# Paired five-minute calendar reference benchmark

The primary arms use daily elapsed lag 288, weekly elapsed lag 2,016, and
`local-calendar-v1`. A zero-width calendar sensitivity keeps the ladder and
support rules while removing neighboring-clock pooling. All arms use the
floor-adjusted 0.4 configuration, the same chronological outlier policy and
residual rules, and their own earlier prediction errors. The fixed arms use the
existing one/four-reference reduction in the forward replay. Required lagged
values that are missing cause an abstention. Robust calibration replacements
take effect going forward in all paired arms. The original detector replay
remains available as a separate floor regression.

The three existing short suites supply regression evidence. Long cases pair
controls with incident-injected versions of the same source history. Each
case spans 24 weeks on a UTC grid, with four weeks of training and calibration
opportunity through the end of week 12. The final 12 weeks use only calibrations
that had already frozen. Development and held-out runs use different seeds and
calendar starts. UTC, spring-forward, fall-back and non-hour-offset cohorts use
rates driven by their local clocks where applicable. Truth is scheduled before
scoring. Ordinary transitions and incident echoes remain in the normal
denominator outside labeled incident windows.

Compare point flags and residual patterns at their actual detection buckets.
A false run breaks at a reset, normal or unscored bucket. Report native alert
starts separately, retaining only existing openings when applying a shared
coverage mask. Keep missed and unassessed incidents distinct. False-alert
summaries use controls and incident outcomes use injections. The case bootstrap
resamples paired control differences because adjacent buckets and paired
controls and injections are dependent.

The locked gates require a 25% shared-coverage weekend false-run reduction on
busy calendar controls, improvement in at least two cases, at most two percentage
points of mature normal or incident coverage loss, no worsened main incident
outcomes, at most ten minutes of added delay, and at least 90% mature
incident-free shared coverage. Material weekday and calendar-free degradation
means more than two extra false runs per 1,000 scored normal buckets in the
mean paired case difference. Compare weekly lag separately.

```powershell
uv run python examples/comparison/benchmark_calendar_reference.py --split regression --output analysis/calendar-reference/regression
uv run python examples/comparison/benchmark_calendar_reference.py --split development --output analysis/calendar-reference/development
uv run python examples/comparison/benchmark_calendar_reference.py --split held-out --output analysis/calendar-reference/held-out
```

Each paired run writes a protocol manifest before scoring, a coverage table by
case, scope and cohort, per-incident grades, and a summary. Short-suite values
and truth labels are shared through `five_minute_fixtures.py`. Earlier
original-floor and full PostHog scan experiments provide separate regression
and detector context.

## Held-out decision

Keep the calendar selector opt-in. Timestamps establish when measurements
occurred. A useful local-calendar reference also needs a meaningful source
timezone, repeatable local structure, and sufficient support after gaps and
resets. These synthetic results leave production incident performance open.

### Shared weekend coverage on busy calendar controls

| Cohort | Shared normal buckets | Daily runs | Weekly runs | Calendar runs |
| --- | ---: | ---: | ---: | ---: |
| Los Angeles spring-forward | 6,912 | 662 | 97 | 279 |
| Los Angeles fall-back | 6,888 | 586 | 93 | 234 |
| UTC smooth intraday cycle | 6,912 | 912 | 38 | 189 |
| Total | 20,712 | 2,160 | 228 | 702 |

The calendar arm reduced false runs by 67.5% versus daily lag. All three
busy calendar controls improved. The paired mean difference was −70.4 runs
per 1,000 scored normal buckets, with a case bootstrap interval of
−104.6 to −51.1. This interval represents three synthetic case pairs.
Weekly lag had fewer false runs than calendar in each of these cohorts.

### Native grades across all held-out cases

| Arm | Scored normal buckets | False point buckets | False alert buckets | False alert runs | Detected | Missed | Unassessed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Daily | 169,299 | 6,308 | 11,922 | 7,092 | 49 | 0 | 0 |
| Weekly | 169,300 | 3,417 | 7,816 | 4,666 | 47 | 2 | 0 |
| Calendar | 145,128 | 689 | 4,053 | 3,503 | 40 | 1 | 8 |
| Calendar with zero clock width | 145,128 | 666 | 3,825 | 3,316 | 39 | 2 | 8 |

With all three primary arms limited to the same 145,128 scored normal buckets,
daily recorded 5,816 false runs, weekly 3,227, and calendar 3,503. Overall
incident detection on that shared subset was 41/49, 39/49, and 40/49,
respectively. Against weekly lag, calendar added a mean 1.90 false runs per
1,000 scored normal buckets on pairwise shared coverage and detected one
additional shared main incident. The largest shared delay increase versus
weekly was 95 minutes. In native coverage, weekly assessed all 49 incidents.

Calendar failed the mature normal and incident coverage gates by losing
14.27 and 14.29 percentage points versus daily. Shared mature incident-free
coverage was 85.70%, below the 90% floor. The sparse case's reset left its
preferred mature keys uncalibrated at the locked cutoff, accounting for seven
unassessed main incidents. A moderate weekday rise was missed in the busy
spring case. The largest delay increase versus daily was 90 minutes. A
separate fall-back boundary incident abstained during the repeated hour. The
weekday and calendar-free false-run limits passed.

The zero-width sensitivity covered the same held-out buckets. It produced
187 fewer false runs and detected one fewer incident than the pooled version.
Development showed the same qualitative tradeoff against daily, with a 67.8%
weekend false-run reduction and an approximately 14-point coverage loss. The
short regression calendar arms had zero scored final buckets and left all 69
labeled incidents unassessed under the frozen protocol.

### Evidence inspection

At 10:00 Los Angeles time on November 1, 2025, the held-out fall-back control
and its injected counterpart both used four preceding Saturdays with five of
five eligible slots per date. The control had 33 observations against an
expectation of 31.16, with a standardized residual of 0.37. The injected count
of 85 used the same expectation and produced a point trigger at 11.94. The
fall-back boundary example preserved its UTC instant and local fold and
reported `ambiguous_target_time` with unavailable calendar maturity. The
input truth labels came from the fixture. The selector's output established
its numerical criterion and left incident confirmation and impact unresolved.
