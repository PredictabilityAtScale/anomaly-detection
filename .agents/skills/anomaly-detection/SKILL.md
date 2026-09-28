---
name: anomaly-detection
description: Analyze one numeric time series for anomalies, outliers, spikes, drops, sustained shifts, residual patterns, or regime changes with this repository's Anomalyzer CLI, then explain the evidence and its reliability limits. Create a quick chart or publication-quality visualization only when explicitly requested. Use when the user asks to detect, find, investigate, visualize, or explain unusual changes in timestamped or ordered metric data. Do not use for generic charting, multivariate analysis, forecasting-only requests, or distribution comparison.
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

## Return text first

Default to a concise text result immediately after Anomalyzer completes. Write
for an analyst who need not know statistical terminology. Lead with what changed,
when, and how it compares with the usual level; then say how reliable that
comparison is and what to check next. Use "one unusual day" or "several days
running high/low" before method names. Keep scores, rule names, and thresholds
in a short supporting detail when they help someone inspect the result. Do not
hide a material limitation to make the summary simpler. Do not create a chart
or invoke a visualization capability merely because a visual could help. Unless
the user explicitly requests a graph, chart, visualization, or publication-ready
figure, report:

- what was found, its dates and observed-versus-expected values, or why the run
  could not make a finding;
- whether it was one unusual reading, a run of point flags, or a possible
  ongoing change, without counting overlapping rules as separate events;
- each method's `diagnostics.detection_readiness` status and material reasons,
  translated into ordinary language;
- the strongest calibrated evidence and important non-triggering evidence,
  with run status and counts in supporting detail;
- resolved lag, trend, initialization windows, and point threshold when they
  explain the result;
- a brief judgment of how much to rely on the findings, grounded in readiness,
  evidence maturity, and representative history; and
- the material limitations that affect interpretation.

Keep the first response compact. When a chart could help, offer a quick inline
chart or a publication-quality interactive figure as optional follow-ups, but
do not generate either one automatically.

## Interpret the evidence

State the run status and lead with the most decision-relevant evidence. In
user-facing prose, translate `supported` to "the baseline quality checks
passed," `caution` to "the comparison may be unreliable because ...," and
`not_assessed` to "there was not enough suitable history to judge the
baseline." Keep the exact status available in supporting detail.

- `completed` with no observations or patterns means the configured detector
  found none; it does not prove the series is normal.
- `insufficient_history`, `inapplicable`, `partial`, or `failed` cannot establish
  normality. Explain the specific applicability, data-quality, or runtime issue.
- Only `calibrated` evidence can trigger. Distinguish it from `reference_only`
  and `provisional` evidence. Calibration means the residual center and scale
  are frozen; it is not a confidence level or a validation of the baseline.
- Explain the three levels separately: a `point` trigger is one value crossing
  the configured threshold against the modeled expectation; `observations`
  groups adjacent point flags into episodes; `anomaly_patterns` reports point
  runs or rules over calibrated residuals. The same points can produce both an
  episode and patterns, so do not count them as independent incidents.
- Describe patterns by their reported rule, interval, direction, and first
  `detection_index`. Nelson Rules 2, 5, and 6 and CUSUM suggest a possible
  shift in residual location even without a point flag. Nelson Rules 3, 4,
  and 8 concern residual trend, oscillation, or mixture; moving range concerns
  short-term variation. Do not call every pattern a shift.
- A standardized residual is a scale-relative departure, not a probability.
  Pattern rules are evidence about residual behavior, not proof of causality or
  a full-distribution change.
- Read `methods[].diagnostics.detection_readiness` and its reasons for every
  reported method. It checks training and calibration reference quality, not
  alert accuracy. `caution` qualifies the point scores and patterns; explain
  the specific weak fit, unstable season, residual drift, or other reported
  reason. `supported` does not establish precision or operational usefulness;
  `not_assessed` does not establish a good reference. If the field is absent,
  say readiness is unavailable rather than assuming support.
- If asked for confidence, state a qualitative assessment grounded in evidence
  maturity, readiness reasons, baseline fit, and representative history. Do not
  invent a confidence percentage or equate a large score, multiple overlapping
  rules, or a `supported` rating with a known chance of a true incident.
