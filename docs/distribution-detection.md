# Distribution detection and UsageTap handoff (0.4.0)

Version 0.5.0 adds [explicit seasonal reference selection](seasonal-distributions.md)
ahead of these unchanged population detectors. UsageTap can supply bounded history
and a declared timezone/daily-or-weekday policy instead of selecting similar priors itself.

The additive `distribution-v1` contract compares populations of calls or reports.
It does not change the schema-1.0/1.1 seasonal/residual algorithms or their case
policy. Python, JSON CLI and read-only MCP call the same numerical implementation.
No NumPy, SciPy or hosted service is required. The package remains alpha.

## Choose a measurement

| UsageTap check | Input and interpretation |
| --- | --- |
| Cache reuse | Numeric `cached_input / input` per measured call; retain measured zeros. Optionally compare the separate numeric 0/1 indicator of any cache read. |
| Output/input | Numeric ratio per call; zero or missing input produces null, never an invented ratio. |
| Output size | Numeric output tokens per completed call; changes in shape need not change the mean. |
| Feature mix, updates | Categorical feature label per genuine metering submission. |
| Feature mix, consumed calls/units | Supply each genuine report's category and positive measured `weight` (quantity). Permute whole reports; sample support counts reports, not units. Aggregate-only unit totals are descriptive. |
| Completion reasons | Categorical reported provider reason; missing reason remains null. |
| Errors / measurement coverage | Numeric 0/1 per eligible attempted call; include failures in an appropriate denominator. Missing outcome is unknown. |
| API call rate | Continue using a time/exposure-aware detector; event positions do not establish elapsed rates. |

Keep application-wide behavioral comparisons. Use workload/model/customer context
where it explains differences, without partitioning away the change being
monitored. Independent customer comparisons need their own populations and budgets.
Keep updates and consumed quantities separate: batching can change the former
while the latter stays unchanged. Do not pool different meter units.

## Compare explicit populations

```python
from anomalyzer import compare_distributions

def population(values, prefix):
    return {"samples": [
        {"id": f"{prefix}-{i}", "value": value}
        for i, value in enumerate(values)
    ]}

result = compare_distributions({
    "kind": "numeric",
    "entity": {"application": "example"},
    "units": "cache_read_fraction",
    "reference": population([0, .25, .5, .75, 1] * 80, "before"),
    "current": population([0, 0, .5, 1, 1] * 80, "after"),
    "assume_exchangeable": True,
    "config": {"alpha": .01, "min_effect": .05},
})
assert result.change_detected  # both populations have mean .5
```

Inputs require an entity and one declared unit, a `kind` (`numeric` or
`categorical`), and two populations with disjoint logical sample IDs. IDs are
case-sensitive; duplicate deliveries must be deduplicated upstream. All numeric
values must be finite; booleans are rejected (use explicit 0/1). Categories are
trimmed strings up to 128 characters, with at most 128 categories across both
populations. Each population supports up to 4,096 observations.

Samples contain `id`, `value`, optional offset-aware `timestamp`, and `complete`
(default true). `value=null` is unknown. Explicit comparisons exclude unknown
and incomplete observations and report their IDs/counts; `missing_current="break"`
instead makes a current population containing either unavailable. Samples are
never trimmed as outliers and legitimate zero-heavy mixtures retain their hits.
The caller must assess whether excluded measurements are representative.

Categorical samples additionally accept positive finite `weight` (default 1).
For consumed-unit mix, provide the actual quantity of each report, for example
`{"id":"report-1","value":"export","weight":250}`. The test reassigns the
**whole category/quantity event** between populations and preserves their report
counts. A report containing 250 units is one observation. Scaling every quantity
by the same factor changes neither support nor the p-value. Report totals are
inspectable as `total_weight`. Zero/unknown consumed quantity cannot supply a
positive weighted observation; keep it in a separate updates/coverage comparison.
Numeric samples require weight 1. The [weighted-report example](../examples/distributions/weighted-reports.json)
preserves report category counts and total units while changing which categories
consume those units; it produces statistical evidence using actual reports.

