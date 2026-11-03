# Team 2: forecasting rain for the canoe trip

## What we built

The original [prototype](README.md) reports recent rainfall. Our experiment
instead forecasts rainfall at one location near Utrecht for **14:30-16:30
CET on 3 November 2026** (13:30-15:30 UTC).

We use KNMI's [RTCOR-5m radar observations](https://dataplatform.knmi.nl/dataset/nl-rdr-data-rtcor-5m-1-0):
rainfall estimates updated every five minutes and corrected using rain gauges.
Our [radar helper](arima/radar.py) downloads the latest images and extracts
the pixel at Utrecht centre by default. It checks timestamps, calibration and
missing data, then writes a CSV of five-minute rainfall totals.

The [ARIMA model](arima/__main__.py) fits an ARIMA(1,1,1) model to recent
rainfall at that location. It forecasts forward in five-minute steps, keeps
the **24 intervals** within the trip window and adds them up. A total of at
least **0.1 mm** is labelled “rain”; this is an exercise threshold, not a
probability. The output also includes a simple persistence baseline: if the
latest five-minute observation is wet, predict rain during the trip.

## Example result

Our [radar CSV](data/radar_utrecht_5min.csv) contains 72 observations ending
at 13:20 CET on 3 November 2026. The saved [forecast](forecast.json), issued
at 13:28 CET using those observations, predicts approximately **0 mm** for
the trip, and persistence also predicts dry. This is a fixed example, **not
an updated forecast**. The CSV is derived from KNMI RTCOR-5m data, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); source:
Royal Netherlands Meteorological Institute (KNMI).

## Run it

With Python 3.12 or later, install dependencies and place a KNMI Open Data
API key in `.config/knmi-api-key`, or set `KNMI_API_KEY`. The key file is
Git-ignored; never commit the key.

```bash
python -m pip install -e ".[dev]"
python -m arima.radar --output data/radar_new.csv
python -m arima --input data/radar_new.csv \
  --start 2026-11-03T14:30:00+01:00 \
  --end 2026-11-03T16:30:00+01:00 > forecast-new.json
```

The download does not overwrite existing files. Forecast timestamps are in
UTC. See the [ARIMA README](arima/README.md) for options, the
[technical report](arima/TECHNICAL_REPORT.md) for the workflow, and
[ARIMA maths](arima/ARIMA_MATH.md) for the model equations.

## What remains

This is a prototype, not a safety advisory. ARIMA cannot see a shower
approaching from outside the chosen pixel, and the forecast is not a
calibrated probability. The pipeline has been exercised with real radar
data, but **forecast skill has not yet been evaluated on historical KNMI
windows**. Next, compare ARIMA and persistence over multiple held-out wet and
dry periods, and consider a radar-based nowcast. For a real trip, consult
current official forecasts, warnings and local water conditions.