- Business impact is unresolved until the user supplies operational context.
- Surface detector limitations that affect the result, including baseline echo,
  adaptation after one season, short history, tiny calibration variance, a
  lag-inference fallback, missed multiple seasonalities, or short reset segments.

Report the resolved lag, trend choice, training/calibration windows, point
threshold, reset boundaries, and material data-quality transformations when
they help the user judge the result. Preserve the detector's own wording when
precision matters; do not invent confidence levels.

## When findings feed recurring alerts or actions

Explain the ordinary behavior the reference learned (level, trend, recurring
cycle, and typical variation) and where it fits poorly before recommending an
alert. For each decision-relevant finding, start with the entity, unit, period,
observed and expected values, whether the change is isolated or repeated, how
reliable the comparison is, and a concrete question to investigate. Put the
calibrated score, exact rule, and first detection time in supporting detail.
Separate what the data establishes from possible causes and business impact.

Treat `action_eligible` and `notification_eligible` in schema 1.1 as the result
of a caller-supplied policy, not an endorsement that an action is safe or useful.
The MCP adapter is read-only: it neither schedules runs nor delivers alerts or
executes actions. Its policy does not gate eligibility on detection readiness.
When readiness is `caution` or `not_assessed`, make that visible before suggesting
an automatic response; consequential actions need an externally reviewed policy
that accounts for that uncertainty. A `supported` rating also needs historical
replay and reviewed outcomes before it can justify an alert threshold.

For repeated runs, distinguish a newly detected period or rule from an ongoing
or previously reported finding. Do not count overlapping point episodes and
patterns as separate alerts. State that deduplication, late-data handling,
review state, notification delivery, and action execution require the calling
application; do not infer them from a fresh result or a run ID.

## Visualization modes

Only visualize after Anomalyzer has produced structured JSON and the user has
explicitly requested a visual. Choose the smallest requested mode.

### Quick inline chart

Use this mode for an ordinary request to graph, chart, plot, or visualize the
result, or when the user says `quick`, `simple`, or `not a full chart`. An
explicit invocation of the host's visualization skill does not by itself make
the request publication-quality.

In Codex, use the built-in visualization capability so the chart renders in
the conversation. Keep it deliberately small: one responsive plot with the
observed line, the available expected line, subtle training/calibration
shading, reset boundaries, and triggered point markers. Include a concise title
and labeled axes. Omit controls, KPI cards, residual subplots, pattern lanes,
custom tooltips, and publication styling unless the user asks for them. Emit
the native visualization content reference in the same response. Do not return
a local `.svg` through Markdown; Codex clients may show it as a blank image.

When the host has no native inline visualization capability, run the
dependency-free fallback renderer with the same Python interpreter used for
the CLI:

```text
python .agents/skills/anomaly-detection/scripts/quick_chart.py result.json --output anomaly-chart.svg
```

The fallback produces one static SVG panel matching the repository examples:
observed and expected values, initialization shading, reset boundaries, and
triggered point markers. It intentionally omits custom HTML, JavaScript,
tooltips, controls, residual subplots, and pattern lanes. Write the result to a
task-owned path and do not overwrite an existing file unless the user requested
it. Present it using the host's supported artifact mechanism rather than
assuming Markdown will render local SVG files.

### Publication-quality interactive figure

Use this mode only when the user explicitly asks for an interactive,
publication-quality, presentation-ready, or detailed figure, requests hover
tooltips, residual plots, pattern lanes, or multiple evidence panels. Then read
and follow
[references/visualization.md](references/visualization.md).

In Codex, use the built-in visualization capability for this mode when
available. In Claude Code or another Agent Skills host, use its strongest
equivalent artifact or charting capability. Analysis must still succeed when
visualization is unavailable. Never substitute visual inspection for the
structured detector result.

## Repository references

- Use `README.md` for detector semantics, input rules, and limitations.
- Use `schemas/request.schema.json` and `schemas/result.schema.json` only when
  exact input or output fields are needed.
- Use `examples/README.md` and the checked-in figures under `docs/images/` as
  examples of presentation and synthetic behavior, not as evidence of
  real-world accuracy.
