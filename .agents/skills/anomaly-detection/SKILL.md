---
name: anomaly-detection
description: Analyze one numeric time series for anomalies, outliers, spikes, drops, sustained shifts, residual patterns, or regime changes with this repository's Anomalyzer CLI, then explain or chart the evidence. Use when the user asks to detect, find, investigate, visualize, or explain unusual changes in timestamped or ordered metric data. Do not use for generic charting, multivariate analysis, forecasting-only requests, or distribution comparison.
---

# Anomaly detection

Use the repository's Anomalyzer implementation as the numerical engine. Do not
reimplement its detector in prose, SQL, JavaScript, or ad hoc Python.

## Run the analysis

Work from the repository root. Resolve the executable in this order:

1. `anomalyzer` when it is already on `PATH`.
2. `.venv/Scripts/anomalyzer.exe` on Windows or `.venv/bin/anomalyzer` on Unix.
3. `python -m anomalyzer` when the package is installed in the active Python.

Do not install packages or alter the environment unless the user asks. If no
working executable exists, explain the missing prerequisite and stop.

Inspect the input before constructing the command:

- Analyze exactly one entity, numeric measure, and unit at a time.
- For CSV, identify the value column. Supply time column and fixed frequency
  together, or omit both for ordered positional data.
- Preserve missing values as missing. Do not impute, resample, interpolate,
  convert units, or silently aggregate changing entity columns.
- Use an explicit `season_length` when the user or domain supplies one. For
  positional data, omission requests conservative lag inference. Do not tune
  lag, thresholds, trend, or reset points merely to create or remove flags.
- Treat reset points as reviewed external regime boundaries. Never infer them
  from the detector's own anomalies.

Run `anomalyzer analyze --help` when syntax or current defaults are uncertain.
Request full structured output with `--format json`. Typical commands are:

```text
anomalyzer analyze data.csv --time timestamp --value calls --frequency 1d --season-length 7 --format json
anomalyzer analyze values.csv --value calls --format json
anomalyzer analyze request.json --format json
```

Prefer reading JSON from stdout. If a durable result is useful, write it to a
task-owned path with `--output`; do not replace an existing file without the
user's intent.

## Interpret the evidence

Lead with the run status and the most decision-relevant evidence.

- `completed` with no observations or patterns means the configured detector
  found none; it does not prove the series is normal.
- `insufficient_history`, `inapplicable`, `partial`, or `failed` cannot establish
  normality. Explain the specific applicability, data-quality, or runtime issue.
- Only `calibrated` evidence can trigger. Distinguish it from `reference_only`
  and `provisional` evidence.
- Describe `observations` as point-anomaly episodes. Describe
  `anomaly_patterns` by their reported rule, interval, direction, and detection
  index; do not collapse every rule into a generic incident.
- A standardized residual is a scale-relative departure, not a probability.
  Pattern rules are evidence about residual behavior, not proof of causality or
  a full-distribution change.
- Business impact is unresolved until the user supplies operational context.
- Surface detector limitations that affect the result, including baseline echo,
  adaptation after one season, short history, tiny calibration variance, a
  lag-inference fallback, missed multiple seasonalities, or short reset segments.

Report the resolved lag, trend choice, training/calibration windows, point
threshold, reset boundaries, and material data-quality transformations when
they help the user judge the result. Preserve the detector's own wording when
precision matters; do not invent confidence levels.

## Visualize when useful

When the user requests a graph, or a visual materially improves interpretation,
read and follow [references/visualization.md](references/visualization.md).

Use the host's strongest available visualization capability after analysis:

- In Codex, use the built-in visualization skill/capability when it is available
  and applicable, passing it the source series, structured result, and the chart
  requirements in the reference.
- In Claude Code or another Agent Skills host, use its available artifact,
  charting, HTML/SVG, or plotting capability to implement the same semantics.
- If no specialized visualization capability is available, produce an
  accessible standalone HTML/SVG or a static scientific plot with the tools
  already installed. Do not install a charting dependency without permission.

Analysis must still succeed when visualization is unavailable. Never substitute
visual inspection for the structured detector result.

## Repository references

- Use `README.md` for detector semantics, input rules, and limitations.
- Use `schemas/request.schema.json` and `schemas/result.schema.json` only when
  exact input or output fields are needed.
- Use `examples/README.md` and the checked-in figures under `docs/images/` as
  examples of presentation and synthetic behavior, not as evidence of
  real-world accuracy.
