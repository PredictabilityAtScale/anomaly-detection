# Calibrated calendar fallback and empirical ranges

These are opt-in improvements to the current calendar implementation. They do
not port PostHog's full detector or change existing alert thresholds. No new
libraries are required. Keep both options off unless explicitly requested.

```json
"calendar_reference": {
  "profile": "local-calendar-v1",
  "calibrated_fallback": true,
  "expected_range_coverage": 0.95
}
```

Calibrated fallback learns supported calendar tiers in parallel and uses the
narrowest supported tier that was already calibrated. It keeps a broader
comparison available while a preferred tier learns. Calibration remains separate
for each tier, day group and reset segment. Switching keys breaks residual
patterns so evidence cannot accumulate across different calibrations.

Expected ranges collect unscreened earlier absolute prediction errors, separately
from the detector's screened center and scale. The radius is ordered error
`ceil((n+1)*coverage)`, after sufficient sample/date/week support, and takes effect
on the next bucket. Ranges are inspectable evidence; crossing one does not trigger
an alert. Dependence and changing regimes can change later coverage.

## Fresh paired replay

Run from the repository root using the existing environment:

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_calendar_improvements.py --output analysis/calendar-improvements-final
```

The output path must not already exist. This run uses fresh integer hourly data,
not the earlier five-minute leaderboard: 98 days per history, with evaluation
starting on day 35. Three seeded backgrounds are flat (5507), weekly/day-night
(6947), and weekly/day-night with an explicitly declared reset on day 56 (8669).
Each has paired control and injected versions with identical background noise.
Incidents occur on day 42 at 10:00 (+25 for 3 hours), day 61 at 10:00 (-8 for 12
hours), and day 86 at 10:00 (+8 for 24 hours). All timestamps are UTC.

Both arms use unchanged detector settings: trend none, training 48, calibration
24, scale floor 0.4, and default point/pattern criteria. Both request 95% ranges;
only calibrated fallback differs. The original comparison pack remains an
unchanged regression check in `tests/test_comparison_pack.py`, including full
reproduction of the delivered pack. These longer histories supplement that pack
because short fixtures cannot establish mature calendar calibration.

The alerts counted here are point-trigger buckets plus pattern detection buckets.
A false run is a consecutive run of such buckets outside labeled incidents.
Unscored buckets break runs. This is an alert-burden measure, not a notification
policy. A miss has scored incident buckets but no detection; an unassessed
incident has no scored buckets. Delays start at the actual detection bucket.
`incidents.csv` retains scored and unscored counts for partial incident coverage.

## Results

Across the six control/injected histories there are 9,072 evaluation buckets and
nine injected incidents.

| Measure | Current calendar | Calibrated fallback |
| --- | ---: | ---: |
| Scored buckets | 4,576 (50.4%) | 8,300 (91.5%) |
| Unscored buckets | 4,496 | 772 |
| Scored normal buckets | 4,504 | 8,195 |
| False alert buckets | 146 | 332 |
| False alert runs | 130 | 288 |
| False runs / 1,000 scored normal buckets | 28.86 | 35.14 |
| Detected incidents | 4 | 8 |
| Scored misses | 0 | 0 |
| Entirely unassessed incidents | 5 | 1 |

On the **same 4,504 normal buckets scored by both**, current calendar produced
146 false buckets / 130 runs, versus 128 false buckets / 112 runs with fallback.
The larger overall alert burden comes from newly scored periods. Overall false
run rate still rises, so increased coverage is not a free sensitivity gain.
These three synthetic backgrounds do not establish production performance.

### Per-incident detection delay, hours

| Background | Day 42 spike: current / fallback | Day 61 drop: current / fallback | Day 86 rise: current / fallback |
| --- | --- | --- | --- |
| Flat | unassessed / 0 | 0 / 0 | 0 / 0 |
| Weekly | unassessed / 0 | 0 / 0 | 1 / 1 |
| Weekly with reset | unassessed / 0 | unassessed / unassessed | unassessed / 2 |

The four incidents detected by both arms have unchanged delays. The post-reset
day 61 incident still falls before fresh calibration is available. Unavailable
positions and their reasons are retained in `buckets.csv`.

### Expected ranges on later controls

| Measure | Current calendar | Calibrated fallback |
| --- | ---: | ---: |
| Normal control buckets with ranges | 2,288 | 4,150 |
| Observations outside ranges | 66 | 148 |
| Empirical coverage | 97.12% | 96.43% |
| Mean width: flat | 11.43 | 10.55 |
| Mean width: weekly | 10.58 | 12.21 |
| Mean width: weekly with reset | 15.21 | 15.11 |

Both exceed the requested 95% target on these controls. Compare width alongside
coverage: a wider range can cover more without improving usefulness. Native
coverage denominators differ between arms. The target is not an incident
probability or a guaranteed coverage level. Injected-history range coverage is
also exported, but not pooled into these normal-control summaries because
incidents during learning can widen later ranges.

`cases.csv`, `incidents.csv`, `ranges.csv`, `buckets.csv`, `shared.csv` and
`summary.json` provide the underlying grades. The implementation and replay
support keeping fallback available for evaluation, with defaults unchanged.
The next useful test is these same options on the locked five-minute calendar
suite and representative operational histories before any default change.
