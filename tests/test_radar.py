import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from arima import radar


UTC = timezone.utc
TIME = datetime(2026, 11, 3, 12, 15, tzinfo=UTC)
PROJECTION = "+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60 +a=6378137 +b=6356752 +x_0=0 +y_0=0 +units=km"


def radar_file(value=37, end=TIME):
    buffer = io.BytesIO()
    with h5py.File(buffer, "w") as file:
        geo = file.create_group("geographic")
        geo.attrs["geo_dim_pixel"] = np.bytes_("KM,KM")
        geo.attrs["geo_pixel_size_x"] = [1.0]
        geo.attrs["geo_pixel_size_y"] = [-1.0]
        geo.attrs["geo_column_offset"] = [365.0]
        geo.attrs["geo_row_offset"] = [4079.0]
        projection = geo.create_group("map_projection")
        projection.attrs["projection_proj4_params"] = np.bytes_(PROJECTION)
        image = file.create_group("image1")
        image.attrs["image_geo_parameter"] = np.bytes_("PRECIP_[MM]")
        image.create_dataset("image_data", data=np.array([[value]], dtype="uint16"))
        calibration = image.create_group("calibration")
        calibration.attrs["calibration_formulas"] = np.bytes_("GEO=0.010000*PV+0.000000")
        calibration.attrs["calibration_missing_data"] = [65534]
        calibration.attrs["calibration_out_of_image"] = [65535]
        overview = file.create_group("overview")
        for field, stamp in [
            ("product_datetime_start", end - timedelta(minutes=5)),
            ("product_datetime_end", end),
        ]:
            overview.attrs[field] = np.bytes_(stamp.strftime("%d-%b-%Y;%H:%M:%S.000").upper())
    return buffer.getvalue()


def test_extracts_utrecht_pixel_and_calibrates():
    assert radar.radar_value(radar_file(), TIME, 52.0907, 5.1214) == pytest.approx(0.37)


@pytest.mark.parametrize("value", [65534, 65535])
def test_missing_pixels_are_not_rainfall(value):
    with pytest.raises(ValueError, match="missing"):
        radar.radar_value(radar_file(value), TIME, 52.0907, 5.1214)


def test_rejects_mismatched_times_and_outside_grid():
    with pytest.raises(ValueError, match="timestamp"):
        radar.radar_value(radar_file(), TIME - timedelta(minutes=5), 52.0907, 5.1214)
    with pytest.raises(ValueError, match="outside"):
        radar.radar_value(radar_file(), TIME, 52.0, 5.0)


def test_lists_files_ending_before_cutoff_and_detects_missing(monkeypatch):
    def listing(timestamps):
        return {"files": [
            {"filename": f"RAD_NL25_RAC_RT_{stamp:%Y%m%d%H%M}.h5"}
            for stamp in timestamps
        ], "isTruncated": False}

    times = [TIME + timedelta(minutes=5), TIME, TIME - timedelta(minutes=5)]
    monkeypatch.setattr(radar, "api_get", lambda *args, **kwargs: SimpleNamespace(json=lambda: listing(times)))
    result = radar.recent_files("key", TIME, 2)
    assert [timestamp for timestamp, _ in result] == [TIME - timedelta(minutes=5), TIME]
    monkeypatch.setattr(radar, "api_get", lambda *args, **kwargs: SimpleNamespace(json=lambda: listing(times[:2] + [TIME - timedelta(minutes=10)])))
    with pytest.raises(ValueError, match="Missing"):
        radar.recent_files("key", TIME, 2)


def test_cli_writes_csv_without_overwriting(tmp_path, monkeypatch, capsys):
    output = tmp_path / "rain.csv"
    monkeypatch.setenv("KNMI_API_KEY", "example-key")
    files = [(TIME - timedelta(minutes=5 * i), f"file-{i}") for i in reversed(range(48))]
    monkeypatch.setattr(radar, "recent_files", lambda key, as_of, count: files)
    monkeypatch.setattr(radar, "download_value", lambda item, key, lat, lon: (item[0], 0.1))
    assert radar.main(["--output", str(output), "--count", "48"]) == 0
    assert output.read_text().splitlines()[-1] == "2026-11-03T12:15:00+00:00,0.1"
    assert radar.main(["--output", str(output), "--count", "48"]) == 2
    assert "already exists" in capsys.readouterr().err
