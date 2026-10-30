# Explicit seasonal population matching (0.5.0)

`compare_seasonal_distributions` selects comparable earlier local-clock windows
and passes them to the existing numeric or categorical distribution detector.
Use it when scheduled work has different normal behavior from the rest of the
day. The schedule is explicitly declared: no season discovery, automatic reset,
run-phase inference or block resampling is added.

## UsageTap handoff

UsageTap supplies one bounded, available snapshot of genuine call/report samples,
their stable IDs, original timestamps, measured values and coverage, plus the
application/customer/workload scope and unit. Anomalyzer owns the declared
calendar matching, support checks and numerical comparison. Collection
completeness, source eligibility and snapshot revision selection remain caller
responsibilities. A prior clock window ending does not prove its telemetry is
complete; inspect collection health before asserting exchangeability.

```python
import json
from anomalyzer import compare_seasonal_distributions

with open("examples/distributions/seasonal-morning.json") as stream:
    request = json.load(stream)

result = compare_seasonal_distributions(request)
print(result.status, result.change_detected)
print(result.selection["reference_sample_ids"])
print(result.selection["current_window"])
```

The request uses `schema_version="distribution-v1"` and
`task="compare_seasonal_distributions"` (both default in the dedicated API).
Required fields are `kind`, nonempty `entity`, `units`, `samples`, `window_start`,
`window_end`, `as_of`, and `reference_policy`. Numeric/categorical values,
unknowns, sample completeness, positive per-report quantities, and inference
assumptions have the same meanings as in the
[distribution API](distribution-detection.md).

`samples` accepts at most 10,000 distinct logical IDs, each with an offset-aware
timestamp. Sorting is deterministic by UTC time and ID. Tied timestamps are
allowed: this is a comparison of populations, not a sequence-pattern test; ID
sorting asserts no event order or independence. No event is manufactured,
aggregated, duplicated or silently subsampled.

## Declare the reference policy

```json
{
  "timezone": "America/Los_Angeles",
  "matching": "same_weekday",
  "lookback_days": 28,
  "min_windows": 3,
  "max_windows": 14,
  "min_samples_per_window": 8,
  "fallback": "none"
}
```

All fields except `timezone` have the shown defaults. `matching` is one of:

| Policy | Eligible earlier local dates |
| --- | --- |
| `daily` | Every prior date in the lookback |
| `same_weekday` | The same weekday as the current window |
| `weekday_weekend` | Weekdays for a weekday window; Saturdays/Sundays for a weekend window |

Windows are selected newest first, up to `max_windows`. A candidate needs at
least `min_samples_per_window` complete non-null observations. Inference needs
at least `min_windows` distinct dates (minimum configurable value 2), **and**
the detector's total minimum event support. One very large batch cannot supply
several days of evidence. Complete measured events remain the sampling unit;
this day-count gate does not make calls within a batch independent.

Lookback is 1–366 local calendar days. Minimum/maximum window counts are 2–90,
and minimum samples per window is 1–4,096. Neither population may exceed the
underlying detector's 4,096-position limit; narrow the window or lower
`max_windows` when necessary. An explicit error replaces silent truncation.
Pooling weights every genuine event equally (or uses its measured report
quantity for categorical composition), so busier days contribute more events.
This version does not balance days to equal influence.

`fallback="daily"` explicitly permits a broader reference when the primary
policy lacks enough supported windows or total reference measurements. It is
chosen using support only, before any statistical test. The engine never tries
several populations and chooses whichever produces a finding. The fallback is
visible in `fallback_used`, `resolved_matching` and the support-only `attempts`.
No fallback is the default; a daily policy cannot fall back to itself.

## Match progress and handle DST explicitly

