"""Replay five-minute integer counts with and without a count-sized scale floor."""

import argparse
from collections import Counter
from datetime import timedelta
import json
import math
from pathlib import Path
from statistics import median

from anomalyzer import __version__, analyze
from count_persistence_policy import confirm_alerts, learn_reference

from five_minute_fixtures import (
    BUCKETS_PER_DAY, TRAIN, CALIBRATION, HOLDOUT, ORIGIN, START, COUNT_FLOOR,
    SEEDS, Incident, Fixture, poisson, inject, fixtures, clustered_counts,
    quiet_incident, holdout_fixtures, persistence_fixtures, SUITES, write_csv,
)


def analyze_fixture(fixture, timestamps, floor=None):
    request = {
        "schema_version": "1.1",
        "datasets": [{"id": "requests", "entity": {"fixture": fixture.name}, "values": fixture.values,
                      "timestamps": timestamps, "frequency": "5min", "units": "requests"}],
        "config": {"training_size": TRAIN, "calibration_size": CALIBRATION, "season_length": BUCKETS_PER_DAY,
                   "trend": "none"},
    }
    if floor is not None:
        request["config"]["scale_floor"] = floor
    result = analyze(request)
    target = result.dataset_results[0]
    if any(method.status in {"failed", "budget_exceeded"} for method in target.methods):
        raise RuntimeError(f"{fixture.name} did not finish: {[method.error for method in target.methods]}")
    return target


def score(fixture, timestamps, floor):
    target = analyze_fixture(fixture, timestamps, floor)
    points = {e["index"]: e for method in target.methods for e in method.evidence
              if e["signal_maturity"] == "calibrated" and e["index"] >= ORIGIN}
    patterns = {}
    for pattern in target.anomaly_patterns:
        patterns.setdefault(pattern["detection_index"], set()).add(pattern["rule"])
    return points, patterns


