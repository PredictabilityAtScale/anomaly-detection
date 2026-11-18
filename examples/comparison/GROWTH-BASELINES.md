# Frozen and adaptive baselines on paired growth series

Run with the existing Anomalyzer environment and Python standard library:

```powershell
.venv/Scripts/python.exe examples/comparison/benchmark_growth_baselines.py --pack C:/path/comparison-cases.zip --output analysis/growth-baseline-benchmark
```

Without `--pack`, the runner uses the repository's copy of the comparison
archive. It uses nine daily cases with known counterfactual values and labels,
covering linear and compound growth, ordinary acceleration, point departures,
and shifts. It keeps a single acceleration copy and one copy of the identical
robust/include spike inputs. The remaining pack cases exercise other behaviors.
Each case retains the supplied cadence, season length, training and calibration
sizes, and outlier handling. Adaptive uses its rolling trend. Frozen uses the
pack's trend setting. No recipe settings are fitted against the evaluation labels.

The fresh suite uses three seeded histories for each of four growth profiles.
Every history has weekly seasonality and four independent incident variants
derived from the same clean measurements. The changes are an abrupt permanent
rise, a smaller permanent drop, a seven-day rise, and a persistent reduction
in growth rate. Both recipes use the same weekly lag, 42 training days, 21
calibration days and identical values. Relative delays are in daily buckets.

False alert buckets combine calibrated point triggers and first pattern
detections. Consecutive flagged days count as one false alert run. Count them
on the clean controls and separately outside labeled windows in incident runs.
Count detection only when a point or location pattern agrees with the direction
and occurs within the labeled shift. The paired metric additionally requires a
day without a same-direction signal on the unchanged control. This is a stricter
test of whether a labeled incident adds a signal. The two metrics are both
available in `incidents.csv`. `buckets.csv` preserves the directional evidence
for independent checks.

On the fresh histories, adaptive reduced false alert days on clean controls
from 296 to 178, while separate runs increased from 61 to 65. The paired test
found 34 of 48 incidents with frozen and 33 of 48 with adaptive. Both caught
all twelve large permanent rises. On the original pack controls, frozen had
62 false days in six runs and adaptive had 78 in 30 runs. The nine selected
pack cases and 12 fresh histories are synthetic. Paired variants share their
noise, and the results do not estimate production accuracy.
