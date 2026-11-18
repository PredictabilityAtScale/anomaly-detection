# Alert lifecycle benchmark

This experiment borrows PostHog's distinction between an abnormal bucket and
an open issue. It replays already-computed Anomalyzer signals. The first signal
opens immediately. A configurable number of consecutive scored quiet buckets
is needed to resolve. Unknown buckets break the recovery streak. A recurrence
within 12 buckets of the last signal can reuse the issue identity. Reopens and
fresh alerts on an active issue both count as interruptions.

The development grid compares 19 policies on the 41 existing five-minute
count fixtures. It varies the quiet recovery length, allowing a new calibrated
point after at least one scored quiet bucket to alert, and applying the longer
recovery only after pattern evidence. It discards policies that miss or delay
any new alert previously emitted inside a labeled incident. Among the remaining
policies it minimizes false alert starts, using shorter false open time to
break ties. The selected setting is written before processing the fresh suite.

The fresh holdout uses four new synthetic backgrounds, each with a matched
control and incident variant. It includes clustered one-count noise, separate
nearby spikes, outages, and sustained shifts. Scoring the fresh suite compares
the locked policy with the adjacent flag-run rule. A standard detector flag
inside a labeled incident is distinct from an alert emitted in that window.
An already-open issue can suppress a distinct alert even though evidence is
present. The replay reports misses and delays for alert starts, and counts
known normal buckets during which an issue is left open.

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_alert_lifecycle.py --output analysis/alert-lifecycle-hill-climb
```

The selected policy used four quiet buckets after a pattern and one after a
point. A point could alert again after verified quiet. On development it cut
false starts from 1,923 to 1,799, with no new misses or delays. On the fresh
holdout it reduced false starts from 226 to 216, missed one additional outage,
and left issues open during 1,110 normal buckets, up from 588. The policy stays
in offline evaluation. The detector and its default alert interpretation are
unchanged. The outputs include the development sweep, the locked setting,
the original holdout signals, and the outcome for each held-out incident.