def run(output, count_floor=COUNT_FLOOR, suite="original", persistence=False):
    timestamps = [(START + timedelta(minutes=5 * i)).isoformat() for i in range(ORIGIN + HOLDOUT)]
    inputs, buckets, cases, incidents, clusters = [], [], [], [], []
    modes = ("before", "after", "persistence") if persistence else ("before", "after")
    for fixture in SUITES[suite]():
        truth = {i: event for event in fixture.incidents for i in range(event.start, event.stop)}
        inputs.extend(dict(case=fixture.name, index=i, timestamp=timestamps[i], count=value,
                           split="holdout" if i >= ORIGIN else "calibration" if i >= TRAIN else "train",
                           incident=truth[i].kind if i in truth else "",
                           boundary=truth[i].boundary if i in truth else False)
                      for i, value in enumerate(fixture.values))
        reference = learn_reference(fixture.values[:ORIGIN]) if persistence else None
        for mode in modes:
            if mode != "persistence":
                floor = None if mode == "before" else count_floor
                points, patterns = score(fixture, timestamps, floor)
            point_flags = {i for i, point in points.items() if "point" in point["triggers"]}
            alerts = point_flags | (patterns.keys() & points.keys())
            confirmed = set()
            if mode == "persistence":
                point_flags, alerts, confirmed = confirm_alerts(fixture.values, points.keys(), point_flags,
                                                               patterns, reference)
            false_flags = sorted(alerts - truth.keys())
            for start, stop in fixture.noise_clusters:
                if start >= ORIGIN:
                    span = set(range(start, stop))
                    clusters.append(dict(case=fixture.name, mode=mode, start=start, timestamp=timestamps[start],
                                         length=stop-start, scored=len(span & points.keys()),
                                         point_flags=len(span & point_flags), alert_buckets=len(span & alerts)))
            cases.append(dict(case=fixture.name, mode=mode, scored=len(points),
                              confirmation_buckets=reference.confirmation_buckets if mode == "persistence" and reference else None,
                              unknown=sum(v is None for v in fixture.values[ORIGIN:]), unscored=HOLDOUT-len(points),
                              scored_normal=len(points.keys() - truth.keys()),
                              false_point_buckets=len(point_flags - truth.keys()), false_alert_buckets=len(false_flags),
                              false_alert_runs=sum(i == 0 or index != false_flags[i-1] + 1
                                                   for i, index in enumerate(false_flags))))
            for event in fixture.incidents:
                positions = range(event.start, event.stop)
                first = next((i for i in positions if i in alerts), None)
                status = "detected" if first is not None else "missed" if any(i in points for i in positions) else "unassessed"
                incidents.append(dict(case=fixture.name, mode=mode, incident=event.kind, boundary=event.boundary,
                                      onset=event.start, first=first, delay_minutes=5*(first-event.start) if first is not None else None,
                                      status=status))
            for i in range(ORIGIN, len(timestamps)):
                evidence = points.get(i)
                buckets.append(dict(case=fixture.name, mode=mode, index=i, timestamp=timestamps[i],
                                    expected=evidence["expected"] if evidence else None,
                                    residual=evidence["residual"] if evidence else None,
                                    z=evidence["standardized_residual"] if evidence else None,
                                    point_flag=i in point_flags if evidence else None,
                                    patterns=";".join(sorted(patterns.get(i, ()))),
                                    persistence_confirmation=i in confirmed if evidence else None,
                                    alert=i in alerts if evidence else None))
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("fixtures", inputs), ("buckets", buckets), ("cases", cases), ("incidents", incidents)):
        write_csv(output / f"{name}.csv", rows)
    if clusters:
        write_csv(output / "ordinary_clusters.csv", clusters)
    summary = {"anomalyzer": __version__, "training_buckets": TRAIN, "calibration_buckets": CALIBRATION,
               "holdout_buckets_per_case": HOLDOUT, "after_scale_floor": count_floor, "suite": suite, "modes": {}}
    for mode in modes:
        results = [row for row in cases if row["mode"] == mode]
        metrics = {key: sum(row[key] for row in results) for key in
                   ("scored", "unknown", "unscored", "scored_normal", "false_point_buckets", "false_alert_buckets", "false_alert_runs")}
        for boundary in (False, True):
            group = [row for row in incidents if row["mode"] == mode and row["boundary"] == boundary]
            delays = [row["delay_minutes"] for row in group if row["status"] == "detected"]
            metrics["one_count_boundary" if boundary else "main_incidents"] = dict(
                Counter(row["status"] for row in group), median_delay_minutes=median(delays) if delays else None,
                max_delay_minutes=max(delays, default=None))
        if clusters:
            ordinary = [row for row in clusters if row["mode"] == mode and row["case"].endswith("-control")]
            metrics["ordinary_clusters_in_controls"] = {
                label: {"total": len(group), "with_alert": sum(row["alert_buckets"] > 0 for row in group)}
                for label, group in (("singletons", [row for row in ordinary if row["length"] == 1]),
                                     ("multi_bucket", [row for row in ordinary if row["length"] > 1]))
            }
        summary["modes"][mode] = metrics
    before = {(row["case"], row["incident"]): row for row in incidents if row["mode"] == "before"}
    changes = []
    for row in (row for row in incidents if row["mode"] == "after"):
        previous = before[row["case"], row["incident"]]
        if (previous["status"], previous["delay_minutes"]) != (row["status"], row["delay_minutes"]):
            changes.append(dict(case=row["case"], incident=row["incident"], before=previous["status"],
                                after=row["status"], before_delay_minutes=previous["delay_minutes"],
                                after_delay_minutes=row["delay_minutes"]))
    summary["changed_incidents"] = changes
    if persistence:
        floor_only = {(row["case"], row["incident"]): row for row in incidents if row["mode"] == "after"}
        summary["persistence_changes_vs_floor"] = [
            dict(case=row["case"], incident=row["incident"], floor_delay_minutes=previous["delay_minutes"],
                 persistence_delay_minutes=row["delay_minutes"], floor_status=previous["status"],
                 persistence_status=row["status"])
            for row in incidents if row["mode"] == "persistence"
            for previous in [floor_only[row["case"], row["incident"]]]
            if (row["status"], row["delay_minutes"]) != (previous["status"], previous["delay_minutes"])
        ]
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count-floor", type=float, default=COUNT_FLOOR)
    parser.add_argument("--suite", choices=(*SUITES, "all"), default="original")
    parser.add_argument("--persistence", action="store_true", help="Also replay the experimental alert policy")
    args = parser.parse_args()
    if not math.isfinite(args.count_floor) or args.count_floor <= 0:
        parser.error("--count-floor must be positive and finite")
    if args.suite == "all":
        for suite in SUITES:
            print(json.dumps(run(args.output / suite, args.count_floor, suite, args.persistence), indent=2), flush=True)
    else:
        print(json.dumps(run(args.output, args.count_floor, args.suite, args.persistence), indent=2))
