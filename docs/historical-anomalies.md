# Native historical anomalies with forecast_series (0.7.0)

This additive API lets a caller select its forecast method and its
anomaly detector independently. One public `forecast_series` call returns a
scenario and, when requested, native evidence from its existing historical
analysis. It performs no second analysis, inference or historical fit. The
historical model is separate from the trailing forward scenario model.
`analyze`, distribution APIs and Guard recipes keep their existing behavior.

The API requires **0.7.0**, using `forecast-v1` plus the opt-in
**`historical-anomalies-v1`** extension. Use the verified immutable release
artifact, not an earlier development build. Released v0.6.0 and earlier assets remain intact.
Changing these evidence semantics requires a new evidence contract version;
do not infer support from the presence of the old forecast function.

```python
from anomalyzer import ForecastSettings, HistoricalAnomalySettings, forecast_series

values = [100.] * 80 + [400.] + [100.] * 9
result = forecast_series(values, ForecastSettings(
    horizon=30, lower_bound=0,
    historical_anomalies=HistoricalAnomalySettings(
        point_threshold=3, cusum_k=.5, cusum_h=5,
        moving_range_threshold=3.686, scale_floor=1e-8),
))
if result.status == "completed":
    point = result.historical_anomalies.points[80]
    assert point.triggers == ["point"]
    print(point.expected, point.residual, point.standardized_score)
else:
    print(result.reason)  # no partial evidence on failure
```

In canonical JSON put `"historical_anomalies": {"schema_version":
"historical-anomalies-v1"}` inside `config`. Omitting the field or passing null
leaves the extension disabled; the result field is null. `{}` explicitly enables
defaults. All threshold values must be finite positive numbers. Unknown keys and
unknown extension versions are invalid input. No severity setting belongs here.
Default thresholds reproduce the existing native historical analysis; changing
detector thresholds does not change the forward scenario. `scale_floor` affects
historical trend fitting/calibration; seasonality selection retains the existing
forecast selection policy and numerical floor of 1e-8.

Public types include `HistoricalAnomalySettings`, `HistoricalAnomalyPoint`,
`HistoricalPattern`, `HistoricalReferenceAdjustment`, `HistoricalCalibration`,
`HistoricalDetectorSettings` and `HistoricalAnomalies`. The exact machine contracts
are [forecast request](../schemas/forecast-request.schema.json),
[forecast result](../schemas/forecast-result.schema.json),
[extension settings](../schemas/historical-anomalies-request.schema.json) and
[extension result](../schemas/historical-anomalies-result.schema.json).
Regenerate them with `python scripts/export_forecast_schemas.py`.

## Point evidence and availability

`points` has exactly N entries in original order, including hidden training
history and partial tails. Every coordinate is a zero-based original position.
Index availability means **after that bucket is finalized and observed**, not
its timestamp's bucket start. Ingestion latency is unknown; a caller must apply
its real arrival/completeness policy. Complete zero is an observation.

| Point field | Contract |
| --- | --- |
| `index`, `period_status`, `observed` | Original position, complete/partial status and supplied signed measurement (nullable for partial). |
| `availability`, `unavailable_reason` | available or unavailable; unavailable reason is warmup or partial. An available reference can still have no calibrated score. |
| `available_from_index`, `reference_cutoff_index` | Target index and index-1 for available evidence; both null when unavailable. No target or suffix participates in its own reference. |
| `expected`, `residual` | Signed native detector reference and `observed - expected`, nullable when unavailable. |
| `standardized_score`, `score_semantics` | Finite nullable native score and its interpretation; never infinity, probability, confidence, accuracy or health. |
| `triggers` | Empty or `["point"]`; only calibrated scores with strict `abs(score) > point_threshold` trigger. |
| `direction` | increase/decrease/flat according to raw residual sign; null without a reference. The sign of a centered score can differ. |
| `maturity` | unavailable, reference_only, provisional or calibrated; neither provisional nor reference_only can trigger. |
| `calibration_samples`, `calibration_cutoff_index` | Number of earlier supporting residuals, retained count after robust calibration, and inclusive cutoff of the supporting window. Null cutoff when no samples. Cutoff includes screened positions; it is not a claim that every position was retained. |

