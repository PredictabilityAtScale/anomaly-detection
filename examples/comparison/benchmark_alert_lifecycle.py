"""Tune a PostHog-inspired lifecycle on prior count suites and check a fresh holdout."""

import argparse
from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
from random import Random
from statistics import median

from anomalyzer.evaluation.alert_lifecycle import ALERT_ACTIONS, Signal, replay_alert_lifecycle
from benchmark_five_minute_counts import (
    BUCKETS_PER_DAY, HOLDOUT, ORIGIN, START, SUITES, Fixture, Incident, clustered_counts,
    inject, poisson, quiet_incident, score, write_csv,
)


@dataclass(frozen=True)
class Policy:
    name: str
    recovery: int
    realert_on_point: bool = False
    pattern_grace_only: bool = False


BASE = Policy("adjacent", 1)
POLICIES = (BASE,) + tuple(
    Policy(f"{variant}-{quiet}", quiet, realert, pattern_only)
    for quiet in (2, 3, 4, 6, 8, 12)
    for variant, realert, pattern_only in (("hold", False, False), ("realert", True, False), ("pattern-grace", True, True))
)


@dataclass(frozen=True)
class Evidence:
    suite: str
    fixture: Fixture
    signals: tuple[Signal, ...]


def holdout_fixtures():
    for name, level, seed, widths in (("quiet", 0, 2689, (1, 2, 4, 6)), ("flat", 14, 3251, (1, 1, 2, 4, 5))):
        values, noise = clustered_counts(level, seed, 48, 29, widths)
        nearby = quiet_incident(values, level, "anchor", 170, 3, 1).start
        events = (
            Incident("nearby_spike_one", nearby, 1, 5),
            Incident("nearby_spike_two", nearby + 2, 1, 6),
            quiet_incident(values, level, "one_count_shift", 360, 20, 1),
            quiet_incident(values, level, "late_outage" if level else "late_burst", 670, 10, -level if level else 5),
        )
        yield Fixture(f"{name}-control", values, noise_clusters=noise)
        yield Fixture(f"{name}-incidents", inject(values, events), events, noise_clusters=noise)
    for name, rate, seed, spike in (("sparse", 1.9, 8629, 14), ("busy", 34, 7477, 70)):
        rng = Random(seed)
        values = [poisson(rate * (1.6 if 84 <= i % BUCKETS_PER_DAY < 225 else 0.65), rng)
                  for i in range(ORIGIN + HOLDOUT)]
        start = ORIGIN + 376
        events = (
            Incident("nearby_spike_one", ORIGIN + 150, 1, spike),
            Incident("nearby_spike_two", ORIGIN + 153, 1, spike),
            Incident("outage", start, 15, -max(values[start:start+15])),
            Incident("sustained_rise", ORIGIN + 687, 30, 3 if name == "sparse" else 12),
        )
        yield Fixture(f"{name}-control", values)
        observed = inject(values, events)
        observed[ORIGIN+500:ORIGIN+503] = [None] * 3
        yield Fixture(f"{name}-incidents", observed, events)


def evaluate(suite, fixtures, timestamps):
    evidence = []
    for fixture in fixtures:
        points, patterns = score(fixture, timestamps, None)
        signals = tuple("unknown" if i not in points else "point" if "point" in points[i]["triggers"]
                        else "pattern" if i in patterns else "quiet" for i in range(ORIGIN, ORIGIN + HOLDOUT))
        evidence.append(Evidence(suite, fixture, signals))
    return evidence