Window intervals are half-open: start included, end excluded. The assessed end
is `min(as_of, window_end)`; `as_of` must be after the start. For a scheduled
08:00–09:00 window assessed at 08:05, current **and historical** populations
cover 08:00–08:05 in the declared timezone. Calls at 08:05 or later cannot enter
that assessment. With `as_of >= window_end`, the entire declared window is used.
History always comes from earlier local dates, never another part of today or
a later observation. Event times do not establish when records arrived: supply
only the snapshot actually available at the assessment cutoff.

The explicit window must start and end on one local date in increasing
wall-clock order. Cross-midnight windows and windows spanning UTC-offset
transitions are intentionally unsupported in this first version. Current
ambiguous local boundaries are rejected even if an input offset identifies one
fold, because matching prior folds would require another explicit policy.

Each historical date resolves the same wall-clock boundaries independently.
An 8am window therefore follows the local timezone across a DST change, rather
than shifting to 7am or 9am. Nonexistent spring-forward boundaries, ambiguous
fall-back boundaries and historical windows crossing an offset transition are
skipped with explicit reasons. There is no guessed fold, interpolation or
timestamp jitter. These skipped days do not count toward minimum support.

## Inspect evidence and preserve the testing family

The result exposes:

- `selection.policy`, resolved matching, fallback and every candidate window's
  date, UTC boundaries, source IDs, measured support and exclusion reason.
- Current planned and assessed bounds, local times and partial-window status.
- Selected reference/current sample IDs, excluded source IDs/reasons, distinct
  supported dates and the event-pooling interpretation.
- A `reference_id`, a `selection_id` covering the actual selected data/policy,
  and a full input fingerprint. Appending later/out-of-window data leaves the
  selected comparison unchanged; corrections can revise its fingerprints.
- A nested `comparison` from the existing detector, with statistical/practical
  gates and source support. Too few distinct prior windows returns
  `status="insufficient_history"`, `comparison=null`, and no finding.

The existing `DistributionSettings` config is forwarded unchanged. In
particular, `alpha`, `max_comparisons`, `comparison_index`, seed, minimum support
and effect threshold retain their meanings. The selection layer performs at
most one numerical test. A fallback supplies no new alpha budget. Reserve
allocations across all planned partial-window looks, phase windows, detectors
and repeated days; unsupported attempts are not an excuse to reset the family.
The caller persists this policy and allocation. This one-comparison API does
not create a durable seasonal monitor or an unlimited daily testing allowance.

Status and `change_detected` follow the underlying detector, with explicit
insufficient-history and runtime-budget failures. Unknown and incomplete calls
remain inspectable in window IDs and nested population exclusions. Set
`config.missing_current="break"` to make any such current sample unavailable
for inference; otherwise the existing explicit-population exclusion policy
applies. The one cooperative runtime budget covers both selection and testing.

Seasonal matching improves comparability; it does **not** establish operational
false-positive rates or remove serial/run/day dependence. Inference still
requires caller-asserted exchangeability. Keep rate and application-wide mix
checks alongside matched behavior so missing, late or enlarged batches remain
detectable. Validate policies on representative chronological traffic before
using findings for alerts. This feature creates no incidents or notifications.

## CLI, MCP and schemas

```text
anomalyzer compare-seasonal-distributions examples/distributions/seasonal-morning.json
python examples/run_distribution_demo.py
```

The CLI defaults to JSON, accepts stdin `-`, `--format text`, bounded
`--max-bytes` and protected output files. Invalid input exits 2 and a runtime
failure exits 1. Inspect result status even after exit 0.

MCP adds `compare_seasonal_distributions` with `{"request":...}`, returning the
full result outside the older time-series finding cache. Python `analyze` also
dispatches the canonical seasonal task. Typed models are exported at package
root and from `anomalyzer.seasonal_distributions`; generated schemas are
`schemas/seasonal-distribution-request.schema.json` and
`schemas/seasonal-distribution-result.schema.json`. Existing 0.4.0 comparison and
monitoring contracts and schema-1.0/1.1 time-series behavior remain available.