Auto historical selection freezes the original prefix
`K=min(max_training_points,max_inference_points)`. No reference is published
before index K. Calibration uses positions K through K+13; K through K+2 are
reference_only, K+3 through K+13 have provisional scores using earlier incomplete
calibration. Index K+14 is the first calibrated point. Bridge K is 768/56/52/36
for hour/day/week/month. Explicit seasonality retains the existing training
size `max(28,period)` instead. A short series can have an available scenario
while the entire evidence extension is unavailable/warmup.

Provisional scores use the mean and sample standard deviation of earlier
calibration residuals, with the configured scale floor. Calibrated scores use
`(residual - calibration.center) / calibration.scale`, where
`scale=max(raw sample standard deviation,scale_floor)`. The center/scale freeze
before evaluation. Robust mode can screen calibration extremes and rebuild
their later reference chain at K+14. Consequently the final calibration statistics
need not equal statistics recomputed from the displayed earlier provisional
rows. Those rows preserve what was causally available then. Tiny variance may
make tiny changes produce large scores; readiness commonly reports caution.
Calibrated maturity does not promise an adequate baseline or calibrated alert rate.

Forecast-v1 top-level `expected` is a **display** reference with `lower_bound`
applied. Evidence `expected` is always the signed native reference used for
residuals and scores. For observed=-10 and native expected=-10 with lower_bound=0,
display expected=0, native residual=0 and native score=0. Do not recompute or label
the native score as a residual against the display-clamped expectation. Public
`trend` and seasonal components remain signed; no lower-bound change is made.

Missing positions, internal gaps and non-tail partials retain the existing
explicit unavailable/missing_history behavior for the whole forecast, with no
partial evidence payload. There is no gap fill, compressed coordinate or invented
zero. Failed/budget-exceeded results likewise carry no partial evidence.

## Provenance and model operations

| Extension field | Contract |
| --- | --- |
| `schema_version`, `engine_version`, `recipe` | Evidence version, exact package build and seasonal-residual-v1 recipe. |
| `availability`, `unavailable_reason` | Whether any historical reference is available; otherwise unavailable/warmup. Not equivalent to any calibrated detection being available. |
| `origin_fingerprint` | SHA-256 of engine version, resolved historical settings, original training values and dataset id/interval/timezone/training timestamps; null until training completes. |
| `calibration_fingerprint` | SHA-256 of origin fingerprint plus calibration observations; null until calibration is frozen. Identifies frozen calibration, not every later rolling reference. |
| `resolved_settings` | Typed recipe, training/calibration sizes, trend choice, resolved season length (null until auto selection completes), robust/include and four-reference policy, point/CUSUM/moving-range thresholds and scale floor. `reference_exclusion_threshold` is the engine's separate extreme threshold (8 in robust mode, null in include mode). |
| `selection_window`, `training_window`, `frozen_trend` | Inclusive original windows and native historical trend-fit diagnostics; unavailable windows/fit are null. These describe the historical model, not the forward fit. |
| `calibration` | Frozen center, raw_scale, scale, retained samples, cutoff_index and available_from_index; null until calibrated evaluation starts. |
| `readiness`, `readiness_available_from_index` | Native training/calibration caution/support diagnostic and first availability, or null availability before assessment. Never a per-point health classification. |
| `reference_adjustments` | Separate model operations: original index, observed, replacement, reason and available_from_index. Training screening is known at K, calibration screening at K+14, evaluation replacements at the target. |
| `points`, `patterns`, `limitations` | Aligned point stream, first-detection pattern snapshots and interpretation limits. |

An excluded training/calibration point is **not** an anomaly. A calibrated point
may independently trigger and be replaced for future references, but those are
separate decisions. Top-level `outlier_indices` remains the existing union of
forward screening and historical reference adjustments for compatibility. Never
turn that union into incidents. Forward `model.outlier_policy` continues to expose
its screening/trimmed-reference policy; no historical replacements enter its fit.

