# Replay PostHog's negative-binomial band

`benchmark_posthog.py` uses PostHog's band implementation at revision
[`52bb991`](https://github.com/PostHog/posthog/tree/52bb99139083f5734383b2059440ff047163744d).
The upstream Logs scan requires five-minute counts. The pack has no five-minute
series, so the runner benchmarks the band component with a causal adapter for
the pack's hourly and daily counts.

Use a Python environment with Anomalyzer, NumPy and SciPy. From a PostHog
checkout, export these five source files at the pinned revision to a source
directory, retaining their relative paths. This lets the band run without the
PostHog application and database.

- `posthog/dataclasses.py`
- `products/apm/backend/logic/grid.py`
- `products/apm/backend/logic/anomaly_detection/bands.py`
- `products/apm/backend/logic/anomaly_detection/constants.py`
- `products/apm/backend/logic/anomaly_detection/types.py`

From this repository, run:

```text
python examples/comparison/benchmark_posthog.py --posthog-source PATH --output analysis/posthog-benchmark/results
```

The adapter uses 4–28 prior observations at the same declared phase, or a rolling
window for lag 1. It honors reviewed resets and keeps coverage gaps at their
original positions. Its per-tail cutoff allocates the scan's nominal 0.05 daily
budget over the supplied cadence. The adapter uses the band crossing directly,
without the scan's traffic gates, history guard, silence rule, or issue policy.
The sample minimum and the size of the pooled reference are adapter choices.

The primary cohort uses integer counts as supplied. In the sensitivity cohort,
both detectors receive the same rounded synthetic counts. Anomalyzer uses the
pack's declared recipe, with alerts at calibrated point triggers or first
pattern detections. The output also reports Anomalyzer point triggers alone.
An incident is detected on the first alert inside its labeled interval. It is
unassessed if the detector cannot score any bucket in that interval. False
alert runs group adjacent flags on normal buckets within one target. Gaps and
unscored buckets break a run.

`summary.csv` includes each detector's own coverage and a comparison restricted
to buckets with scores from both. `incidents.csv` shows individual delays and
misses, `cases.csv` lists eligibility and abstention reasons, and `predictions.csv`
contains the bucket-level results. Treat these paired synthetic examples as
behavior checks. Rounded results are sensitive to the fixture transformation.