For weighted categorical composition use `{"weights":{"search":900,"export":100}}`
for **both** populations instead of samples. The engine reports Jensen-Shannon
divergence, share changes and total variation with `status="descriptive"` and
`p_value=null`. Weight totals never supply sample support. Even an exchangeability
assertion cannot turn weights into a statistical finding.

## Numerical methods

Numeric `ks_tie_exact` reports the maximum absolute difference between empirical
CDFs. Its effect is a share difference, not a difference in metric units. Exact
conditional label-permutation probabilities account for **whole tied-value
groups**, including many zeros. Dynamic programming counts event assignments
using integer arithmetic, including outcomes equal to the observed distance.
There is no continuous-distribution KS p-value approximation, binning, learned
sigma, residual fitting or automatic zero removal.

Categorical `jensen_shannon_permutation` measures whole-composition divergence
in base-2 bits (0..1). Its null distribution reassigns pooled category/quantity
events together while preserving population sizes. All assignments are enumerated when their count
is at most `permutations`; otherwise a reproducible pseudorandom sample uses
`(extreme+1)/(permutations+1)`, never a zero Monte Carlo p-value. Default
`permutations=9999`, `seed=0`; choose and retain the seed before looking at
results. Category rows explain share changes; they are not independent tests.
Total variation is descriptive supporting evidence. Numeric KS and categorical
divergence have different effect units: select practical thresholds separately.

`assume_exchangeable` defaults to false: results stay descriptive unless the
caller explicitly asserts that observations can be treated as independent,
exchangeable draws under the no-change hypothesis. Unique IDs and sorted times
do not establish this. Sessions, task fan-out, retries, serial dependence and
changing workload composition can invalidate inference. This version does not
estimate a block length or perform dependence-aware/block permutation.

Background on the statistics: [KS distribution comparisons](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html)
and [independent permutation tests and the plus-one convention](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html).
These references explain the methods, not product effectiveness; SciPy is not a dependency.

## Evidence, thresholds and resource limits

Results separately expose `statistical_change` (`p_value <= threshold`),
`practical_change` (positive effect at least `min_effect`), and `change_detected`
(both). `business_impact` remains `unresolved`. Default minimum support is 32
reference and 16 current measured events, not token counts or elapsed slots.
These floors prevent tiny comparisons; they do not guarantee adequate power.

`alpha=.01` is a testing-budget choice, **not incident confidence**. For a
predeclared family of `max_comparisons=M`, each threshold is `alpha/M` and
`adjusted_p_value=min(1,M*p_value)`. `comparison_index` must be in `0..M-1`.
The application owns index uniqueness and persistence. Bonferroni permits
overlapping windows but does not repair invalid sampling assumptions. It is
conservative; large families reduce power. Do not keep testing at .01 per call,
change the family size after inspecting results, or restart the budget on each run.

Statuses are `completed`, `descriptive`, `insufficient_history`,
`resolution_limited`, or `budget_exceeded`. If the smallest possible permutation
p-value exceeds its allocated threshold, inference is `resolution_limited` and
cannot trigger. Raise the permutation count or revise the prospective plan,
never the seed merely to obtain a finding. The runtime budget (default 30 seconds)
is cooperative; a timed-out test retains support but cannot produce a finding.
No status establishes normality or validates operational alert precision.

Population fingerprints and retained/excluded IDs expose reference membership.
Numeric summaries include mean, median, range and zero frequency. Corrected
measurements produce new fingerprints. There is no arrival ledger, automatic
deduplication, as-of revision selection or persistent state in this API: supply
the caller's selected, available snapshot. Permutation results are reproducible
for the same request; changes to populations/configuration can revise evidence.

## Causal monitoring

