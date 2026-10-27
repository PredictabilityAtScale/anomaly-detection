# Sparse observations in Anomalyzer 0.2

An empty hour does not tell us whether nothing happened or collection failed.
Schema 1.1 therefore preserves missing values by default. An expectation can be
shown separately; it is never inserted as an observed measurement. Schema 1.0
keeps its existing complete-series behavior and unchanged schemas.
Schema 1.1 gains optional source and result fields. Upgrade strict schema-1.1
producers/readers together to 0.2; an older strict result model is not promised to
accept the new metadata. Complete legacy requests remain accepted. Record the
package version and method `profile_revision` with Guard's own profile revision.

The numbered [README progression](../README.md#14-choose-what-an-empty-period-means)
continues with chapters 14–22. Fixtures live in [examples/sparse](../examples/sparse/).
Run `python examples/generate.py`, `python examples/run_demo.py` and
`python examples/render_readme_progression.py --only-sparse` to reproduce them.
The examples demonstrate mechanics, not measured abuse accuracy.

## Source policies

All new source fields belong to a schema-1.1 dataset. The same canonical request
works through `analyze`, `analyze_relationships`, CLI JSON and read-only MCP.
`analyze_series` also accepts a `DatasetV11` or a dictionary containing policy,
coverage, rules or revisions and returns a schema-1.1 result.

```python
from anomalyzer import analyze, DataPolicy, DatasetV11

source = DatasetV11(
    id="calls", entity={"customer": "synthetic"}, units="calls",
    timestamps=["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z",
                "2026-01-01T03:00:00Z"],
    frequency="1h", values=[2, None, 4],
    data_policy=DataPolicy(),  # preserve missing; hour 2 is also unknown
)
result = analyze({"schema_version": "1.1", "datasets": [source.model_dump(mode="json")]})
print(result.dataset_results[0].data_quality["samples"])
```

| Input state | Meaning and behavior |
| --- | --- |
| Numeric value, including zero, `coverage="complete"` | A measurement eligible for rules and model support. Explicit zero remains zero. |
| Null or an omitted internal grid position | Unknown by default; not a zero, observation, calibration residual or recovery. |
| `coverage="empty"` | Caller confirms a finalized period with no reported volume. Preserve as missing unless an additive zero policy explicitly authorizes conversion. |
| `coverage="unknown"` | Collection/exposure is unknown; never filled even under a global empty-volume contract. |
| `coverage="incomplete"` | Original partial value remains visible but is excluded from completed measurements, references, calibration and totals. |
| `coverage="excluded"` | A measured value excluded from model fitting/calibration. Its explicit range rule can still be assessed; change comparisons break at it. |
| `coverage="revised"` | Supplied corrected measurement; preserve its revision and availability provenance. |

`coverage`, `available_at` and legacy `period_statuses` align with the original
input arrays before chronological sorting. Contradictory incomplete annotations
are rejected. Unknown values do not become observed zero merely because their
unit is named `calls` or their numeric neighbor is zero.

### Explicitly justified empty volume

```python
source = source.model_copy(update={
    "coverage": ["complete", "empty", "complete"],
    "data_policy": DataPolicy(measurement="additive_volume", missing="zero_for_empty"),
})
# Hour 1 is a confirmed empty zero. Omitted hour 2 remains unknown.
```

Use `absence_means_zero=True` only when a trusted collection/exposure contract
confirms that **every otherwise unannotated period inside the supplied grid** is
complete and absence means no volume. Explicit unknown/incomplete annotations
override that contract. This option requires both `measurement="additive_volume"`
and `missing="zero_for_empty"`. It does not infer heartbeats or successful collection.
For per-call cost, output/input or cache share, a no-call period is undefined;
the zero-volume policy is inappropriate.

Preparation reports original values, model values, coverage, source indexes,
conversion reasons, counts, revision IDs and availability timestamps. Converted
zeros are visibly identified as policy transformations. No expectation,
interpolation or carried-forward value trains the model as a measurement.
For policy-prepared sources, `grid_count` counts positions, `observation_count`
counts usable complete values (including authorized zero volume and measured
model exclusions), `reported_measurement_count` counts actually reported numeric
measurements, and `usable_model_count` excludes model-masked values. Training and
calibration expose their own eligible indexes/counts. Grid size is not training support.

## Calendar coordinates and bounded grids

The declared frequency is a fixed elapsed cadence. Internal omitted positions
are expanded on that grid and handled exactly like nulls. `grid_start` and
`grid_end` optionally declare its bounds, including leading/trailing empty periods;
otherwise bounds come from the supplied as-of-available timestamp range.
Nothing outside those bounds is invented. Off-grid values, off-grid bounds and
contradictory inputs fail visibly. No cadence is guessed.

The four-dataset/four-relationship limits remain. Raw samples plus revisions and
the expanded source grids share `max_points` (default 10,000). The grid size is
checked before allocation, and preparation/model loops use the runtime budget.
Partition large histories into compatible bounded requests without moving the
training origin. A failed or unsupported sibling does not erase other results.
Full evidence can be several megabytes for a bounded two-source history; the
point limit is not a guarantee of a small result. The standalone
`examples/library/benchmark_sparse.py` records warm runtime, serialization time
and result bytes for 1,344-hour and bounded event workloads. CI runs it in the
offline Lambda-compatible image and retains the report beside its exact image
and native dependency wheel hashes. Measure Guard's actual memory, concurrency,
cold start and persistence costs; store a suitable compact application evidence
contract rather than repeatedly transporting every raw result on each refresh.

Duplicate timestamps normally fail. Legacy schema-1.1 relationship preparation
retains its unique-source requirement. With an explicit `data_policy`, complete,
unrevisioned calendar duplicates can follow the declared `duplicate_policy`
(`sum` or `mean`); original values/indexes remain in `duplicate_sources`. Nulls
propagate. Duplicates involving incomplete coverage or revision metadata are
rejected. Event-index timestamps must be unique; ties are refused rather than
assigned invented times or counted as multiple independent events.

## What sparse statistical support means

Schema-1.1 gaps select an inspectable sparse profile. An explicit `data_policy`
also selects it for dense data. The default `seasonal-residual-v1` sparse profile
collects `training_size` **eligible observations**, retaining their actual grid
indexes. For each declared phase it freezes the training median (mean with
`outlier_handling="include"`). A phase needs `minimum_phase_samples`, default 2.
It then collects `calibration_size` eligible forecast residuals, not elapsed slots.
Unknown/incomplete/excluded positions never count toward either requirement.
Robust calibration screening is reported separately. Only subsequent calibrated
points can cross statistical thresholds; early/provisional evidence cannot trigger.

References match `(grid index - regime origin) % season_length`, so missing
Tuesday does not turn Wednesday into Tuesday. Training origins, indexes, phase
support, calibration indexes/cutoff and exclusions are inspectable. Unsupported
phases stay unavailable with a reason. Trend `auto` resolves visibly to no trend
in this frozen sparse profile. Evaluation samples never update that reference,
so gap handling cannot learn away a suspected sustained episode.

`reference_gaps="same_phase"` permits a point reference to borrow supported earlier
training phases across a gap. `reference_gaps="restart"` restarts training and
calibration after gaps. Explicit `reset_points` always start new regimes.
Nelson/CUSUM/moving-range runs and point episodes cannot bridge missing,
incomplete, excluded or reset boundaries, regardless of point-reference policy.
Location-pattern assessments and cases remain numerical evidence.

Adaptive recipes and explicit linear/exponential trend fitting currently use
**complete contiguous spans only**: they restart support at gaps, retaining their
original calendar indexes and timestamps. Post-gap learning requires an explicit
reset or caller-selected `reference_gaps="restart"`; the default does not silently
train a new reference on a suspected episode after unknown collection. Leading
unavailability before any observed history can precede the initial training span.
These methods do not borrow references through a gap.
The existing adaptive policy may admit a persistent third extreme observation;
this release does not implement an open-episode quarantine policy or simultaneous
multiple seasonal cycles. Do not label those roadmap features as delivered.

Readiness/reference quality, calibration eligibility, confidence and business
severity remain different concepts. Sparse readiness is conservatively `caution`
or `not_assessed`; neither is a probability or a universal switch disabling a
valid independently measured rule.

## Comparable event-index observations

```python
from anomalyzer import analyze_series

events = DatasetV11(
    id="cost_per_call", entity={"customer": "synthetic"}, units="dollars_per_call",
    timestamps=["2026-01-01T00:00:00Z", "2026-01-03T14:20:00Z"],
    values=[0.10, 0.12],  # one measurement per genuine comparable call
    data_policy=DataPolicy(observation_basis="event_index", change_max_gap_seconds=86400),
)
result = analyze_series(events, {"season_length": 1, "trend": "none"})
```

Omit `frequency`: event position is not elapsed time. Original event timestamps
remain on assessments and lineage. Calendar seasonality (`season_length>1`),
calendar rates, zero filling and calendar grid bounds are unavailable on this
basis. A caller-declared maximum time separation can limit change comparisons.
Without it, successive known comparable events are the explicit comparison basis.
Unknown event measurements break comparisons. Values not yet available at the
as-of cutoff do not create known event positions.
Event patterns refer to recorded comparable events, not uninterrupted calendar
coverage. Recorded events do not establish complete collection between them;
declare an explicit reset after an unknown collection boundary rather than
inventing a call to mark it.

Comparability of tenant, operation, model, execution context and sample unit is
the caller's responsibility. Tokens, records or consumed units are not implicitly
independent events. This mode does not infer abuse, invocation count or timing
resolution that the telemetry never recorded.

## Rules before learning; relationships with gaps

A measured `acceptable_range` rule can be violated on the first usable value,
even when statistical status is `insufficient_history` or `inapplicable`.
`maximum_absolute_change` and `maximum_relative_change` require a comparable prior
value. Unknown/incomplete/excluded positions and explicit resets break that prior.
Relative change from zero is unavailable. An optional `change_max_gap_seconds`
also limits separation. Unavailable rule reasons are included in assessment
baselines. A descriptive candidate alone remains non-triggering.

Relationships align valid original coordinates and may use different source
missing-data policies. A missing input is unavailable; a zero denominator remains
undefined; nonfinite derived arithmetic is unavailable rather than invented.
Lineage records source values, coverage, indexes, revision IDs and availability.
An excluded but genuinely measured value can still support exact arithmetic and
range assessment, while its derived model sample stays excluded.

## Sparse multi-resolution views

Schema 1.1 `multi-resolution-v1` exposes distinct `intraday` and `completed_period`
targets, assessments, cases and evidence IDs. The child recipe is explicitly
frozen seasonal analysis. Native evidence remains available when a daily view
lacks support. Daily sources require declared additive volume and `sum`; all
expected fixed-UTC-day children must be valid and complete. A missing or
open child makes its completed total unavailable. A reset inside a fully measured
day or an excluded model child excludes that day's model sample; the real sum
can still support a separately declared daily range rule. Observed
partial sums are progress metadata, never a completed total. Empty days are not
silently compressed out of the daily grid.

Daily ratios divide summed compatible numerator and denominator quantities;
percentages are not averaged. Daily differences use compatible additive sums.
Daily lagged, normalized-residual and joint-condition definitions remain
explicitly inapplicable until their per-view settings are supported. Hourly
lags/scales/thresholds are not silently reinterpreted as daily ones.

Source and relationship `rules` apply natively. Use `completed_period_rules` for
separately meaningful daily rules. View cases remain separate on policy replay;
they are correlated evidence from shared source samples, not independent votes.
Local-calendar/DST day aggregation and adaptive multi-resolution children remain
unsupported. Schema-1.0 multi-resolution retains its earlier complete-data contract.

## Availability, revisions and recomputation

`available_at` optionally records when each original value became known.
`revisions` contains explicit `{timestamp, value, available_at, revision_id, coverage}`
records. Revisions need distinct event-time/availability pairs. As-of analysis
selects only values/revisions available by the cutoff, and the latest eligible
revision wins. A revised snapshot with no earlier version cannot reconstruct the
missing historical value. Revision coverage is an input fact, not persistent
state maintained by the library.

Case availability cutoffs conservatively retain supplied known-input timing.
Unknown arrival times remain event-time snapshots and cannot establish
delivery-time detection latency. Later corrections can change a later recomputed
result; they must not rewrite an earlier as-of assessment. Keep the same grid
origin, training/calibration history, profile revision and reviewed reset boundaries
when recomputing a bounded history. Moving the request start can relearn a different
reference. Durable append/state storage and automatic correction reconciliation
remain caller responsibilities and separate roadmap work.

## Guard adoption

Install the exact [immutable release and hash-pinned dependencies](releases/README.md)
at application build time in Linux/Python 3.12 for the Lambda's actual architecture.
Bundle Pydantic's compatible native wheel and all other dependencies. Execution
requires no checkout, CLI, MCP process, hosted engine or package download.

Guard owns collection/exposure declarations, metric units, trusted attribution,
profile selection, fixed history origins, persistence, scheduling, business
materiality and Warning/Critical severity, deduplication/recovery and opt-in
notifications. API/Agentic Calls, LLM dollars and custom-meter units remain distinct.
No-data and failed checks cannot recover an incident. This library release does
not integrate or deploy Guard, invent risk thresholds, authorize blocking, or send
notifications. Hourly history cannot reconstruct minute activity.
