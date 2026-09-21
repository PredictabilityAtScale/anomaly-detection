# Publication-quality anomaly chart specification

Read this reference only when the user explicitly requests an interactive,
publication-quality, presentation-ready, or detailed figure, asks for hover
tooltips, residual plots, pattern lanes, or multiple evidence panels. Do not
read or apply it for the default text response or a quick inline chart. Merely
invoking the host's visualization skill does not require this full
specification; honor `quick`, `simple`, or equivalent scope words.

Use this reference only after Anomalyzer has produced structured JSON. The
source series supplies the complete observed line; the result supplies expected
values, residuals, scores, maturities, triggers, windows, and detected patterns.

## Publication composition

For one series, prefer two aligned plots sharing the same horizontal coordinate:

1. **Observed and expected**
   - Draw observed values as the dominant solid line.
   - Draw detector expectations as a contrasting dashed or dotted line only
     where evidence contains an `expected` value.
   - Mark triggered point evidence with a high-contrast symbol. Pair color with
     shape or a direct label so flags remain identifiable without color.
   - Shade training and calibration regions subtly. Separate them when space
     permits; otherwise label the combined initialization region accurately.
   - Draw reviewed reset boundaries as vertical lines and restart window shading
     per segment.
2. **Standardized residual evidence**
   - Plot `standardized_residual` only where it is defined.
   - Draw the frozen residual centerline and positive/negative point thresholds.
   - Visually distinguish provisional from calibrated scores. Never render
     provisional points as triggered anomalies.

Add a compact third set of aligned pattern lanes only when `anomaly_patterns`
would otherwise clutter the plots. Use one lane per reported rule and draw each
reported interval from its first triggering sample through its last. Mark the
`detection_index` distinctly so the chart does not imply the pattern was known
before detection became possible.

For several comparable series or example cases, use small multiples. Share a
vertical scale only when the units and useful ranges are genuinely comparable.

## Data mapping

- Join evidence to the source series by zero-based `index`; do not align by
  formatted timestamps or rounded values.
- Use timestamps on the x-axis when provided and sample position otherwise.
- Label axes with the dataset unit. If units are absent, say `Value`, not an
  invented unit.
- Use `methods[].evidence[].observed`, `expected`, `residual`,
  `standardized_residual`, `signal_maturity`, and `triggers` for point details.
- Use `methods[].diagnostics.segments` for segment boundaries and per-segment
  training, calibration, and evaluation windows. Fall back to the top-level
  diagnostic windows only when segment diagnostics are absent.
- Use `observations` for point-episode annotations and `anomaly_patterns` for
  rule intervals. Preserve the detector's direction and rule names.
- If downsampling is necessary, always retain triggered samples, the adjacent
  seasonal references involved in their expectations, pattern interval ends,
  detection indices, reset boundaries, and extrema. State that ordinary points
  were downsampled.

## Interaction and annotation

When the host supports interaction, use a shared crosshair and tooltip showing:

- timestamp or sample position;
- observed and expected values with units;
- residual and standardized residual when defined;
- evidence maturity and trigger names;
- pattern rule and detection timing when applicable.

Keep the first render useful without interaction. Provide labeled axes, a concise
title, an accessible summary, keyboard-accessible controls, and touch-friendly
targets. Prefer direct labels over a legend for one or two series.

Annotate only the most consequential episodes and pattern detections. Avoid a
dashboard of redundant KPI cards. Put exact lists in the accompanying text or a
compact table when the chart would become crowded.

## Semantic guardrails

- Do not draw expectations before the detector has a seasonal reference.
- Do not extend the expectation line into the future unless the user explicitly
  asks for a projection. Label any extension as a projection, not an anomaly
  result or confidence interval.
- Do not label a flag as a known event, root cause, or incident without external
  evidence.
- A flag exactly one season after another departure may be a baseline echo, but
  label it as such only after verifying the seasonal reference used the earlier
  changed observation. Otherwise describe it as another flagged departure.
- Show `insufficient_history`, `inapplicable`, `partial`, or `failed` visibly;
  never present the absence of flags from those states as reassurance.
- Do not hide quiet evidence. The observed line and available expectations must
  remain visible around anomaly markers so users can judge context.

Match the clarity of the checked-in figures under `docs/images/`: restrained
colors, aligned time axes, visible initialization context,
observed-versus-expected comparison, precise anomaly symbols, and explicit
units. Improve on the examples for real analyses by adding the residual panel
and pattern lanes when they carry decision-relevant evidence.
