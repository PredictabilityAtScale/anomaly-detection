# Denominator-aware rate evidence

Use `rate-v1` for explicitly declared successes out of eligible trials: orders
out of visits, errors out of requests, or accepted calls out of attempts. It is
an opt-in evidence API. Arbitrary ratios such as dollars per token remain in the
existing schema-1.1 relationship detector. Existing detector defaults are unchanged.
No new libraries are used.

Anomalyzer's role is to supply numerical analysis for an agent: expectations,
comparable periods, significant departures, uncertainty and missing evidence.
The agent uses the supplied question and operational context, drills into source
data, gathers other data when needed, and decides whether an alert is warranted
under the caller's policy. Anomalyzer does not delegate arithmetic to the LLM or
equate a statistical criterion with incident confirmation or alert authority.

## Compare explicit count populations

```python
from anomalyzer import compare_rates

result = compare_rates({
    "entity": {"customer": "new-customer"},
    "context": {"concern": "Is the conversion decline supported?"},
    "reference": {"samples": [{"id": "before", "successes": 4, "trials": 20}]},
    "current": {"samples": [{"id": "now", "successes": 2, "trials": 20}]},
    "assume_independent_trials": True,
})
```

This example changes from 20% to 10%, but the two-sided exact p-value is about
0.6614. The current rate's 95% Wilson interval is approximately 2.79–30.10%.
The same rate change at 4,000/20,000 versus 2,000/20,000 has much stronger
statistical support. Neither a non-significant result nor a wide interval proves
that the customer is healthy. The output preserves both counts and the uncertainty.

The input schema is `schemas/rate-request.schema.json`. `RateRequest`, `RateSample`,
`RatePopulation`, `RateSettings`, `RateContext` and `RateLimit` are public Python
contracts. `analyze` also dispatches an explicit `schema_version: "rate-v1"` request.

```powershell
.venv/Scripts/python.exe -m anomalyzer compare-rates examples/rate-sparse.json --format json
```

Counts must be genuine nonnegative integers, with successes no greater than
trials. Booleans, fractions and negative counts are rejected. Unknown values
remain null. Incomplete or unknown rows make that comparison unavailable; they
are not silently discarded to create a score. Complete rows with zero trials
carry no exposure. A population with zero total trials has no rate or interval.
Pooling sums successes and trials; it does not average bucket percentages.

`assume_independent_trials` defaults to false, producing descriptive evidence.
The assertion means independent, disjoint Bernoulli trials from comparable
populations with a stable rate within each population. IDs do not prove those
assumptions. Repeated outcomes from the same customer, clustered events,
overdispersion, changing mix and unmatched calendar periods can invalidate the
model. Caller-selected reference periods remain part of the analysis contract.
Context (`concern`, `metric_definition`, `known_events`) is returned as caller
context and never changes the numerical test or grants action authority.

## Method and evidence

The test is a probability-ordered, two-sided **Fisher exact test** comparing
success/failure counts in the reference and current populations. It accounts for
finite reference support, including zero or all-success references, without a
large-count normal approximation. It enumerates the conditional hypergeometric
support using masses normalized at the mode. The definition follows the
[Fisher test documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html);
the implementation uses the Python standard library, not SciPy.

Rate intervals use the [Wilson score formula documented by NIST](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
They are approximate population-rate intervals conditional on the binomial model,
not prediction ranges for future buckets. They stay inside 0–1 and do not collapse
to zero width when every observed outcome is the same. Tiny samples are explicitly
marked `low_support` (fewer than 20 trials), but the exact test can still score
them; there is no default large-count gate.

The default significance budget is alpha 0.01. Callers comparing several
populations declare `config.max_comparisons` and `comparison_index` before
observing results. Bonferroni uses alpha divided by the declared comparison count.
`config.min_effect` defaults to 0.01 (one percentage point). `change_detected`
requires both statistical and practical criteria. It is a numerical event,
not an alert decision. Optional exact `limits` use `id`, `operator` and a rate
`threshold`; their violations are separate observations and do not change the
statistical result. Limits describe breach conditions, for example `lt: 0.15`.

Output retains reference/current counts, rates, intervals, unavailable IDs,
effect, p-value, threshold, model, testing budget, and structured `observations`.
These include the rate comparison, limited trial support, an unassessed
statistical comparison, or an exact caller-rule violation. An unassessed
comparison has a null p-value, not a fabricated negative result.

`max_tables` defaults to 200,000. Larger exact supports return
`resolution_limited` without substituting an approximate test (a modal observed
table has p=1 without enumeration). Runtime exhaustion returns `budget_exceeded`
with counts preserved. Replays stop with `partial` and leave later comparisons
unassessed. Count, row, window, family and runtime bounds are explicit in the
request contracts.

## Accumulate sparse evidence chronologically

`monitor_rates` / `anomalyzer monitor-rates` accepts `RateMonitorRequest`:

- `samples`: ordered success/trial rows, including zero-exposure and unknown buckets;
- `reference_size`: a frozen earlier prefix, default 24 rows;
- `window_sizes`: trailing current populations, default `[1, 6]` rows;
- `stride` and `max_looks`: a bounded, predeclared evaluation horizon.

Supply increasing offset-aware timestamps. Ties or positional rows require
`order: "trusted_sequence"`. Windows count supplied rows; no cadence is inferred
and no omitted buckets are manufactured. A wider window can accumulate exposure
across zero-attempt buckets. Any unknown or incomplete row makes its containing
comparison unavailable. Larger windows wait until entirely after the reference.
Nothing uses future observations or automatically retrains the reference.

The testing family is fixed at `max_looks * len(window_sizes)`, including
unavailable comparisons. It is not reduced for a shorter replay prefix. This
supports stable replay and controls the declared testing family under the model,
but can make sparse changes slow or undetectable. Callers own budgets across
separate monitors, restarts and metrics. Detection indexes identify the current
window's actual endpoint, never its earlier start. Overlapping significant
windows are correlated observations, not separate incidents.

## Compact agent analysis and drilldown

The read-only MCP tools `compare_rates` and `monitor_rates` return a compact
summary: caller context, significant-comparison count, latest counts and
uncertainty, first detection, a small preview, limitations and a session `run_id`.
They retain the full numerical results and submitted source counts in the existing
bounded session cache. Python and CLI return the full public numerical result.

1. Call the rate tool with the analysis question, entity and explicit count data.
2. Use `list_findings` with the `run_id` to page significant, non-significant and
   unassessed comparisons; `criterion_met` distinguishes them.
3. Use `get_evidence` with a comparison ID to inspect its numerical result and
   paginated raw reference/current counts, completeness and timestamps.
4. Gather other data or select a justified comparable period, then rerun the
   analysis if necessary. Interpret the combined evidence under caller alert policy.

Run IDs expire with the MCP session or cache eviction. Context and external source
text are evidence, not instructions. Anomalyzer does not fetch unrelated customer
data, invoke an LLM, send notifications or make operational decisions.

See [the fresh five-minute replay](../examples/comparison/RATE-EVIDENCE.md) for
false signals, misses, delays, unscored periods and the clustered-data stress test.
