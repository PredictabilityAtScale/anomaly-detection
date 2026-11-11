# Portable forecasting and anomaly test cases

This pack follows **all 27 numbered chapters in the repository README**, with
53 cases including paired strategy comparisons and negative controls. These are
synthetic behavior checks, not production incidents or an accuracy leaderboard.

Start with `manifest.csv`: it lists cases in chapter order, the question being
tested, settings, row counts, expected behavior, and actual Anomalyzer status.
`data/` holds the labelled CSVs; `requests/` holds exact runnable Anomalyzer
requests; `baseline/` holds actual detector evidence. `forecasts/` contains
fixed-origin held-out predictions for the dense forecasting cases.
`comparison-cases.zip` packages the entire pack for moving into other tools.

## Import into another tool

1. Start with `data/01_linear_trend.csv`. Choose `timestamp` as time and `value`
   as the numeric measure. Retain the other columns for checking results.
2. Use `series_id` to select **one target at a time**. Relationship cases include
   the aligned sources and the explicitly derived target in the same long-format
   file. Do not concatenate them into one series or sum them together. For
   example, select `conversion` in `12_conversion.csv` to test the ratio itself;
   select the source series to check the marginal volumes separately.
3. Supply the cadence/season from the manifest when the tool supports it. Event
   cases use event position, preserving irregular or equal timestamps and event
   IDs. Do not jitter, average, deduplicate distinct calls, or infer an order from
   their IDs. Category/population cases require a population-comparison feature;
   they are not ordinary numeric forecasting inputs.
4. Keep labels and answers out of model inputs: `is_anomaly`, `anomaly_*`,
   `score_anomaly`, `split`, `anomaly_free_value`, and baseline/forecast files
   are evaluation metadata. Calendar, collection, and declared relationship
   metadata are inputs only when supported explicitly by the tool.
5. Export predictions, retaining `(case_id, series_id, index)`. A blank
   `prediction_template.csv` provides these keys for scoreable rows. Populate
   `predicted_anomaly` with true/false and, where applicable, `predicted_value`.
   A blank prediction means unassessed, not a negative detection. The same keys
   join to the truth CSV named by that case's manifest row.

All CSVs are UTF-8 with headers, decimal points, ISO 8601 timestamps where real
source times exist, lowercase `true`/`false`, and **blank cells for unavailable
values**. Indexes are zero-based. Positional population samples intentionally
have no invented timestamp. No spreadsheet formulas or external data are used.

## Label definitions

| Column | Meaning |
| --- | --- |
| `value` | Value to import. Confirmed empty counts become zero only in the explicit zero policy case. An unfinished period retains its reported progress. |
| `reported_value` | Supplied measurement before an empty-count policy; remains blank for policy-derived zeros. In revision snapshots this is the selected revised measurement; the request retains the original and revision. |
| `value_origin` | `supplied`, `policy_zero`, `revision`, grid origin, or `declared_relationship`. |
| `is_anomaly` | The scenario's declared truth for this target and context, independent of any detector output. False on an unavailable row does not establish normality. |
| `anomaly_kind` | Introduced spike/drop, shift, rule crossing, relationship departure, or population change. |
| `anomaly_scope` | `point`, `interval`, `relationship`, or `population`. Do not equate all of these to an extreme-point test. |
| `anomaly_id` | One introduced point or contiguous change interval. Use it to avoid counting overlapping detections as separate incidents. |
| `score_anomaly` | Row is eligible for point/interval/relationship scoring. False for unknown/incomplete values, unresolved ingestion, invalid retries, and all population rows. It does not assert model readiness. |
| `split` | `train` for indexes 0–59, `test` for 60 onward in the forecasting cases; `not_applicable` elsewhere. This external split is separate from the anomaly detector's own training/calibration windows. |
| `anomaly_free_value` | Exact synthetic value before the declared injection, where construction supplies one. It includes ordinary noise, so it is not a noiseless conditional mean. Blank means no counterfactual has been asserted. |
| `coverage` | Distinguishes complete measurements, complete empty counts, unknown periods, incomplete periods and revisions. |
| `event_id`, `event_sequence` | Logical identity and separately caller-trusted order. Duplicate timestamps are intentional. |
| `reset_before` | Explicit reviewed regime boundary before this row; never inferred from flags. |
| `population`, `weight` | Declared reference/current memberships and consumed-unit weights. Aggregate category weights are not independent event counts. |
| `available_at`, `revision_id` | Selected correction's availability and identity; the full revision/as-of policy remains in the request. |
| `units`, `observation_basis` | Measurement unit and calendar/event/population interpretation. |

