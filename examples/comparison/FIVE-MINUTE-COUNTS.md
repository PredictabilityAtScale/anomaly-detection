# Five-minute integer count benchmark

The replay uses Anomalyzer and Python's standard library. Run it from the
repository root with the existing project environment.

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_five_minute_counts.py --output analysis/five-minute-count-benchmark
```

The 21 synthetic fixtures are native five-minute integer counts. They include
quiet and flat controls, isolated spikes and drops, sustained changes, outages,
and low- and higher-volume series with daily patterns and a weekend effect.
Paired incident and control fixtures share their underlying observations. The
runner uses eight training days, four calibration days and a three-day holdout
with the same daily lag and trend settings in both runs. Six unknown buckets
stay unknown. Evaluation labels are kept outside detector inputs.

The candidate uses `scale_floor=0.4`, exposed in the CLI as `--scale-floor 0.4`.
Use it for explicitly selected integer count series. With the default point
threshold of 3, a centered one-count residual on a flat reference scores 2.5
and a two-count residual scores 5. The measured residual remains in the result.
Repeated same-direction misses can still trigger residual patterns. The floor
also affects robust screening and model reference updates. Its effect can differ
when the expected value or the residual center is fractional.

Every run grades calibrated point flags and first pattern detections in the
holdout. An incident is detected by the first flag within its labeled interval.
This measures temporal overlap. Adjacent false flags count as one run, and
unscored buckets break a run. The benchmark reports the intentionally ambiguous
one-count singleton separately alongside all other labeled incidents. A genuine
one-count singleton can be indistinguishable from ordinary one-count noise in the
observations. Review counts and timing for both groups before changing policy.

`summary.json` contains aggregate results and individual changes in incident
detection or delay. `incidents.csv`, `cases.csv`, and `buckets.csv` contain the
details. `fixtures.csv` exports the original counts, timestamps and labels for
replay in other tools. This run evaluates Anomalyzer on both settings. Its
synthetic histories and paired controls do not estimate production alert rates.

In the 0.9.1 replay, `0.4` reduced false alert runs from 1,171 to 1,065 across
all fixtures and from 108 to 2 in the five quiet or flat fixtures. The same
29 main incidents were detected. Two sustained one-count incidents took one
extra bucket to detect, and the ambiguous one-count singleton was missed.
Both settings left the same six unknown buckets unscored. The initial `0.5`
trial gave the same false alert and incident counts but took three extra buckets
on each sustained one-count incident. Both floors were explored on these same
fixtures.

## Fresh holdout with clustered one-count noise

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_five_minute_counts.py --suite clustered-holdout --count-floor 0.4 --output analysis/five-minute-clustered-holdout
```

This suite uses five fresh seeded backgrounds, each replayed as an ordinary
control and with injected incidents. Three backgrounds generate same-direction
one-count departures lasting one to five buckets throughout the history. One
of those three has more frequent clusters in the holdout. The other two are
low- and higher-volume count series with a daily cycle, weekend changes and
three unknown buckets in their incident variants. Both settings use the same
training, calibration and holdout periods as the original suite. The floor
and point and pattern thresholds were held fixed for this follow-up.

`ordinary_clusters.csv` tracks false flags within each ordinary cluster.
The summary counts clustered-noise alerts on the three independent control
series only, because the paired incident variants reuse that noise. The
main false-alert totals include both variants and count flags just outside
a cluster as well. Incident windows are selected before scoring. Each
incident is graded by when the first flag occurs inside its window.

With 0.4, false alert buckets fell from 838 to 677 and false alert runs rose
from 404 to 488. The three clustered controls went from alerts on all 17
ordinary one-count singletons to zero, while alerts on multi-bucket clusters
changed from 52 of 52 to 51 of 52. Both settings detected all 15 main incidents.
Two sustained one-count shifts took five minutes longer with 0.4, and the three
isolated one-count incidents were missed. The summary and incident CSV preserve
these results alongside coverage and individual delays.

## Experimental persistence policy

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_five_minute_counts.py --suite all --count-floor 0.4 --persistence --output analysis/five-minute-persistence-benchmark
```

The runner compares the default, the 0.4 floor, and a benchmark-only policy
on all three suites. `persistence-holdout` uses fresh seeds and includes a
background with longer ordinary clusters in the holdout than in training.
It includes isolated one-count incidents and short one-count shifts as
separate boundary cases. Keep the fresh results separate from the two earlier
suites that motivated the policy.

The policy starts from Anomalyzer's 0.4 result. It applies when at least 90%
of the measured training and calibration buckets share one count and every
other measured bucket lies within one count of it. For such a series, alerts
on one-count departures are confirmed after the longest same-direction
one-count run seen in that prefix plus one bucket, with a minimum of two
buckets. A return to the learned level, a gap, or a reversal breaks the run.
The policy emits once at confirmation and passes through existing 0.4 alerts
on deviations of two counts or more. Other series keep their 0.4 alerts.

This experiment changes alert eligibility, leaving raw point and pattern
evidence available for inspection. It does not change the Anomalyzer API or
defaults. `cases.csv` records per-series confirmation lengths. `buckets.csv`
includes original pattern names and the separate confirmation flag. An
ordinary cluster that exceeds the historical maximum can still alert. A
real shift that ends before confirmation can be missed.

On the fresh suite, the default, 0.4 floor, and persistence policy produced
380, 427, and 249 false alert runs respectively. The policy alerted on 2 of
36 ordinary multi-bucket clusters. Both baselines alerted on all 36. The
three long one-count shifts were detected after 15, 25, and 35 minutes with
persistence, compared with five minutes each with the floor alone. The
policy missed two of three four-bucket shifts and all three isolated
one-count incidents. Outcomes and delays for the other 12 incidents were
unchanged across all three settings.
