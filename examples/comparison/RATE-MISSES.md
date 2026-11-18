# Agent drilldown into the three sparse misses

The three labeled incidents were scored, with known complete exposure. None
passed the monitor's statistical criterion. This investigation used the actual
MCP `monitor_rates`, `list_findings` and `get_evidence` handlers, retaining raw
source-count pagination. No detector defaults, thresholds or libraries changed.

The main constraint is limited trial volume combined with a strict planned
testing family: alpha 0.01 across 192 looks and three window widths means each
comparison needs a p-value at or below **0.00001736**. A low unadjusted p-value
alone does not pass that policy. The p-value is not an incident probability.

## What the agent actually receives

The first MCP response is a compact numerical summary with the caller's
`concern`, `metric_definition`, `known_events`, entity, latest comparison,
significant-comparison count, preview and session `run_id`. It is not an
LLM-generated business interpretation. The agent can then inspect non-significant
comparisons, their counts, intervals, effects, p-values, thresholds and supporting
source rows through the existing paginated tools.

Each snapshot here stops at the final bucket of the relevant incident. No later
observations enter its initial summary or evidence. The original testing family
stays 576 even though the snapshot is shorter than the planned full replay.
Truth labels choose the cases and inspection intervals retrospectively; they
are never supplied to the numerical engine or passed off as live-agent knowledge.
Fixture times are UTC bucket labels; the benchmark does not simulate delivery latency.

| Miss | Whole labeled interval | Earlier reference | Strongest original monitor comparison within the incident |
| --- | --- | --- | --- |
| Brief, seed 13007, 15 minutes | 2/5 = 40.0% | 13/187 = 7.0% | 30-minute window: 5/12 = 41.7%; p=0.001830 |
| Sustained, seed 72019, four hours | 23/93 = 24.7% | 20/197 = 10.2% | Two-hour window: 16/52 = 30.8%; p=0.000561 |
| Brief, seed 72019, 15 minutes | 5/8 = 62.5% | 20/197 = 10.2% | 30-minute window: 5/11 = 45.5%; p=0.004740 |

All effects are above the configured one-percentage-point practical-effect
minimum. All three fail the statistical criterion after the declared correction.
The strongest windows are selected retrospectively from already-budgeted tests;
they are not new independent confirmation. The original widths are 5, 30 and
120 minutes, so the exact 15-minute incident interval was not an original test.

### Brief rise, seed 13007

There are only five trials in the labeled 15 minutes. Their 40% rate has a 95%
Wilson interval of **11.8–76.9%**. The stronger 30-minute comparison contains
three earlier buckets as well: 5/12, with interval **19.3–68.0%**. Three of those
five successes preceded the labeled incident. Do not describe all five as
incident-period outcomes. The final individual bucket has zero attempts, so its
single-bucket rate is unavailable; pooled windows retain their actual exposure.

An agent should inspect the five actual attempts, whether they are independent,
what a success means, whether this short interval has an externally justified
start, and the impact of those specific events. Counts alone warrant an
investigation candidate, not a claim of a confirmed adverse incident.

### Sustained rise, seed 72019

The whole four-hour observed rate rose by **14.6 percentage points**. Its 95%
interval is **17.1–34.4%**, versus **6.7–15.2%** for the reference. The strongest
original two-hour window has interval **19.9–44.3%**. It occurs at index 181,
185 minutes after the labeled onset, but still does not pass the monitor's
576-comparison threshold. Its adjusted p-value is about 0.323.

This is the strongest case to prioritize for investigation: an increase sustained
over 93 trials, with more than one plausible window showing a rise. Those
overlapping windows are the same data, not independent confirmations. The agent
needs comparable-period history and operational corroboration to judge urgency.

### Brief rise, seed 72019

The exact labeled interval has five successes out of eight trials, with a 95%
interval of **30.6–86.3%**. Comparing that exact 15-minute interval with the
reference gives p=0.000797, but its start/end were supplied by benchmark truth.
The actual monitor's strongest comparison is 5/11 over 30 minutes, interval
**21.3–72.0%**, and does not pass its corrected threshold.

This burst deserves inspection of the individual attempts and any externally
known event at that time. It can matter operationally despite a statistical
criterion remaining unmet, but the data does not establish how harmful it was.

## Follow-up analyses actually run

**Add a four-hour current window.** Replaying both sparse seeds, controls and
injected histories, with `[1,6,24,48]` buckets and the corresponding 768-test
family recovers **none of the three misses**. Control signals remain zero. The
already-detected other sustained event keeps its 80-minute delay, while its
off-incident signal endpoints increase from 9 to 29 as the larger trailing window
continues to include incident data. This is exploratory reuse of the same
fixtures, not a new held-out qualification or a recommended default.