`monitor_distributions` accepts the same kind/entity/unit and a single ordered
`samples` list, plus `monitor_id`, `reference_size`, `window_sizes`, `stride`,
and `max_looks`. The **first original positions** form the frozen reference;
current windows never overlap it. Defaults: 128 reference positions, windows
32 and 128, stride 1, 32 planned looks. A 32-look family starting with a 32-event
window will not yet reach the 128-event window; choose the horizon prospectively
to support larger windows (the example uses 129 looks).

The first look ends after `reference_size + min(window_sizes)` positions. Each
subsequent look advances by `stride`. Every window consumes an allocation, even
before enough post-reference positions exist or when unknowns break it. The
family is `max_looks * len(window_sizes)` comparisons; the monitor owns these
settings, so leave config `max_comparisons=1` and `comparison_index=0`.

Use strictly increasing original timestamps with `order="timestamp"`, or assert
`order="trusted_sequence"` when the supplied list has actual trusted event order
(required for positional data or tied timestamps). Never fabricate timestamp
jitter or ID order. Unordered same-time cohorts remain usable in **explicit
population comparisons**, which need no within-population order.

Unknown reference measurements are reported and excluded subject to minimum
support. An unknown **current** position breaks that window; it does not disappear
and join unrelated neighbors. A later fully measured window can recover.
`complete=false` must form a trailing suffix; it is not evaluated. References
never adapt to a detected change and no finding automatically resets the model.

Replay retains evaluations, `first_detection` (zero-based index, event ID,
timestamp, look and window), a fixed reference fingerprint, planned budget,
unknown/incomplete counts and unassessed positions after the horizon. Status
`horizon_exhausted` means this finite family is used up; `partial` means runtime
ended before requested evaluations completed. Preserve completed evidence and
inspect status before using it. Replaying the same prefix plus new observations
leaves earlier complete evaluations unchanged under the same prospective plan.

For online integration, persist monitor ID, original reference membership and
fingerprint, planned horizon/window sizes/alpha, seed, logical event IDs,
comparison progress, and finding deduplication. Re-submit a bounded snapshot to
replay, or call `compare_distributions` for explicit windows with the matching
family/index allocation. Never slide off the reference while retaining the same
monitor identity. New regimes and fresh budgets require an explicit application
policy accounting for repeated operation. Scheduling, persistence, notifications
and UsageTap case policy remain the application's responsibility.

## CLI, MCP, schemas and acceptance replay

```text
anomalyzer compare-distributions examples/distributions/numeric-shape.json
anomalyzer compare-distributions examples/distributions/categorical-mix.json
anomalyzer monitor-distributions examples/distributions/numeric-monitor.json
python examples/run_distribution_demo.py
```

Commands default to JSON and support `--format text`, stdin `-`, bounded
`--max-bytes`, and protected `--output`/`--overwrite`. Invalid input exits 2;
timed-out/partial execution exits 1. Other result statuses exit 0 and must still
be inspected. Python `analyze` dispatches requests carrying
`schema_version="distribution-v1"`; the older CLI `analyze` command keeps its
schema-1.0/1.1 time-series interface.

MCP exposes `compare_distributions` and `monitor_distributions`, each taking
`{"request":...}` and returning the full typed result directly. They do not
populate the older time-series finding cache or support its run-ID drilldown.
Generated schemas live in `schemas/distribution-{request,result}.schema.json`
and `schemas/distribution-monitor-{request,result}.schema.json`.

Before UsageTap adoption, replay representative measured traffic with this
version and predeclared configurations. Include stable zero-heavy mixtures,
stable-mean redistribution with no point outliers, distributed category changes,
rare categories, missing telemetry, changed batching, clustered tasks and
low-volume periods. Measure detection delay in calls **and elapsed time**, false
findings per monitor/day and compute cost. Synthetic acceptance fixtures and
passing tests establish implemented behavior, not real-world alert accuracy.