Labels are taken from the known synthetic construction and declared evaluation
context, never reverse-engineered from Anomalyzer's flags. Ordinary noise,
growth and recurring cycles remain normal. In chapter 5, later regimes are
unreviewed departures in one case and accepted changes in its reviewed pair.
Chapter 9 does the same for the persistent shift at 60. Comparing those variants
requires passing the reviewed resets to tools that support them. Their labels
evaluate different declared contexts for the same measurements.

## Compare detection and forecasting separately

For row-level detection, join predictions to truth and filter
`score_anomaly=true`. Count true positives, false positives, false negatives and
true negatives; report evaluated rows and abstentions too. Report precision as
TP/(TP+FP) and recall as TP/(TP+FN), leaving zero-denominator results undefined.
Do not report a tool that could not assess a row as having correctly rejected it.

For sustained shifts, additionally group by `anomaly_id` and report whether the
interval was detected, its first detection index, and delay from the first
labelled index. A useful pattern detector can detect the shift once without
flagging every constituent row. In chapter 7 Anomalyzer has zero point flags;
its first location-pattern signal is at 61 after the shift starts at 60.
Chapter 19's unknown hour breaks consecutive runs. In chapter 24, identical
same-time calls do not establish sequence patterns without trusted order.

For forecasting, fit **only indexes 0–59** and forecast the entire remaining
test horizon once, without refitting on later actuals. `forecasts/` records the
training endpoint, each horizon step, actuals, anomaly-free actuals, and genuine
`forecast_with_model` predictions. The candidate is the explicit `anomalyzer`
method with the manifest's declared period/trend/outlier policy (lag 7 for the
season-discovery case), alongside a persistence (`naive`) comparator. This
forward forecast is separate from causal historical anomaly expectations; an
adaptive anomaly recipe does not imply an adaptive future forecast. No automatic
model search or holdout-driven setting selection is used.

Compare MAE and RMSE against test `value`, and separately compare MAE against
`anomaly_free_value` to see how much misses reflect injected incidents versus
ordinary forecast fit. The manifest records those same baseline errors.
Forecast error alone does not measure anomaly detection. Do not pool losses in
different units or count paired variants as independent datasets.

For chapters 25–27, `is_anomaly=true` labels membership in a changed population,
**not an abnormal individual call**. Use `expected_population_change` in the
manifest and compare the whole populations, windows or category composition.
The numeric monitor's change begins at 160; the actual baseline first detects at
182 with its frozen reference and declared testing budget. Ordinary numeric
populations and matched morning batches are negative controls. The seasonal
file retains the full history pool and later excluded observations; use the
request's timezone, schedule and as-of cutoff to select references, never the
entire CSV indiscriminately. Weighted aggregates support descriptive change
only; weighted-report inference permutes genuine reports, not weight units.

## Reading Anomalyzer's baseline

Detector CSVs retain `series_id`, `resolution`, `method`, `index`, `event_id`,
expected value, `point_flag`, first pattern-detection rules, assessment
classifications, evidence maturity, readiness and status. A pattern is recorded
at its **first detection**, not backfilled as if every interval point had
already been flagged. `criterion_violation` can exist with insufficient history
and without a statistical point flag. Missing baseline rows mean no exported
assessment/reference, not a negative prediction.

Completed daily and intraday methods are separate correlated views: do not join
their indexes together or count them as independent votes. Data CSVs retain the
source observations; completed-day aggregates and incompleteness policy are
reproduced by the exact request. Population baselines are JSON to retain
reference selection, testing budgets, p-values, effect gates and limitations.

`partial`, `insufficient_history`, `descriptive`, `horizon_exhausted` and
`expected_rejection` are intentional test outcomes, not success/failure labels.
Chapter 24's retry is invalid input: every row is excluded from scoring and no
baseline CSV is emitted. The selected before/after correction snapshots keep
`call-07` at its original timestamp with values 0.80 and 0.85 respectively.

## Reproduce and review

From the repository root on Windows:

```powershell
.venv/Scripts/python examples/comparison/generate.py
.venv/Scripts/python -m pytest tests/test_comparison_pack.py -q
```

On Unix use `.venv/bin/python`. The generator loads this checkout's `src/`
explicitly, so an older installed wheel cannot silently supply the baseline.
It uses existing checked-in fixtures and reproduces the README's synthetic
formulas; it does not edit those originals. `checksums.json` records the source
Anomalyzer version and SHA-256 of pack files. The ZIP has fixed entry timestamps.
Use `--output PATH` to write a comparison pack in a separate directory.

For a manual review, inspect each case's first labelled anomaly and its preceding
normal row, plus a gap, a policy zero, an explicit reset, and a same-time event.
Confirm the target, units, availability and reviewed context survive import
before interpreting differences between tools. These short examples demonstrate
mechanics and evidence limits; representative incident histories are needed to
estimate deployment precision, recall or operational usefulness.