**Use more genuinely earlier reference data.** Expand the reference from the
first eight hours to the first twelve hours, which still precede all injected
incidents. On the exact labeled intervals, the results are:

| Incident | Original reference / p | Expanded reference / p |
| --- | --- | --- |
| Brief 13007 | 13/187 / 0.04980 | 23/276 / 0.06442 |
| Sustained 72019 | 20/197 / 0.002242 | 27/286 / 0.000349 |
| Brief 72019 | 20/197 / 0.000797 | 27/286 / 0.000500 |

None passes the original corrected threshold. More history can strengthen or
weaken the observed comparison; it should be selected for comparability, not
for the smallest p-value. These reference and interval choices are exploratory
and share the same observations, so they are not fresh statistical confirmations.

**Inspect subsequently arriving data.** Disjoint observations in the next two
hours give 6/43 (14.0%), 5/58 (8.6%) and 5/42 (11.9%), respectively. None passes
the original criterion against its reference. The two seed-72019 intervals do
not show persistence at the incident's observed elevated rate. This does not
prove recovery or negate a transient impact. This later snapshot was unavailable
to the agent at the original incident endpoint and cannot improve its historical
detection delay. Thirty-minute follow-ups are exported as well.

**Do not reset the testing budget to one test after finding an interesting
window.** If an externally known deployment or incident defines a comparison
prospectively, that can justify a planned focused test. Choosing the same window
from these outcomes and discarding the earlier search does not.

## What extra data would help the agent decide

- **Metric meaning, expected direction and stakes.** These fixtures describe
  conversion increases. That can be good news. The same counts interpreted as
  payment failures could justify prompt review under an existing impact policy.
  Statistical departure, adverse impact and permission to notify are different facts.
- **Raw trial IDs, users and event outcomes.** Check duplicates, retries,
  clustered outcomes, success eligibility, collection completeness and actual
  delivery times. Distinct measured trials matter more than more copies of a count.
- **Earlier comparable exposure.** Request the same local periods on earlier
  normal days/weeks and a stable traffic mix. These fixtures span only one day,
  so they cannot validate weekday calendar matching. For new customers, a
  caller-declared comparable peer cohort may help, with its different population
  and assumptions visible rather than presented as that customer's own history.
- **Operational corroboration.** Deployment/configuration changes, error codes,
  latency, completed transactions and affected-customer reports can change the
  decision. Multiple detectors applied to the same counts are not independent
  corroborating data.

An appropriate agent response is: "This rate increase is worth investigating;
the planned statistical criterion is unmet. Here are the counts and uncertainty,
the impact we still need to establish, and the next specific data request."
A high-impact event can warrant a policy-based alert without being described as
statistically confirmed. The sustained miss is the clearest investigation priority;
the brief misses need event-level context and exposure before claiming confidence.

## Interface finding from the drilldown

The MCP has the contextual summary and detailed evidence, but the initial view
does not yet prioritize the strongest recent **unconfirmed** comparison. It shows
the last configured window as `latest`; its preview chooses the first significant
comparisons anywhere in the run, or the final comparisons when none qualify.

For the sustained miss, `latest` reports 13/55 (23.6%, p=0.01287), while the
stronger earlier two-hour comparison is 16/52 (p=0.000561). For brief 13007, the
preview shows indexes 160–162 from the earlier detected event, while the new
burst occurs at 240–242. The last two-hour window also dilutes each brief burst.
`list_findings` currently exposes status/time/window/criterion, requiring
`get_evidence` calls to inspect the underlying magnitude and p-value.

A useful next API change is an explicit focus interval plus a compact preview of
significant, unconfirmed and unavailable evidence within it, with count, effect,
uncertainty and stable drilldown IDs. Ranking an unconfirmed comparison must not
change its statistical criterion, testing budget or alert authority. This is a
recommendation from the investigation; the production summary was not changed.

## Reproduce and inspect

```powershell
.venv/Scripts/python.exe examples/comparison/inspect_rate_misses.py --output analysis/rate-miss-drilldown-final
```

Use a new output path. The script reads the earlier benchmark's fixture and
incident CSVs and asserts that all three misses reproduce. It uses the real MCP
handlers, paginates source counts and verifies that those counts reconcile to
the returned reference/current summaries. Output includes:

- `misses.csv`: counts, strongest original comparisons, uncertainty and initial previews;
- `comparison_scan.csv`: original comparisons inside the inspection intervals;
- `followups.csv` and `window_sensitivity.csv`: exploratory follow-ups and replays;
- per-case request, initial-summary and best-evidence JSON files, including source counts.

Saved `run_id` values describe that completed MCP session; rerunning creates new
session IDs. No business events or customer-impact evidence were invented.
