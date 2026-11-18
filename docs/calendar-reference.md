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
