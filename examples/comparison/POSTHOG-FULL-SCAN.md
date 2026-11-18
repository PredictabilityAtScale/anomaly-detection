# PostHog Logs scan on the five-minute integer fixtures

This comparison runs the pinned PostHog `run_scan` and its original replay,
baseline, count-band, gate, and issue-state code. A fixture reader supplies
the counts that would normally come from ClickHouse and respects the scan's
requested time ranges. The scanner uses one service and `info` severity per
fixture, UTC, and its default detection settings. Available contiguous history
sets the retention boundary. This tests the local scan logic without measuring
database performance, production retention, or delivery to a notification service.

Measured zeros are passed as absent rows, which matches PostHog's native
count grid. Unknown collection gaps cannot use that representation. Such a
gap splits the scan and the next known span starts with its own history. This
is a benchmark input policy, so affected coverage is reported explicitly.
Anomalyzer keeps its default missing-data and calibration behavior.

Bucket metrics compare PostHog's verdicts with Anomalyzer point or first
pattern flags. Alert-start metrics compare native `OPEN` and `REOPEN`
transitions with the first bucket of an Anomalyzer flag run. Anomalyzer runs
are a proxy for alert openings. An already-active alert does not count as a
new detection in the alert-start view. The shared view filters existing flags
and openings to buckets scored by both detectors, without synthesizing new
openings. Delays are measured from label onset to the first signal in the
labeled window. An unassessed incident has no scorable buckets in that window.

Use the existing isolated benchmark environment and the pinned source files.
The runner verifies all ten source blobs used for the scan, including
`products/logs/backend/anomaly_scan.py`, the pure APM detector modules, the
grid constants, and PostHog's dataclass helper. No project dependencies are
added.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'analysis/posthog-benchmark/deps'
.venv/Scripts/python.exe examples/comparison/benchmark_posthog_full_scan.py --posthog-source analysis/posthog-benchmark/upstream --output analysis/posthog-full-scan-benchmark
```

`buckets.csv` gives the gate or coverage reason for every unscored bucket.
`incidents.csv` gives outcomes, coverage, and individual delays for both
views on each cohort. `posthog_issue_events.csv` preserves the native event
type, time, verdict, and confirmation count. The unchanged five-minute fixtures
contain synthetic controls and incidents. They help compare behavior and do not
estimate production detection or false-alert rates.
