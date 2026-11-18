"""Paired hourly replay for calendar fallback and empirical range evidence."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from random import Random

from anomalyzer import analyze
from benchmark_five_minute_counts import write_csv


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    cases, incidents, ranges, buckets = [], [], [], []
    start = datetime(2025, 1, 6, tzinfo=timezone.utc)
    size, origin = 98*24, 35*24
    times = [(start+i*timedelta(hours=1)).isoformat() for i in range(size)]
    for name, seed, daily, reset in (("flat", 5507, False, None), ("weekly", 6947, True, None),
                                     ("weekly-reset", 8669, True, 56*24)):
        rng = Random(seed)
        values = [max(0, round(30*(0.35 if i//24 % 7 >= 5 else 1)*(1.4 if 8 <= i%24 < 18 else 0.7)
                               + rng.gauss(0, 2))) if daily else max(0, round(30+rng.gauss(0, 2))) for i in range(size)]
        events = ((42*24+10, 3, 25), (61*24+10, 12, -8), (86*24+10, 24, 8))
        changed = values.copy()
        for at, length, change in events:
            changed[at:at+length] = [max(0, v+change) for v in changed[at:at+length]]
        for variant, observed in (("control", values), ("injected", changed)):
            truth = {i for at, length, _ in events for i in range(at, at+length)} if variant == "injected" else set()
            for arm, fallback in (("current", False), ("calibrated_fallback", True)):
                document = {"schema_version": "1.1", "datasets": [{"id": "counts", "entity": {"case": name},
                    "values": observed, "timestamps": times, "frequency": "1h", "timezone": "UTC",
                    "calendar_reference": {"profile": "local-calendar-v1", "calibrated_fallback": fallback,
                                           "expected_range_coverage": 0.95}}],
                    "config": {"trend": "none", "training_size": 48, "calibration_size": 24,
                               "scale_floor": 0.4, "reset_points": [reset] if reset else []}}
                target = analyze(document).dataset_results[0]
                method, = target.methods
                if target.status != "completed":
                    raise RuntimeError(f"{name}/{arm}: {target.status} {method.error}")
                evidence = {e["index"]: e for e in method.evidence if e["signal_maturity"] == "calibrated" and e["index"] >= origin}
                flags = {i for i,e in evidence.items() if e["triggers"]} | {p["detection_index"] for p in target.anomaly_patterns if p["detection_index"] in evidence}
                false = flags - truth
                tags = dict(case=name, variant=variant, arm=arm)
                cases.append(dict(**tags, scored=len(evidence), unscored=size-origin-len(evidence),
                    scored_normal=len(evidence.keys()-truth), false_buckets=len(false), false_runs=sum(i-1 not in false for i in false)))
                for at, length, _ in events if variant == "injected" else ():
                    hit = min(flags & set(range(at, at+length)), default=None)
                    status = "detected" if hit is not None else "missed" if evidence.keys() & set(range(at, at+length)) else "unassessed"
                    incidents.append(dict(**tags, onset=at, stop=at+length, status=status,
                        scored_buckets=len(evidence.keys() & set(range(at, at+length))),
                        unscored_buckets=length-len(evidence.keys() & set(range(at, at+length))),
                        delay_hours=hit-at if hit is not None else None))
                by_range = []
                for row in method.diagnostics["targets"][origin:]:
                    i = row["index"]
                    band = row.get("expected_range", {})
                    available = i in evidence and band.get("status") == "available"
                    outside = not band["lower"] <= observed[i] <= band["upper"] if available else None
                    buckets.append(dict(**tags, index=i, observed=observed[i], incident=i in truth, scored=i in evidence,
                        flag=i in flags if i in evidence else None, range_available=available,
                        lower=band.get("lower") if available else None, upper=band.get("upper") if available else None,
                        outside=outside, tier=row.get("tier"), fallback_reason=row.get("fallback_reason"),
                        unscored_reason=row.get("reason") if i not in evidence else None))
                    if available and i not in truth:
                        by_range.append((outside, band["upper"]-band["lower"]))
                ranges.append(dict(**tags, range_scored_normal=len(by_range), normal_outside=sum(x for x,_ in by_range),
                    normal_coverage=1-sum(x for x,_ in by_range)/len(by_range) if by_range else None,
                    mean_width=sum(w for _,w in by_range)/len(by_range) if by_range else None))
                print(name, variant, arm, cases[-1], flush=True)
    for name, rows in (("cases", cases), ("incidents", incidents), ("ranges", ranges), ("buckets", buckets)):
        write_csv(output/f"{name}.csv", rows)
    summary = {}
    for arm in ("current", "calibrated_fallback"):
        group = [r for r in cases if r["arm"] == arm]
        events = [r for r in incidents if r["arm"] == arm]
        rr = [r for r in ranges if r["arm"] == arm and r["variant"] == "control"]
        summary[arm] = dict(**{k: sum(r[k] for r in group) for k in ("scored", "unscored", "scored_normal", "false_buckets", "false_runs")},
            **{s: sum(r["status"] == s for r in events) for s in ("detected", "missed", "unassessed")},
            range_normal_buckets=sum(r["range_scored_normal"] for r in rr),
            range_normal_outside=sum(r["normal_outside"] for r in rr))
    shared = []
    for name in sorted({r["case"] for r in buckets}):
        for variant in ("control", "injected"):
            groups = {arm: {r["index"]: r for r in buckets if r["case"] == name and r["variant"] == variant
                           and r["arm"] == arm} for arm in summary}
            common = {i for i, r in groups["current"].items() if r["scored"] and groups["calibrated_fallback"][i]["scored"]
                      and not r["incident"]}
            for arm, rows in groups.items():
                false = {i for i in common if rows[i]["flag"]}
                shared.append(dict(case=name, variant=variant, arm=arm, scored_normal=len(common),
                    false_buckets=len(false), false_runs=sum(i-1 not in false for i in false)))
    write_csv(output/"shared.csv", shared)
    for arm, total in summary.items():
        total["false_runs_per_1000_normal"] = 1000*total["false_runs"]/total["scored_normal"]
        total["shared_normal"] = sum(r["scored_normal"] for r in shared if r["arm"] == arm)
        total["shared_false_runs"] = sum(r["false_runs"] for r in shared if r["arm"] == arm)
        total["shared_false_buckets"] = sum(r["false_buckets"] for r in shared if r["arm"] == arm)
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
