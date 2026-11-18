# Five-minute sparse rate qualification

This replay qualifies an opt-in evidence API, not an automatic alert policy.
The agent receives counts, rate uncertainty, effects, numerical criteria and
limitations. It can drill into source data and gather more context before
deciding whether to alert. A benchmark flag is a numerical candidate signal.

No libraries were added. The exact test is checked independently against integer
table enumeration, published examples, boundary counts and unbalanced populations.
The original comparison pack remains unchanged and its reproduction checks pass.

## Reproduce

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_rates.py --output analysis/rates-first-validation
```

The output path must be new. Seeds 13007 and 72019 generate 288 integer
five-minute success/trial rows per case: 96 reference buckets (eight hours), then
192 evaluation buckets (16 hours). Independent-trial cohorts have per-bucket
exposure drawn from `[0,1,2,5]` (sparse), `[10,20,50]` (small) or `[1000,2000]`
(busy). Base conversion is 10%. Paired controls and injected versions use identical
trial counts and random draws. Injected probability rises to 35% for 48 buckets
from index 144, then to 55% for three buckets from index 240.

A separate clustered sparse stress cohort reuses one outcome for every trial
within a bucket. It violates independent-trial inference deliberately. Its grades
are separated from the independent-binomial controls; the test is not a correction
for clustering.

The existing ratio arm calls the public schema-1.1 ratio relationship using
successes/trials, `trend: none`, and otherwise default settings. It counts point
trigger buckets plus first residual-pattern detection buckets. The exact rate
arm uses a frozen 96-row reference, trailing windows `[1,6,24]`, alpha 0.01,
minimum effect 0.01, and 192 planned looks: 576 Bonferroni comparisons. Wider
windows wait until entirely disjoint from the reference. Both are evaluated over
the same final 192 native endpoints.

**This is a comparison of two complete paths.** Reference updating, window
pooling, criteria and repeated-testing policy differ; the gains cannot be
attributed to denominator awareness alone. Independent tests separately show that
an equal percentage change gets different support at different trial volumes.

## Independent-binomial results

Six background draws, each paired with an injected history, produce 12 histories
and 12 incidents. A rate endpoint is assessed when at least one window ending
there completed the test; it need not have a scoreable one-bucket rate. In
particular, a wider window can retain exposure when its final bucket has no trials.
Unknown/incomplete exposure is not used this way.

| Measure | Existing ratio path | Exact rate evidence |
| --- | ---: | ---: |
| Assessed endpoints | 2,134 | 2,302 |
| Unassessed endpoints | 170 | 2 |
| Normal assessed endpoints | 1,849 | 1,996 |
| Signals outside labeled incident intervals | 355 | 171 |
| Runs of those signals | 183 | 13 |
| Detected incidents | 12 | 9 |
| Scored misses | 0 | 3 |
| Entirely unassessed incidents | 0 | 0 |

On the same 1,849 normal endpoints assessed by both, there were 183 versus 14
signal runs (355 versus 170 signal buckets). Shared filtering can split a native
run, hence 14 shared runs versus 13 in the exact arm's native coverage.

### Incident-free controls only

| Cohort, both seeds | Ratio false buckets / runs | Exact rate false buckets / runs |
| --- | ---: | ---: |
| Sparse | 87 / 56 | 0 / 0 |
| Small | 64 / 45 | 0 / 0 |
| Busy | 9 / 8 | 0 / 0 |
| Total | 160 / 109 | 0 / 0 |

Zero signals on these six controls is encouraging, not a production false-alert
estimate or proof of calibration. The exact arm has a stricter testing budget.
All 171 off-incident exact-rate signals in injected histories occur during
recovery endpoints whose trailing windows can still contain incident buckets.
They remain counted against the strict endpoint labels; they are not hidden by
extending incident truth. A contextual agent should distinguish lingering window
evidence from a newly starting incident.

### Each incident's detection delay, minutes

| Cohort | Seed | Sustained: ratio / exact | Brief: ratio / exact |
| --- | ---: | --- | --- |
| Sparse | 13007 | 0 / 80 | 0 / missed |
| Sparse | 72019 | 5 / missed | 0 / missed |
| Small | 13007 | 0 / 5 | 0 / 0 |
| Small | 72019 | 0 / 15 | 0 / 0 |
| Busy | 13007 | 0 / 0 | 0 / 0 |
| Busy | 72019 | 0 / 0 | 0 / 0 |

The exact arm misses one sustained sparse rise and both brief sparse rises under
the declared budget. It detects all eight incidents in the small/busy cohorts and
one sustained sparse incident (nine detections total). Sparse signals can take
longer to establish. A finite,
noisy reference and strict repeated-testing policy both constrain sensitivity;
the method does not claim that tiny counts are sufficient to rule out a problem.

## Clustered sparse stress, separated from model-valid data

Across four control/injected histories, ratio produced 45 off-incident runs,
versus 22 with exact rate evidence. On incident-free controls alone the counts
were 26 versus 12 runs (33 versus 18 buckets). Both methods detected three of
four incidents and missed one. Sustained delays were 0/0 and 15/15 minutes
(ratio/exact); brief outcomes were missed/missed and 5/5 minutes.

The excess control signals demonstrate that sparse counts are not the only
issue: correlated trials violate the binomial model. Do not present an exact
p-value as reliable merely because its arithmetic is exact. Caller context and
trial definitions matter, and representative customer replay is still needed.

## Interpretation and inspectable outputs

Keep this API opt-in. It improves the evidence presented for sparse rates and
substantially reduces candidate signals in this replay, with a measured loss of
sparse sensitivity. Keep effect, uncertainty, support and unassessed periods
visible; do not reduce the agent interface to a binary alert flag.

`fixtures.csv` contains count inputs and independent labels, `cases.csv` native
and shared coverage grades, `incidents.csv` each incident's misses/delays and
coverage, `buckets.csv` endpoint signals/statuses, and `summary.json` totals.
The replay parameters and source are fixed in `benchmark_rates.py`; no parameters
were changed after inspecting this run to conceal misses or delays.

See [the rate API](../../docs/rates.md) for assumptions, compact agent summaries,
context retention, and paginated source-count drilldown.
See [the three sparse misses](RATE-MISSES.md) for actual MCP evidence, follow-up
comparisons, additional-data requests and the summary-preview gap found by drilldown.