def grade(evidence, policy):
    cases, incident_rows = [], []
    for series in evidence:
        steps = replay_alert_lifecycle(series.signals, resolve_after=policy.recovery, reopen_within=12,
                                      realert_on_point=policy.realert_on_point, pattern_grace_only=policy.pattern_grace_only)
        alerts = {i+ORIGIN for i, step in enumerate(steps) if step.action in ALERT_ACTIONS}
        labels = {i for event in series.fixture.incidents for i in range(event.start, event.stop)}
        tag = dict(suite=series.suite, case=series.fixture.name, policy=policy.name)
        cases.append(dict(**tag, alert_starts=len(alerts), false_starts=len(alerts-labels),
                          open_normal_buckets=sum(step.active_issue is not None and signal != "unknown" and i+ORIGIN not in labels
                                                  for i, (step, signal) in enumerate(zip(steps, series.signals, strict=True))),
                          held_quiet_buckets=sum(step.active_issue is not None and signal == "quiet" and i+ORIGIN not in labels
                                                 for i, (step, signal) in enumerate(zip(steps, series.signals, strict=True)))))
        for event in series.fixture.incidents:
            positions = range(event.start, event.stop)
            first = next((i for i in positions if i in alerts), None)
            status = "detected" if first is not None else "missed" if any(series.signals[i-ORIGIN] != "unknown" for i in positions) else "unassessed"
            incident_rows.append(dict(**tag, incident=event.kind, onset=event.start, stop=event.stop,
                                     onset_time=(START + timedelta(minutes=5*event.start)).isoformat(), status=status,
                                     first_alert=first, delay_minutes=5*(first-event.start) if first is not None else None,
                                     already_open=steps[event.start-ORIGIN-1].active_issue is not None if event.start > ORIGIN else False))
    return cases, incident_rows


def compare(incident_rows, baseline):
    reference = {(r["suite"], r["case"], r["incident"], r["onset"]): r for r in baseline}
    pairs = []
    for row in incident_rows:
        before = reference[tuple(row[k] for k in ("suite", "case", "incident", "onset"))]
        pairs.append((before, row))
    return pairs


def totals(policy, cases, incident_rows, baseline):
    delays = [r["delay_minutes"] for r in incident_rows if r["status"] == "detected"]
    pairs = compare(incident_rows, baseline)
    return dict(policy=policy.name, recovery_buckets=policy.recovery, realert_on_point=policy.realert_on_point,
                pattern_grace_only=policy.pattern_grace_only,
                **{k: sum(r[k] for r in cases) for k in ("false_starts", "open_normal_buckets", "held_quiet_buckets")},
                detected=len(delays), missed=sum(r["status"] == "missed" for r in incident_rows),
                unassessed=sum(r["status"] == "unassessed" for r in incident_rows),
                newly_missed=sum(a["status"] == "detected" and b["status"] == "missed" for a,b in pairs),
                later=sum(a["status"] == b["status"] == "detected" and b["delay_minutes"] > a["delay_minutes"] for a,b in pairs),
                median_delay_minutes=median(delays) if delays else None,
                longest_delay_minutes=max(delays, default=None))


def run(output):
    timestamps = [(START + timedelta(minutes=5*i)).isoformat() for i in range(ORIGIN + HOLDOUT)]
    development = [row for name, source in SUITES.items() for row in evaluate(name, source(), timestamps)]
    _, baseline = grade(development, BASE)
    sweep = [totals(policy, *grade(development, policy), baseline) for policy in POLICIES]
    winner = min((r for r in sweep if not r["newly_missed"] and not r["later"]),
                 key=lambda r: (r["false_starts"], r["held_quiet_buckets"], r["recovery_buckets"]))
    policy = next(policy for policy in POLICIES if policy.name == winner["policy"])
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output/"development_sweep.csv", sweep)
    (output/"locked_policy.json").write_text(json.dumps(winner, indent=2)+"\n", encoding="utf-8")

    fresh = evaluate("fresh-holdout", holdout_fixtures(), timestamps)
    ref_cases, ref_incidents = grade(fresh, BASE)
    trial_cases, trial_incidents = grade(fresh, policy)
    holdout = {
        "reference": totals(BASE, ref_cases, ref_incidents, ref_incidents),
        "locked": totals(policy, trial_cases, trial_incidents, ref_incidents),
    }
    for name, rows in (("holdout_cases", ref_cases + trial_cases), ("holdout_incidents", ref_incidents + trial_incidents)):
        write_csv(output/f"{name}.csv", rows)
    write_csv(output/"holdout_signals.csv", [dict(case=s.fixture.name, index=i+ORIGIN, timestamp=timestamps[i+ORIGIN],
        observed=s.fixture.values[i+ORIGIN], signal=signal) for s in fresh for i, signal in enumerate(s.signals)])
    summary = {"development_reference": next(r for r in sweep if r["policy"] == BASE.name),
               "development_selected": winner, "holdout": holdout}
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), indent=2))
