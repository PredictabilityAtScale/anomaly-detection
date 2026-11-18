"""Paired calendar-reference replay. Run each split into a separate directory."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from random import Random
from statistics import mean
from zoneinfo import ZoneInfo

from anomalyzer.baseline import reduce_references, reference_weight
from anomalyzer.budget import RuntimeBudget
from anomalyzer.calendar_baseline import TIERS
from anomalyzer.calendar_scoring import AvailableVersions, Calibration, analyze_calendar
from anomalyzer.contracts import Context, DatasetV11, MethodResult, Settings
from anomalyzer.evidence import anomaly_patterns
from anomalyzer.robust import EXTREME_Z
from anomalyzer.sparse import active_resets, normalize
from anomalyzer.validation import timestamp

from five_minute_fixtures import COUNT_FLOOR, ORIGIN, SUITES, START, TRAIN, CALIBRATION, Incident, inject, poisson, write_csv


DAY = 288
WEEK = 7 * DAY
STEP = timedelta(minutes=5)
PROFILE = {"profile": "local-calendar-v1"}
LAGS = {"daily": DAY, "weekly": WEEK}
SCOPES = {
    "native": ("daily", "weekly", "calendar", "calendar_zero_width"),
    "shared_three": ("daily", "weekly", "calendar"),
    "shared_daily_calendar": ("daily", "calendar"),
    "shared_weekly_calendar": ("weekly", "calendar"),
    "shared_calendar_sensitivity": ("calendar", "calendar_zero_width"),
}
LIMITS = {
    "weekend_run_reduction": 0.25,
    "busy_cases_with_reduction": 2,
    "coverage_pp_loss": 2.0,
    "max_extra_delay_minutes": 10,
    "weekday_and_calendar_free_extra_runs_per_1000": 2.0,
    "mature_incident_free_shared_floor": 0.90,
    "paired_resamples": 2000,
}
# These identifiers and dates are fixed before either replay. DST transitions
# land within the final evaluation interval for each LA seasonal cohort.
SPLITS = {
    "development": (20371, (2024, 11, 25), (2024, 7, 29), (2024, 2, 5)),
    "held-out": (74903, (2025, 11, 24), (2025, 7, 28), (2025, 2, 3)),
}


@dataclass
class Case:
    name: str
    pair: str
    volume: str
    cohort: str
    timestamps: list
    values: list
    origin: int
    training: int
    calibration: int
    incidents: tuple = ()
    variant: str = "control"
    zone: str = "UTC"
    resets: list = field(default_factory=list)
    annotations: dict = field(default_factory=dict)


def _long_case(split, case_index, volume, cohort, zone, start):
    seed = SPLITS[split][0]
    rng = Random(seed + 397 * case_index)
    origin = 12 * WEEK
    start = datetime(*start, tzinfo=timezone.utc)
    instants = [start + i * STEP for i in range(24 * WEEK)]
    local_times = [value.astimezone(ZoneInfo(zone)) for value in instants]
    timestamps = [value.isoformat() for value in instants]
    values = []
    for i, local in enumerate(local_times):
        weekday, clock = local.weekday(), local.hour + local.minute / 60
        if volume == "quiet":
            value = 1 if rng.random() < 0.032 else 0
        elif volume == "flat":
            value = 12
        else:
            rate = 27.0 if volume == "busy" else 1.6
            if cohort == "calendar-free":
                multiplier = 1
            else:
                daily = ((0.45 if clock < 7 or clock >= 19 else 1.8)
                         if cohort != "utc-smooth" else 1 + 0.48 * math.cos((clock - 13) * math.tau / 24))
                multiplier = daily * {0: 1.23, 5: 0.61, 6: 0.28}.get(weekday, 1.0)
            value = poisson(rate * multiplier, rng)
        values.append(value)

    def locate(week_number, weekday, clock_hour):
        return next(i for i in range(week_number * WEEK, (week_number + 2) * WEEK)
                    if local_times[i].weekday() == weekday and local_times[i].hour == clock_hour
                    and local_times[i].minute == 0)

    magnitude = 52 if volume == "busy" else 9
    moderate = 5 if volume == "busy" else 1
    outage = locate(15, 1, 11)
    events = [
        Incident("weekend_spike", locate(13, 5, 10), 3, magnitude),
        Incident("weekday_outage", outage, 18, -max(values[outage:outage+18]) or -1),
        Incident("moderate_weekday_rise", locate(17, 0, 11), 24, moderate),
        Incident("moderate_weekend_drop", locate(18, 6, 13), 36, -moderate),
        Incident("multi_day_guard_overlap", locate(19, 3, 9), 3 * DAY, 2 * moderate),
        Incident("unannounced_level_change", locate(22, 2, 6), DAY, 2 * moderate),
        Incident("growth_change", locate(23, 3, 6), 48, 3 * moderate),
    ]
    if volume == "quiet":
        events = [event for event in events if event.change > 0 and event.kind != "weekday_outage"]
    if cohort in ("spring-forward", "fall-back"):
        switch = next(i for i in range(origin, len(instants))
                      if local_times[i].utcoffset() != local_times[i-1].utcoffset())
        events.append(Incident("dst_boundary_spike", switch, 1, magnitude, boundary=True))

    injected = inject(values, [event for event in events if event.kind != "growth_change"])
    growth = next(event for event in events if event.kind == "growth_change")
    for age in range(growth.duration):
        injected[growth.start + age] += math.ceil(growth.change * (age + 1) / growth.duration)
    annotations, resets = {}, []
    if cohort == "sparse":
        statuses = ["complete"] * len(values)
        arrivals = [None] * len(values)
        for start_index, stop, status in (
                (0, 10 * DAY, "unknown"), (15 * DAY, 25 * DAY, "unknown"),
                (42 * DAY, 45 * DAY, "unknown"), (origin + 90, origin + 100, "empty"),
                (outage, outage + 8, "unknown"), (len(values) - 3, len(values), "incomplete")):
            for index in range(start_index, stop):
                statuses[index] = status
                values[index] = injected[index] = 1 if status == "incomplete" else None
        late = origin + 68
        arrivals[late] = timestamps[late + DAY + 3]
        revision_index = origin + 359
        revisions = [{"timestamp": timestamps[revision_index], "value": values[revision_index] + 2,
                      "available_at": timestamps[revision_index + 8 * DAY], "revision_id": "reconciled"}]
        resets.append(timestamps[5 * WEEK + 12])
        annotations = dict(data_policy={"missing": "zero_for_empty", "measurement": "additive_volume"},
                           coverage=statuses, available_at=arrivals, revisions=revisions)
    pair = f"{volume}-{cohort}-{seed + 397 * case_index}"
    for variant, series in (("control", values), ("injected", injected)):
        yield Case(f"{pair}-{variant}", pair, volume, cohort, timestamps, series, origin,
                   4 * WEEK, CALIBRATION, tuple(events) if variant == "injected" else (),
                   variant, zone, resets, annotations)


def cases(split):
    if split == "regression":
        for suite, make in SUITES.items():
            for fixture in make():
                times = [(START + i * STEP).isoformat() for i in range(len(fixture.values))]
                yield Case(f"{suite}-{fixture.name}", f"{suite}-{fixture.name}",
                           fixture.name.split("-")[0], suite, times, fixture.values, ORIGIN,
                           TRAIN, CALIBRATION, fixture.incidents, "injected" if fixture.incidents else "control")
        return
    _, spring, fall, utc = SPLITS[split]
    for number, (volume, cohort, zone, start) in enumerate((
            ("busy", "spring-forward", "America/Los_Angeles", spring),
            ("busy", "fall-back", "America/Los_Angeles", fall),
            ("busy", "utc-smooth", "UTC", utc),
            ("busy", "calendar-free", "UTC", utc),
            ("low", "sparse", "Asia/Kathmandu", utc),
            ("quiet", "calendar-free", "UTC", utc),
            ("flat", "calendar-free", "UTC", utc))):
        yield from _long_case(split, number, volume, cohort, zone, start)


@dataclass
class Arm:
    scored: set
    points: set
    alerts: set
    boundaries: set
    reasons: dict
    openings: set = field(init=False)

    def __post_init__(self):
        self.openings = run_starts(self.alerts, self.boundaries)


def run_starts(indexes, boundaries):
    return {index for index in indexes if index - 1 not in indexes or index in boundaries}


def _arm(evidence, patterns, boundaries, reasons):
    scored = {row["index"] for row in evidence if row["signal_maturity"] == "calibrated"}
    point = {row["index"] for row in evidence if row["triggers"]}
    alert = point | ({row["detection_index"] for row in patterns} & scored)
    return Arm(scored, point, alert, set(boundaries), reasons)


def _fixed_arm(dataset, config, times, quality, lag, stop):
    """Fixed elapsed lags in the paired forward-replay protocol.

    Complete histories use the library's one/four-reference reducer. Missing
    required lagged values abstain so a gap cannot substitute a different lag.
    Calibration outlier decisions apply going forward in every paired arm.
    """
    budget = RuntimeBudget(config.max_runtime_seconds)
    state = Calibration(0, 0)
    available = AvailableVersions(quality)
    explicit = set(active_resets(config.reset_points, times, dataset.timezone))
    zone = ZoneInfo(dataset.timezone)
    boundaries, reasons, evidence, all_evidence, patterns = [], {}, [], [], []
    segment, training, previous_missing = 0, [], False

    def finish_segment():
        method = MethodResult(id="fixed", applicability="fixed elapsed lag", status="completed", evidence=evidence)
        patterns.extend(anomaly_patterns([method], dataset.id, cusum_k=config.cusum_k, cusum_h=config.cusum_h,
                                        moving_range_threshold=config.moving_range_threshold))

    for index, when in enumerate(times):
        budget.check()
        instant = timestamp(when)
        available.advance(instant)
        sample = available.visible[index]
        value = sample["value"]
        restart = (dataset.data_policy and dataset.data_policy.reference_gaps == "restart"
                   and previous_missing and value is not None)
        previous_missing = value is None
        if index in explicit or restart:
            finish_segment()
            boundaries.append(index)
            segment, training, state = index, [], Calibration(0, 0)
            all_evidence.extend(evidence)
            evidence = []
        in_training = index - segment < max(config.training_size, lag)
        if in_training and value is not None and len(training) < 4096:
            training.append(value)
        if value is None:
            reasons[index] = sample["reason"]
            continue
        if index - segment < lag:
            reasons[index] = "unsupported_fixed_reference"
            continue
        count = 4 if config.outlier_handling == "robust" and index - segment >= 4 * lag else 1
        values = [available.peer(index - age * lag)[0] for age in range(count, 0, -1)]
        if None in values:
            reasons[index] = "unsupported_fixed_reference"
            continue
        expected = (reduce_references([(v, reference_weight(count - offset, count))
                                       for offset, v in enumerate(values)])[0]
                    if count == 4 else values[-1])
        residual = value - expected
        center, scale, samples, maturity = state.estimate(config)
        z = (residual - center) / scale if scale is not None else None
        calibrated = maturity == "calibrated"
        protected = calibrated and config.outlier_handling == "robust" and abs(z) > EXTREME_Z
        if not calibrated:
            reasons[index] = "training_prefix" if in_training else "uncalibrated_fixed_key"
        evidence.append(dict(id=f"fixed:{index}", method="fixed", index=index, timestamp=when,
                             training_cutoff=times[segment], observed=value, expected=expected, residual=residual,
                             relative_deviation=residual / abs(expected) if expected else None,
                             standardized_residual=z, signal_maturity=maturity, calibration_samples=samples,
                             triggers=["point"] if calibrated and abs(z) > config.point_threshold else [],
                             score_semantics="paired fixed lag residual", excluded_from_model=protected,
                             model_value=expected if protected else value, exclusion_reason=None,
                             reference_action="use_expected" if protected else "use_observed"))
        if not calibrated and not in_training and index < stop:
            day = instant.astimezone(zone).date()
            state.admit(dict(index=index, expected=expected, residual=residual, day=day, sample=sample),
                        day, times, config, training, budget.check, season_length=lag)
            available.protect_calibration(state)
        if protected:
            available.replacements[index] = (sample, expected)
    finish_segment()
    return _arm(all_evidence + evidence, patterns, boundaries, reasons)


def score(case):
    dataset = DatasetV11(id="counts", entity={"fixture": case.name}, values=case.values,
                         timestamps=case.timestamps, timezone=case.zone, frequency="5min",
                         calendar_reference=PROFILE, **case.annotations)
    config = Settings(trend="none", training_size=case.training, calibration_size=case.calibration,
                      scale_floor=COUNT_FLOOR, reset_points=case.resets, max_points=60_000,
                      max_bytes=20_000_000, max_runtime_seconds=180)
    prepared = normalize(dataset, config, Context())
    times, _, quality = prepared
    arms = {}
    for name, lag in LAGS.items():
        try:
            arms[name] = _fixed_arm(dataset, config, times, quality, lag, case.origin)
        except (TimeoutError, ArithmeticError, ValueError, RuntimeError) as exc:
            print(f"{case.name} {name}: {exc}", flush=True)
            arms[name] = Arm(set(), set(), set(), set(), dict.fromkeys(range(len(times)), "failure"))
    stages = {}
    for name, width in (("calendar", None), ("calendar_zero_width", 0)):
        result = analyze_calendar(dataset, config, {}, prepared=prepared, calibration_stop=case.origin,
                                  clock_width_override=width, audit_selections=False)
        method = result.methods[0]
        targets = method.diagnostics["targets"]
        reasons = {row["index"]: row["reason"] for row in targets if row["reason"]}
        for index in set(range(len(times))) - {row["index"] for row in targets}:
            reasons[index] = "failure"
        if method.status in ("budget_exceeded", "failed"):
            print(f"{case.name} {name}: {method.error}", flush=True)
        arms[name] = _arm(method.evidence, result.anomaly_patterns,
                          method.diagnostics["pattern_boundaries"], reasons)
        stages[name] = [next((tier.name for tier in TIERS
                             if row["index"] - row["segment_start_index"] >= tier.minimum_age_days * DAY), "young")
                        for row in targets]
    return arms, stages["calendar"]


def grade(case, arms, stages):
    """Grade native starts before intersecting coverage; keep abstentions visible."""
    size = len(case.values)
    truth = {i for incident in case.incidents for i in range(incident.start, incident.stop)}
    normal = set(range(size)) - truth
    zone = ZoneInfo(case.zone)
    local = [timestamp(value).astimezone(zone) for value in case.timestamps]
    evaluation = set(range(case.origin, size))
    startup = set(range(case.origin))
    groups = {"all": evaluation, "startup": startup}
    groups["mature"] = {i for i in evaluation if i < len(stages) and stages[i] == TIERS[0].name}
    for label, indexes in (
            ("weekend", {i for i in evaluation if local[i].weekday() >= 5}),
            ("weekday", {i for i in evaluation if local[i].weekday() < 5}),
            *[(f"weekday_{weekday}", {i for i in evaluation if local[i].weekday() == weekday}) for weekday in range(7)],
            *[(f"startup_{stage}", {i for i in startup if i < len(stages) and stages[i] == stage})
              for stage in ("young", *(tier.name for tier in TIERS))]):
        groups[label] = indexes
    metadata = dict(case=case.name, pair=case.pair, variant=case.variant,
                    volume=case.volume, cohort=case.cohort, timezone=case.zone)
    rows, incidents = [], []
    for scope, members in SCOPES.items():
        shared = set.intersection(*(arms[name].scored for name in members))
        for name in members:
            arm = arms[name]
            eligible = arm.scored if scope == "native" else shared
            for group, indexes in groups.items():
                scored = eligible & indexes
                scored_normal = scored & normal
                false = arm.alerts & scored_normal
                reasons = Counter(arm.reasons.get(i, "failure") if i not in arm.scored else "outside_shared_coverage"
                                  for i in indexes - scored)
                rows.append(dict(**metadata, scope=scope, arm=name, group=group, possible=len(indexes),
                                 scored=len(scored), possible_normal=len(indexes & normal),
                                 scored_normal=len(scored_normal), incident_buckets=len(indexes & truth),
                                 scored_incident_buckets=len(scored & truth),
                                 false_point_buckets=len(arm.points & scored_normal), false_alert_buckets=len(false),
                                 false_alert_runs=len(run_starts(false, arm.boundaries)),
                                 native_false_alert_starts=len(arm.openings & scored_normal),
                                 unavailable=json.dumps(reasons, sort_keys=True)))
            for incident in case.incidents:
                incident_indexes = set(range(incident.start, incident.stop)) & evaluation
                observed = incident_indexes & eligible
                first = min(observed & arm.alerts, default=None)
                first_point = min(observed & arm.points, default=None)
                incidents.append(dict(**metadata, scope=scope, arm=name, incident=incident.kind,
                                      start_index=incident.start, stop_index=incident.stop, boundary=incident.boundary,
                                      scored_buckets=len(observed), possible_buckets=len(incident_indexes),
                                      scored_fraction=len(observed) / len(incident_indexes) if incident_indexes else 0,
                                      outcome="detected" if first is not None else "missed" if observed else "unassessed",
                                      first_signal=first, first_point=first_point,
                                      delay_minutes=(first - incident.start) * 5 if first is not None else None))
    return rows, incidents


def _sum(rows, field):
    return sum(row[field] for row in rows)


def _rate(rows, numerator, denominator):
    count = _sum(rows, denominator)
    return _sum(rows, numerator) / count if count else None


def _matched(rows, scope, baseline, group="all", *, variant=None, **cohort):
    selected = [row for row in rows if row["scope"] == scope and row["group"] == group
                and (variant is None or row["variant"] == variant)
                and all(row[key] == value for key, value in cohort.items())]
    return ([row for row in selected if row["arm"] == baseline],
            [row for row in selected if row["arm"] == "calendar"])


def paired_run_delta(left, right):
    """Resample matched case differences, never adjacent individual buckets."""
    baseline = {row["pair"]: row for row in left}
    changes = {}
    for row in right:
        prior = baseline.get(row["pair"])
        if prior and prior["scored_normal"] and row["scored_normal"]:
            changes[row["pair"]] = 1000 * (row["false_alert_runs"] / row["scored_normal"]
                                            - prior["false_alert_runs"] / prior["scored_normal"])
    values = list(changes.values())
    if not values:
        return dict(case_deltas={}, mean=None, case_bootstrap_95=None)
    rng = Random(98163)
    draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(LIMITS["paired_resamples"]))
    return dict(case_deltas=changes, mean=mean(values),
                case_bootstrap_95=[draws[len(draws)//40], draws[len(draws)*39//40 - 1]] if len(values) > 1 else None)


def _incident_pairs(incidents, baseline, scope="native", *, boundary=False):
    matching = {(row["case"], row["incident"], row["start_index"]): row for row in incidents
                if row["arm"] == baseline and row["scope"] == scope and row["boundary"] == boundary}
    return [(matching[row["case"], row["incident"], row["start_index"]], row) for row in incidents
            if row["arm"] == "calendar" and row["scope"] == scope and row["boundary"] == boundary]


def summary(rows, incidents, split):
    scopes = {}
    for scope, members in SCOPES.items():
        scopes[scope] = {}
        for name in members:
            normal = [row for row in rows if row["scope"] == scope and row["arm"] == name and row["group"] == "all"]
            incident = [row for row in incidents if row["scope"] == scope and row["arm"] == name]
            # Controls supply false-alert metrics. Injected rows supply incident grades.
            controls = [row for row in normal if row["variant"] == "control"]
            scopes[scope][name] = dict(
                **{key: _sum(controls, key) for key in ("scored_normal", "possible_normal", "false_point_buckets",
                                                      "false_alert_buckets", "false_alert_runs", "native_false_alert_starts")},
                incident_counts=dict(Counter(row["outcome"] for row in incident)),
                main_incident_counts=dict(Counter(row["outcome"] for row in incident if not row["boundary"])),
                boundary_incident_counts=dict(Counter(row["outcome"] for row in incident if row["boundary"])),
                incident_detection_over_all=(sum(row["outcome"] == "detected" for row in incident) / len(incident)
                                             if incident else None),
                incident_scored_fraction=_rate(incident, "scored_buckets", "possible_buckets"))
    output = dict(split=split, limits=LIMITS, scopes=scopes)
    if split == "regression":
        return output
    busy = _matched(rows, "shared_three", "daily", "weekend", variant="control", volume="busy")
    busy = tuple([row for row in arm if row["cohort"] != "calendar-free"] for arm in busy)
    left, right = busy
    reductions = paired_run_delta(left, right)
    denominator = _sum(left, "false_alert_runs")
    reduction = 1 - _sum(right, "false_alert_runs") / denominator if denominator else None
    pairs = _incident_pairs(incidents, "daily")
    delays = [b["delay_minutes"] - a["delay_minutes"] for a, b in pairs
              if a["delay_minutes"] is not None and b["delay_minutes"] is not None]
    worsened = [(a["case"], a["incident"], a["outcome"], b["outcome"]) for a, b in pairs
                if {"detected": 0, "missed": 1, "unassessed": 2}[b["outcome"]]
                > {"detected": 0, "missed": 1, "unassessed": 2}[a["outcome"]]]
    native_mature = _matched(rows, "native", "daily", "mature", variant="control")
    native_incident = _matched(rows, "native", "daily", "mature", variant="injected")
    shared_mature = _matched(rows, "shared_three", "daily", "mature", variant="control")[1]
    mature_daily, mature_calendar = [_rate(arm, "scored_normal", "possible_normal") for arm in native_mature]
    incident_daily, incident_calendar = [_rate(arm, "scored_incident_buckets", "incident_buckets") for arm in native_incident]
    shared_fraction = _rate(shared_mature, "scored_normal", "possible_normal")
    weekday = paired_run_delta(*_matched(rows, "shared_three", "daily", "weekday", variant="control"))
    free = paired_run_delta(*_matched(rows, "shared_three", "daily", variant="control", cohort="calendar-free"))
    output["daily_review"] = dict(
        weekend_relative_reduction=reduction, weekend_paired=reductions,
        normal_coverage_loss_pp=100 * (mature_daily - mature_calendar),
        incident_coverage_loss_pp=100 * (incident_daily - incident_calendar),
        shared_mature_normal_coverage=shared_fraction, worsened_incidents=worsened,
        maximum_delay_increase_minutes=max(delays, default=None), weekday_paired=weekday, calendar_free_paired=free,
    )
    output["gates"] = dict(
        weekend_runs=(reduction is not None and reduction >= LIMITS["weekend_run_reduction"]
                      and sum(value < 0 for value in reductions["case_deltas"].values()) >= LIMITS["busy_cases_with_reduction"]),
        mature_normal_coverage=100 * (mature_daily - mature_calendar) <= LIMITS["coverage_pp_loss"],
        mature_incident_coverage=100 * (incident_daily - incident_calendar) <= LIMITS["coverage_pp_loss"],
        no_incidents_worsened=not worsened,
        max_delay=bool(delays) and max(delays) <= LIMITS["max_extra_delay_minutes"],
        weekday=weekday["mean"] is not None and weekday["mean"] <= LIMITS["weekday_and_calendar_free_extra_runs_per_1000"],
        calendar_free=free["mean"] is not None and free["mean"] <= LIMITS["weekday_and_calendar_free_extra_runs_per_1000"],
        shared_mature_normal_coverage=shared_fraction >= LIMITS["mature_incident_free_shared_floor"],
    )
    output["weekly_review"] = {}
    for scope in ("native", "shared_weekly_calendar"):
        weekly = _incident_pairs(incidents, "weekly", scope)
        output["weekly_review"][scope] = dict(
            paired_false_alert_runs=paired_run_delta(*_matched(rows, scope, "weekly", variant="control")),
            incident_outcome_pairs=dict(Counter(f"{a['outcome']} → {b['outcome']}" for a, b in weekly)),
            delay_delta_minutes=[b["delay_minutes"] - a["delay_minutes"] for a, b in weekly
                                 if a["delay_minutes"] is not None and b["delay_minutes"] is not None])
    return output


def run(split, output):
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    sources = [Path(__file__).resolve(), Path(__file__).with_name("five_minute_fixtures.py"),
               *(root / "src" / "anomalyzer" / name for name in
                 ("baseline.py", "calendar_baseline.py", "calendar_scoring.py", "sparse.py", "evidence.py"))]
    protocol = dict(split=split, seed_and_calendar_starts=SPLITS.get(split), limits=LIMITS,
                    profile=PROFILE, scope_arms=SCOPES, scale_floor=COUNT_FLOOR,
                    source_sha256={path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sources})
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    rows, incidents = [], []
    for case in cases(split):
        print(f"{split}: {case.name}", flush=True)
        case_rows, incident_rows = grade(case, *score(case))
        rows.extend(case_rows)
        incidents.extend(incident_rows)
    write_csv(output / "coverage.csv", rows)
    write_csv(output / "incidents.csv", incidents)
    (output / "summary.json").write_text(json.dumps(summary(rows, incidents, split), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("regression", *SPLITS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.split, args.output)
