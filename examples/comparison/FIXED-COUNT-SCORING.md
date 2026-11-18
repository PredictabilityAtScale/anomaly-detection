# Count scoring on a shared forecast

This replay uses the original five-minute suite and both clustered holdouts.
Each fixture is analyzed once with the existing Anomalyzer recipe. Both point
scorers see the same calibrated buckets and expected values. The benchmark
starts from Anomalyzer's default point rule, so it uses neither the optional
0.4 floor nor the persistence prototype.

The count arm calls PostHog's pinned band implementation with fixed moments
instead of letting it estimate its own baseline. The common point center is the
causal expectation plus Anomalyzer's frozen calibration center. The runner
estimates one negative-binomial overdispersion parameter from the same retained
calibration residuals used by Anomalyzer. It verifies their center and scale
against the detector before scoring. PostHog's one-count minimum rate and its
Poisson fallback are part of the count model. With the forecast locked, neither
arm's point flags feed back into subsequent expectations. This compares the
band calculation, which is only one component of PostHog's full scan.

Both arms use the nominal per-tail cutoff corresponding to a 3-sigma normal
score. Count quantiles are discrete and measured false-alert rates may differ.
The benchmark keeps the same residual-pattern first detections, combines them
with each arm's point flags, and applies the same incident grading and adjacent
false-run counting. It also reports points alone so the unchanged pattern alerts
cannot hide the effect of the point scorer. A detection is the first flag
inside the labeled incident. Missing measurements are unscored in both arms.

Use a source export at the pinned PostHog revision and an existing development
environment that can import its band code. For the local comparison, the
previously prepared PostHog files and isolated packages were reused.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'analysis/posthog-benchmark/deps'
.venv/Scripts/python.exe examples/comparison/benchmark_fixed_count_scoring.py --posthog-source analysis/posthog-benchmark/upstream --output analysis/fixed-count-scoring-benchmark
```

`summary.json` separates the three suites and includes both alert views.
`incidents.csv` preserves the first detection and delay for every incident.
`buckets.csv` exposes the shared reference, the count bounds, each point flag,
and the residual-pattern alerts common to both. The reused synthetic cases
support a controlled comparison and do not estimate production accuracy.

Across the 41 fixtures, the count band with the shared patterns reduced false
alert buckets from 3,882 to 3,503 while increasing the number of false runs from
1,955 to 2,393. It missed one of 69 incidents and delayed two others. The default
detected all 69. For points alone, the default missed 7 and the count band missed
48. Both approaches scored the same normal buckets. These numbers apply to the
fixed-reference comparison and its nominal tail cutoff.