The ordinary `request_fingerprint` covers the full forecast request, including
observations, horizon and evidence configuration; it changes on append. The two
historical fingerprints identify the frozen origin/calibration independently of
horizon, display lower bound and scenario adjustment. They do not replace a
cache key for the complete input series. Changing the leading origin, training
prefix, timestamps, settings or engine version can change historical evidence.
With the same origin/settings, changing a target can change its own residual and
score, and later references, but cannot change earlier point rows or its own
expectation. Changing/appending a later suffix cannot rewrite earlier point rows
or pattern snapshots. A previously partial target can gain evidence when finalized.

## Supported patterns, separately from points

These are the engine's existing rules over contiguous **calibrated residuals**.
No new detector is invented. Patterns do not require individual point triggers,
except the consecutive-point rule. They are exploratory and correlated; repeated
testing, residual autocorrelation, tails and short calibration affect alert rates.

| `rule` | Criterion / kind |
| --- | --- |
| adjacent_point_anomalies | At least two adjacent native point triggers; consecutive_run. |
| nelson_rule_2 | Nine scores strictly on one side of zero; possible location_shift. |
| nelson_rule_5 | Two of three scores strictly beyond +2 or -2 on the same side; location_shift. |
| nelson_rule_6 | Four of five strictly beyond +1 or -1 on the same side; location_shift. |
| cusum | One-sided recurrence `max(0, previous + sign*score - k)` strictly above h; location_shift. Defaults k=.5, h=5. |
| nelson_rule_3 | Six scores strictly increasing or decreasing; residual_trend diagnostic. |
| nelson_rule_4 | Fourteen scores with strictly alternating differences; systematic_oscillation diagnostic. |
| nelson_rule_8 | Eight scores all strictly outside +/-1, on both sides; mixture_pattern diagnostic. |
| moving_range | Adjacent score difference strictly above moving_range_threshold (3.686 default); variation_shift diagnostic. |

Each pattern carries stable `id` (`rule:start:detection:direction`), `rule`, `kind`,
`direction`, `start_index`, `detection_index`, `available_from_index`,
`triggering_indices` and `peak_standardized_score`. The interval and peak stop
at **first detection**, with availability equal to detection_index. Do not paint
the pattern as known at its earlier start. All triggering indices are the native
window through that detection, including any non-extreme positions in the window.
Overlapping native windows/excursions are grouped as in the engine; a growing run
does not emit a new event every point or grow its original snapshot. Patterns in
opposite directions can overlap. Peaks use absolute scores through detection.

The engine's usual `analyze` pattern summaries extend merged intervals and peaks
through the supplied suffix. Those are retrospective summaries; they are not
copied as historical detections here. This extension truncates those summaries
to their first-detection evidence and recalculates only descriptive peak/run
direction, without recalculating a forecast, score or detector threshold. These
snapshots describe evidence about the residual process, not business incidents,
full-distribution shifts or independently corroborating probabilities.

## Consumer boundary

Use native calibrated `triggers` for statistical qualification. Retain business
minimum absolute usage/deviation, percent movement, low-volume gates and explicit
warning/critical presentation policy in UsageTap. A business gate can suppress a
native trigger; it must not manufacture native evidence or recompute its own
z-score. If severity uses score cutoffs, apply them to the returned native score
after native qualification and label that policy. Native point_threshold=3
deliberately differs from UsageTap's current warning z cutoff=2.5; choose and
record the native setting explicitly rather than claiming identical algorithms.
Pattern presentation requires its own explicit consumer policy. See the
[migration guide](usagetap-forecast-migration.md) for independent selectors,
baseline labels, cache metadata and the single-call adapter.


Since 0.8.0, the forecast-only `baseline="recent-level-v1"` option may select a
smoothed historical reference on the frozen training prefix. Native residuals,
calibration, maturity and readiness use that reference; the forward fit cannot
rewrite it. `resolved_settings.forecast_baseline` and `level_baseline` disclose
its version and selection. Default `legacy` and standalone detector recipes keep
their existing numerical behavior. See the [baseline selection contract](forecasting.md#smoothed-recent-level-opt-in-since-080).
