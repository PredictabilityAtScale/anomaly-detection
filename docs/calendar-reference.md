# Local calendar references for numeric series

Schema 1.1 callers can set `calendar_reference` on a timestamped dataset. Each
source supplies its own IANA timezone and one fixed elapsed cadence. Set
`config.trend` to `"none"` explicitly and omit `config.season_length`. The
recipe is `seasonal-residual-v1`. Existing point and residual-pattern thresholds,
the outlier policy, and the scale floor still apply.

```json
{
  "schema_version": "1.1",
  "datasets": [{
    "id": "traffic",
    "entity": {"service": "store"},
    "frequency": "5min",
    "timezone": "America/Los_Angeles",
    "timestamps": ["2026-01-05T08:00:00-08:00", "2026-01-05T08:05:00-08:00"],
    "values": [18, 21],
    "calendar_reference": {
      "profile": "local-calendar-v1",
      "lookback_days": 84,
      "guard_minutes": 1440,
      "fallback": "broader_calendar"
    }
  }],
  "config": {"trend": "none"}
}
```

The example returns insufficient history. With sufficient history, the selector
uses four earlier local dates, each with at least 80% complete native slots in
the clock window. Weeks start Monday. Windows are circular within each
candidate date, so a window around midnight can use both ends of the same
date. A peer bucket must end at or before the guard cutoff, even when the
bucket itself starts hours earlier.

| Segment age | Preferred reference | Distinct peer weeks |
| --- | --- | --- |
| Under 3 days | Unavailable | |
| 3 to under 14 days | Same weekday/weekend type, ±60 minutes | 2 |
| 14 to under 42 days | Same weekday, ±60 minutes | 4 |
| 42 days or more | Same weekday, ±10 minutes | 4 |

`broader_calendar` walks down the age-eligible ladder when date support fails.
`none` tries only the preferred tier. Each selected date contributes its own
mean. Robust mode trims the two outer date representatives and modestly favors
recent dates. Include mode uses the newest supported date mean. A sustained
departure can still enter the reference once it clears the guard.

Calibration starts after the training prefix and collects earlier residuals
for a single segment, tier, and target day group. It needs at least
`calibration_size` retained residuals across three local target dates.
Same-weekday keys need three distinct weeks. Weekday/weekend keys need two.
The frozen center and sample scale take effect on the next bucket. Provisional
residuals cannot trigger. A supported new tier can require fresh calibration
even when a broader tier has a frozen scale.

Offset-aware timestamps preserve both instants in a repeated autumn hour.
The selector skips repeated ambiguous targets, buckets crossing an offset
transition, and candidate clock windows containing ambiguous or nonexistent
wall times or spanning an offset change. Ordinary times continue to match the
same wall clock across offset changes. Unknown and incomplete observations
stay unscored. The existing explicit additive-volume empty policy can authorize
zero. A reset such as `"2026-02-06T08:15:00-08:00"` needs an exact grid time.
`reference_gaps: "restart"` starts new reference history at the first usable
bucket after a gap. `same_phase` keeps earlier eligible dates in scope.

Each historical score uses the versions visible at the target bucket's UTC
start. Measured values with later availability can enter future reference pools.
A late revision leaves the original historical target decision intact. The
dataset's `data_quality.samples` describes the requested snapshot.
`scoring_sample_overrides` records rows whose historical view differed.
The first submitted timestamp establishes the grid origin by default. Use
`data_policy.grid_start` to include earlier revision-only positions.

In JSON output, follow the bucket index from point evidence to the method's
`diagnostics.targets`. A scored target links to its deduplicated selection and
calibration records. Peer indexes resolve to the UTC and local timestamps in
the same target table. The MCP finding evidence view expands those UTC times.
Readiness describes reference support and calibration residuals. A numerical
criterion can support investigation. Incident confirmation and business impact
require source context.

Calendar readiness counts assessed and unassessed calibration keys in
`assessed_calibration_keys` and `unassessed_calibration_keys`. Each segment can
have multiple tier and day-group keys. An earlier tier can remain unassessed
after a later tier becomes usable.

## Keep a calibrated broader comparison during transitions

Set `calendar_reference.calibrated_fallback` to `true` with
`fallback="broader_calendar"` to learn supported age-eligible tiers in parallel.
Each tier and day group retains its own residual errors, support checks, frozen
center and scale. The scorer uses the narrowest currently supported tier that
was calibrated before the current bucket. A broader calibrated tier can remain
in use while the preferred tier collects its calibration. If none is calibrated,
the preferred supported tier reports non-triggering provisional evidence.

`calibration_candidates` lists the available keys and their prior calibration
state. `fallback_reason` distinguishes insufficient preferred peer support from
an uncalibrated preferred key. `calibration_key` identifies the exact scale used.
Switching keys breaks consecutive residual patterns. Reset and restart segments
cannot use calibration learned in an earlier segment. This option defaults to
false, preserving the original selector behavior.

## Inspect and validate expected ranges

Set `calendar_reference.expected_range_coverage` to a fraction such as `0.95`
to request an empirical expected range for calendar targets. The range uses a
separate collection of absolute prediction errors, including errors screened out
of the detector calibration. It starts collecting after training, independently
for each tier, target day group and segment. It freezes when sample and date/week
support pass and rank `ceil((n+1)*coverage)` lies within the available n errors.
The radius is that ordered absolute error. The bounds are expectation plus or
minus the radius, with no unit assumptions or zero clipping. They take effect
on the next bucket. Short history returns `status="insufficient_history"`.

Inspect `diagnostics.targets[i].expected_range` for status, bounds, key, sample
count and cutoff. The key's range calibration is stored alongside its detector
calibration. Ranges are optional evidence and do not change point flags, patterns,
cases or eligibility. Serial dependence, changing expectations and regimes can
change actual future coverage. The declared coverage is a target to validate on
later observations, rather than an incident probability. Assess normal coverage,
range width and unscored periods together. Use the expected ranges only for these
opt-in calendar datasets in this first implementation.

Run `examples/comparison/benchmark_calendar_improvements.py --output PATH` with
the project Python environment for an hourly paired replay of the old selector
and calibrated fallback, including flat, weekly and reset histories. Its output
reports detection, alert burden, and later coverage of the 95% expected ranges.
See [the paired replay results](../examples/comparison/CALENDAR-IMPROVEMENTS.md)
for the coverage gain, false-alert tradeoff and each incident's delay.
