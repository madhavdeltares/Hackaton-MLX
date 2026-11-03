"""Download KNMI five-minute radar observations for one location."""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

import h5py
import requests
from pyproj import CRS, Transformer

from arima.__main__ import parse_timestamp

BASE_URL = (
    "https://api.dataplatform.knmi.nl/open-data/v1/datasets/"
    "nl_rdr_data_rtcor_5m/versions/1.0/files"
)
FILENAME = re.compile(r"RAD_NL25_RAC_RT_(\d{12})\.h5")
CALIBRATION = re.compile(r"GEO=([+-]?\d+(?:\.\d+)?)\*PV([+-]\d+(?:\.\d+)?)")
INTERVAL = timedelta(minutes=5)


def api_get(url: str, *, key: str | None = None, params: dict | None = None) -> requests.Response:
    headers = {"Authorization": key} if key else {}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        raise ValueError(f"KNMI request failed with HTTP {status}") from None
    except requests.RequestException as error:
        raise ValueError(f"KNMI request failed ({type(error).__name__})") from None
    return response


def recent_files(key: str, as_of: datetime, count: int) -> list[tuple[datetime, str]]:
    files: list[tuple[datetime, str]] = []
    token = None
    while len(files) < count:
        params = {"maxKeys": min(count, 500), "sorting": "desc"}
        if token:
            params["nextPageToken"] = token
        data = api_get(BASE_URL, key=key, params=params).json()
        for item in data["files"]:
            name = item["filename"]
            match = FILENAME.fullmatch(name)
            if not match:
                raise ValueError(f"Unexpected radar filename: {name}")
            timestamp = datetime.strptime(match.group(1), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            if timestamp <= as_of:
                files.append((timestamp, name))
                if len(files) == count:
                    break
        if len(files) < count:
            next_token = data.get("nextPageToken")
            if not data.get("isTruncated") or not next_token or next_token == token:
                raise ValueError(f"Only {len(files)} observations available before the cutoff; need {count}")
            token = next_token
    files.sort()
    for previous, current in zip(files, files[1:]):
        if current[0] - previous[0] != INTERVAL:
            raise ValueError(
                f"Missing or duplicate radar files between {previous[0].isoformat()} and {current[0].isoformat()}"
            )
    return files


def radar_value(content: bytes, timestamp: datetime, latitude: float, longitude: float) -> float:
    try:
        with h5py.File(io.BytesIO(content), "r") as file:
            geo = file["geographic"]
            image = file["image1/image_data"]
            if image.ndim != 2 or geo.attrs["geo_dim_pixel"].decode() != "KM,KM":
                raise ValueError("Unsupported radar grid")
            if file["image1"].attrs["image_geo_parameter"].decode() != "PRECIP_[MM]":
                raise ValueError("Unsupported radar measurement or units")
            projection = geo["map_projection"].attrs["projection_proj4_params"].decode()
            crs = CRS.from_proj4(projection)
            if any(axis.unit_name != "kilometre" for axis in crs.axis_info):
                raise ValueError("Unsupported radar projection units")
            x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(longitude, latitude)
            col = math.floor(x / float(geo.attrs["geo_pixel_size_x"][0]) - float(geo.attrs["geo_column_offset"][0]))
            row = math.floor(y / float(geo.attrs["geo_pixel_size_y"][0]) - float(geo.attrs["geo_row_offset"][0]))
            if not (0 <= row < image.shape[0] and 0 <= col < image.shape[1]):
                raise ValueError("Location is outside the radar grid")
            overview = file["overview"].attrs
            start = datetime.strptime(overview["product_datetime_start"].decode(), "%d-%b-%Y;%H:%M:%S.%f").replace(tzinfo=timezone.utc)
            end = datetime.strptime(overview["product_datetime_end"].decode(), "%d-%b-%Y;%H:%M:%S.%f").replace(tzinfo=timezone.utc)
            if end != timestamp or end - start != INTERVAL:
                raise ValueError("Radar file timestamp or accumulation interval does not match the filename")
            calibration = file["image1/calibration"].attrs
            raw = int(image[row, col])
            if raw in (int(calibration["calibration_missing_data"][0]), int(calibration["calibration_out_of_image"][0])):
                raise ValueError("Radar data is missing at the chosen location")
            formula = calibration["calibration_formulas"].decode()
            match = CALIBRATION.fullmatch(formula)
            if not match:
                raise ValueError(f"Unsupported radar calibration: {formula}")
            value = raw * float(match.group(1)) + float(match.group(2))
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid calibrated rainfall amount")
            return value
    except (OSError, KeyError) as error:
        raise ValueError(f"Invalid radar file: {error}") from error


def download_value(item: tuple[datetime, str], key: str, latitude: float, longitude: float) -> tuple[datetime, float]:
    timestamp, name = item
    url = f"{BASE_URL}/{quote(name, safe='')}/url"
    temporary_url = api_get(url, key=key).json()["temporaryDownloadUrl"]
    content = api_get(temporary_url).content
    return timestamp, radar_value(content, timestamp, latitude, longitude)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", type=Path, default=Path(".config/knmi-api-key"))
    parser.add_argument("--output", type=Path, default=Path("data/radar_utrecht_5min.csv"))
    parser.add_argument("--lat", type=float, default=52.0907, help="Latitude (default: Utrecht centre)")
    parser.add_argument("--lon", type=float, default=5.1214, help="Longitude (default: Utrecht centre)")
    parser.add_argument("--count", type=int, default=72, help="Number of five-minute observations (default: 72)")
    parser.add_argument("--as-of", help="Latest observation time, ISO 8601 with UTC offset")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.lat) or not -90 <= args.lat <= 90 or not math.isfinite(args.lon) or not -180 <= args.lon <= 180:
            raise ValueError("Invalid latitude or longitude")
        if not 48 <= args.count <= 400:
            raise ValueError("count must be between 48 and 400")
        key = os.environ.get("KNMI_API_KEY") or args.api_key_file.read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError("KNMI API key is empty")
        as_of = parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        files = recent_files(key, as_of, args.count)
        if args.output.exists():
            raise ValueError(f"Output file already exists: {args.output}")
        print(f"Downloading {len(files)} radar files for {args.lat}, {args.lon}...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=4) as executor:
            values = list(executor.map(lambda item: download_value(item, key, args.lat, args.lon), files))
        with args.output.open("x", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["timestamp_utc", "precipitation_mm"])
            writer.writerows((timestamp.isoformat(), amount) for timestamp, amount in values)
    except (OSError, ValueError, KeyError, requests.RequestException) as error:
        print(f"Unable to download radar data: {error}", file=sys.stderr)
        return 2
    print(f"Saved {len(values)} observations to {args.output} ({values[0][0].isoformat()} to {values[-1][0].isoformat()}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
