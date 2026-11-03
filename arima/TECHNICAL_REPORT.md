# Technical report: forecasting rainfall with ARIMA

## 1. The question

We want to help answer: **how much rain might fall near our canoe trip in
Utrecht between 14:30 and 16:30 on 3 November 2026?** This is a forecast of
rainfall at one chosen location, not a forecast of conditions along the entire
route or a safety assessment.

The existing [hackathon prototype](../README.md) describes rainfall that has
already fallen. This experiment takes the next step: use past rainfall to
predict a future window. It supports the [backlog](../BACKLOG.md) goal of
testing a model against a simple persistence baseline.

## 2. What goes in?

The model expects a CSV containing a single, regularly spaced series of
rainfall observations. By default, each row is the **total precipitation in
millimetres over the preceding five minutes** at the same location:

```csv
timestamp_utc,precipitation_mm
2026-11-03T12:50:00Z,0.0
2026-11-03T12:55:00Z,0.1
2026-11-03T13:00:00Z,0.2
```

These are **illustrative numbers**, not KNMI observations. The last row
describes the five minutes ending at 13:00 UTC, not the five minutes starting
then. On 3 November 2026, Utrecht is on CET (UTC+1), so that interval is
13:55-14:00 local time. Each timestamp must include an offset such as `Z` or
`+00:00`.

The data team can derive this series from a suitable KNMI product, for example
a consistent radar pixel near the route, or a suitable station if
five-minute rainfall totals are available. They must verify the product's
location, units and timestamp convention; rainfall rates or cumulative
measurements need conversion to **five-minute totals** first. Do not mix
different locations or data sources in the same series. The program does not
download KNMI data or convert raw KNMI files, and the bundled hourly exercise
data cannot represent this particular window exactly.

The loader rejects duplicate timestamps and missing, negative or non-finite
values. Within the selected history it also checks that observations are
regularly spaced. Missing observations must not be silently treated as zero:
zero means *measured dry*, while missing means *unknown*. Other regular
interval lengths can be supplied with `--interval-minutes`, as long as both
window boundaries align with the data.

## 3. The forecasting strategy

Think of a rain gauge as a notebook with a new number every five minutes.
ARIMA tries to learn patterns in this one sequence and continue it into the
future. It does not see a radar map or know the weather elsewhere.

Each run fits a new **ARIMA(1,1,1)** model using the available history:

1. Select observations ending no later than the forecast issue time. The
   default history window is the preceding 168 hours (seven days), though a
   full seven days is not required: the code requires at least 48 consecutive
   observations within that window.
2. Transform each rainfall amount using `log(1 + rainfall_mm)`. This reduces
   the relative influence of very large values while keeping zero as zero.
3. Fit the model's parameters to the transformed observations using
   `statsmodels`. The model is fitted at run time, not loaded from a
   previously trained file.
4. Forecast forward at the same interval spacing, convert the predicted values
   back to millimetres using `exp(prediction) - 1`, and clip negative
   predictions to zero.

The three numbers in `(1,1,1)` describe the structure:

- **AR(1), autoregression:** the previous change helps predict the next
  change.
- **I(1), integration:** the model works with the difference between
  consecutive transformed observations, rather than modelling their level
  directly.
- **MA(1), moving average:** the previous unexpected model error also
  contributes. This is not a rolling average of rainfall.

For the transformed series `z`, the simplified relationship is
`change(z_t) = phi * change(z_(t-1)) + error_t + theta * error_(t-1)`.
The fitting process estimates `phi` and `theta` from the selected history;
the model does not assume in advance that an increase must continue.
Differencing can help with changing levels, but it does not guarantee a
stationary series. `(1,1,1)` is a starting choice, not a configuration
validated as best for this dataset.

## 4. How do we get 14:30-16:30?

The program accepts window boundaries with explicit UTC offsets. For this
trip, **14:30-16:30 CET is 13:30-15:30 UTC**. The first interval in the
result is 14:30-14:35 local time; the last is 16:25-16:30. Thus the
two-hour total is the sum of **24 five-minute predictions**.

For example, suppose the latest observation available at issue time ends at
**14:00 CET**. The model forecasts:

| Forecast period, CET | Five-minute intervals | Included in trip total? |
|---|---:|---|
| 14:00-14:30 | 6 | No: these bridge the lead time to departure |
| 14:30-16:30 | 24 | Yes |

It therefore forecasts 30 intervals from the latest observation, discards the
first six for the trip calculation, and sums the remaining 24. If the latest
observation is older, the lead time is longer; check the output timestamp.
For example, 12:45 CET is 1 hour 45 minutes before departure and 3 hours
45 minutes before the end of the trip, even though the trip itself is only
two hours long.

The default issue time is the earlier of the current time and the window
start. Only observations ending at or before that time enter the fit. Use
`--as-of` for an explicit, reproducible cutoff. If running after departure,
the default is a **retrospective simulation** using data up to the start, not
a forecast actually issued at departure. The program does not verify when an
observation became available, so historical evaluations must account for
data-release delays.

## 5. What comes out?

The command prints JSON. Key fields are:

| Field | Meaning |
|---|---|
| `interval_forecasts` | Predicted rainfall in mm for each interval, with start and end times in UTC |
| `forecast_total_mm` | Sum of the predicted interval totals in the requested window |
| `forecast_predicts_rain` | `true` if the predicted window total is at least the threshold |
| `rain_threshold_mm` | Threshold for that yes/no decision; default **0.1 mm over the whole window** |
| `persistence_predicts_rain` | `true` if the latest five-minute observation is greater than zero |
| `as_of_utc`, `latest_observation_utc` | Forecast cutoff and the end time of the latest observation used |
| `training_observations`, `arima_order` | Number of values used and model specification |

The threshold is an exercise choice, not a safety limit. The yes/no result is
derived from the estimated total; it is **not a probability of rain**. The
persistence rule extends the backlog's “raining now means rain next hour”
idea to the whole two-hour window, and checks whether the most recent
five-minute reading is nonzero.

## 6. Running and evaluating it

After installing the project dependencies, and once the normalized data exists:

```bash
python -m pip install -e ".[dev]"
python -m arima --input data/rain_5min.csv \
  --start 2026-11-03T14:30:00+01:00 \
  --end 2026-11-03T16:30:00+01:00
```

See the [ARIMA README](README.md) for the data requirements and command
options. To evaluate a **completed historical window**, add `--as-of` at or
before its start and `--evaluate`, with observations available through the
end of that window. The code compares the predicted total with the observed
total and reports the rain/dry correctness of both ARIMA and persistence.
Window observations are used only for evaluation, not fitting.

One successful run or one historical example does not establish accuracy.
Test multiple held-out dates, including dry, light-rain and heavier-rain
periods; use the same issue times and target threshold for every method.
Report errors and missed rain as well as correct predictions. No evaluation
on real KNMI data has yet been established in this repository.

## 7. Limitations

- The model only sees rainfall at one location. It cannot see a shower
  approaching Utrecht from elsewhere, and it does not use wind or humidity.
- Rainfall is often zero and can change abruptly. A linear ARIMA model may
  smooth or miss these events, particularly over longer lead times.
- A fit can fail to converge, especially for constant dry data. The program
  reports an error instead of silently returning a forecast.
- Reversing the log transformation and clipping negative values produces a
  point estimate, not necessarily an unbiased expected total or a calibrated
  probability. No forecast uncertainty interval is currently output.
- Synthetic-data tests show the code can run and select the intended window;
  they do not prove forecast skill. For an actual trip, consult current
  official forecasts, warnings and local water conditions.
