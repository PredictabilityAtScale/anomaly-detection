# Try the anomaly detector

From the project root:

```powershell
.venv/Scripts/python examples/run_demo.py
```

The script runs twelve checked-in, reproducible examples and checks the exact
flagged samples. It exits 1 if any check fails and prints observed values,
expectations, residuals, scores, and pattern descriptions. No additional
packages needed.

The first eight and the two location-shift files contain 90 daily values; the two
stepped files contain 150. Most have weekly seasonality and an initial level around
100 calls. The location-shift examples use a 30-sample seasonal reference so the
moderate shift remains observable long enough to demonstrate all three rules.
Evidence starts after the first seven-day season. The first 28 days initialize
the baseline, the next 14 calibrate forecast errors, and the remaining 48 have
calibrated scores. Earlier evidence is explicitly reference-only or provisional
and cannot trigger. Spike, drop, and shift events occur after calibration;
the four trend patterns run throughout training, calibration, and evaluation.

| Case | Injected change | Expected flags |
| --- | --- | --- |
| ordinary | None | None |
| spike | +40 calls on March 7 | March 7; robust model history prevents the March 14 echo |
| drop | -40 calls on March 7 | March 7; robust model history prevents the March 14 echo |
| shift | +4 calls daily starting March 2 | March 2 onward; the extreme persistent shift remains abnormal until a reviewed reset |
| growth_up | Add 0.6 calls per elapsed day | None: fitted linear trend |
| growth_down | Subtract 0.6 calls per elapsed day | None: fitted linear trend |
| compound | Underlying level grows 1.2% daily; weekly variation remains additive | None: fitted compound trend using five seasonal training cycles |
| compound_down | Underlying level declines 1.2% daily; weekly variation remains additive | None: fitted compound trend using five seasonal training cycles |
| location_shift_up | Residuals move to +2.28 sigma at position 60 | No point flags; Nelson Rule 5, CUSUM, Rule 6, and Rule 2 detect possible upward location shifts at positions 61, 62, 63, and 68 |
| location_shift_down | Residuals move to -2.28 sigma at position 60 | No point flags; Nelson Rule 5, CUSUM, Rule 6, and Rule 2 detect possible downward location shifts at positions 61, 62, 63, and 68 |
| steps | Steps at positions 50 and 100, with changing trend | Most later samples; unreviewed regimes remain abnormal instead of becoming their own baseline |
| steps_reset | Same stepped data with manual resets at position 50 and date 2026-04-11 | None after independent segment training/calibration |

The compound level is `100 * 1.012 ** day`; its configuration uses 35 training
samples, or five complete seasonal cycles. These are synthetic usage rates,
so fractional calls are intentional. Compound decline uses `100 * 0.988 ** day`.
With a forced linear trend, the README comparison produces 34 flags.

The `steps` case demonstrates that robust model history does not automatically
normalize unreviewed regime changes. Its point evidence and qualifying residual
patterns do not retrain anything. `steps_reset`
uses the same values with reviewed boundaries in `reset_points`; seasonal history,
trend, and calibration restart independently in each segment.

The `location_shift_up` and `location_shift_down` cases demonstrate that location
evidence is distinct from an extreme point. Every shifted residual has magnitude
2.28 sigma, below the default point threshold of 3. Rule 5 detects the first
concentration beyond 2 sigma, CUSUM accumulates the moderate departures, Rule 6
detects the first concentration beyond 1 sigma, and Rule 2 later detects nine
values on one side of the centerline. The
descriptions deliberately say “possible location shift”; they do not claim a
full-distribution change or a confirmed incident.

Focused synthetic example tests in `tests/test_analysis.py` also exercise Nelson
Rule 3 with six increasing residuals, Rule 4 with fourteen alternating residuals,
Rule 8 with eight values outside ±1 sigma on both sides, CUSUM with repeated
moderate +0.8-sigma residuals, and moving range with a −2 to +2 transition. The
tests verify rule identifiers, semantic kinds, detection indices, directions,
threshold fields, and descriptions. They demonstrate mechanics rather than
calibrated real-world false-alarm rates.

The checked-in charts under `docs/images/` show the trend, seasonality,
change-point, location-shift, robust-outlier, and reviewed-regime cases. Regenerate them with
`.venv/Scripts/python examples/render_readme_progression.py` after regenerating
the examples. Historical expectations come directly from detector evidence;
the charts do not extend them into periods where no causal expectation exists.

The progression's early seasonality figures use `outlier_handling=include` to expose
the original limitation: one week after a spike or drop, the changed observation
becomes the baseline and an ordinary value can flag in the opposite direction. The
robust default still scores and displays the actual incident, but substitutes its
prior expectation only in future model references. A sustained extreme change then
remains abnormal until external review supplies a reset point. These flags are
forecast departures, not a count of real incidents.

Run a single case through the CLI:

```powershell
.venv/Scripts/anomalyzer analyze examples/drop.csv --time timestamp --value calls --frequency 1d --season-length 7
.venv/Scripts/anomalyzer analyze --config examples/spike.json --format json
.venv/Scripts/anomalyzer analyze --config examples/location_shift_up.json --format json
```

CSV and JSON contain the same values. Regenerate all twelve cases with
`.venv/Scripts/python examples/generate.py`. Synthetic cases test mechanics;
they do not establish accuracy on real usage data.
