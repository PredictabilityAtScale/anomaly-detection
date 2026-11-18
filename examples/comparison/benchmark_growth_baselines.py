"""Compare frozen and adaptive anomaly recipes on paired growth and shift series."""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
from random import Random
from statistics import median
from zipfile import ZipFile

from anomalyzer import __version__, analyze


PACK = Path(__file__).with_name("pack") / "comparison-cases.zip"
PACK_CASES = (
    "01_linear_trend", "02_linear_weekly", "03_compound_weekly", "04_adaptive_acceleration",
    "07_location_shift_down", "07_location_shift_up", "08_control_drop", "08_spike_robust", "09_persistent_shift",
)
RECIPES = {"frozen": "seasonal-residual-v1", "adaptive": "adaptive-seasonal-v1"}
SEEDS = (523, 787, 1303)
TRAIN, CALIBRATION, LENGTH = 42, 21, 133
WEEK = (-6, -2, 4, 7, 3, -4, -8)


@dataclass(frozen=True)
class Incident:
    id: str
    kind: str
    indices: tuple[int, ...]
    direction: str

    @property
    def onset(self):
        return self.indices[0]


@dataclass(frozen=True)
class Variant:
    name: str
    values: list[float]
    incidents: tuple[Incident, ...]


@dataclass(frozen=True)
class Background:
    cohort: str
    id: str
    growth: str
    times: list[str]
    clean: list[float]
    settings: dict
    variants: tuple[Variant, ...]


def csv_member(archive, member):
    return list(csv.DictReader(StringIO(archive.read(member).decode("utf-8-sig"))))


def pack_backgrounds(path):
    with ZipFile(path) as archive:
        manifest = {row["case_id"]: row for row in csv_member(archive, "manifest.csv")}
        for name in PACK_CASES:
            entry = manifest[name]
            rows = csv_member(archive, entry["data_file"])
            request = json.loads(archive.read(entry["request_file"]))
            dataset, = request["datasets"]
            actual = [float(row["value"]) for row in rows]
            clean = [float(row["anomaly_free_value"]) for row in rows]
            if actual != dataset["values"] or any(row["index"] != str(i) or row["score_anomaly"] != "true"
                                                  for i, row in enumerate(rows)):
                raise ValueError(f"Request and scored labels disagree for {name}")
            labels = defaultdict(list)
            for i, row in enumerate(rows):
                if row["is_anomaly"] == "true":
                    labels[row["anomaly_id"]].append(i)
                elif actual[i] != clean[i]:
                    raise ValueError(f"Unlabeled counterfactual difference for {name} at {i}")
            incidents = []
            for label, positions in labels.items():
                directions = {sign(actual[i] - clean[i]) for i in positions}
                if len(directions) != 1 or None in directions:
                    raise ValueError(f"Expected one nonzero direction for {label}")
                incidents.append(Incident(label, rows[positions[0]]["anomaly_kind"], tuple(positions), directions.pop()))
            yield Background("pack", name, name, dataset["timestamps"], clean, request["config"],
                             (Variant("pack_labels", actual, tuple(incidents)),))


def sign(value):
    return "increase" if value > 0 else "decrease" if value < 0 else None


def growth_level(profile, i):
    elapsed = max(0, i - TRAIN - CALIBRATION)
    if profile == "linear":
        return 100 + 0.45 * i
    if profile == "compound":
        return 100 * math.exp(0.0045 * i)
    if profile == "acceleration":
        return 100 + 0.36 * i + 0.017 * elapsed**2
    if profile == "deceleration":
        slowdown = elapsed + 20 * math.expm1(-elapsed / 20)
        return 100 + 0.72 * i - 0.6 * slowdown
    raise ValueError(profile)


def fresh_backgrounds():
    times = [(date(2026, 1, 5) + timedelta(days=i)).isoformat() + "T00:00:00Z" for i in range(LENGTH)]
    for index, profile in enumerate(("linear", "compound", "acceleration", "deceleration")):
        for seed in SEEDS:
            rng = Random(seed + index * 10000)
            clean, noise = [], 0.0
            for i in range(LENGTH):
                noise = 0.25 * noise + rng.gauss(0, 2.0)
                clean.append(growth_level(profile, i) + WEEK[i % 7] + noise)
            variants = []
            for kind, start, stop, size, slope in (
                ("large_permanent_rise", 79, LENGTH, 8.0, 0),
                ("small_permanent_drop", 79, LENGTH, -2.5, 0),
                ("seven_day_rise", 85, 92, 3.5, 0),
                ("slower_growth", 79, LENGTH, -0.28, 1),
            ):
                positions = tuple(range(start, stop))
                values = clean.copy()
                for i in positions:
                    values[i] += size * (i - start + 1) if slope else size
                event = Incident(kind, kind, positions, sign(size))
                variants.append(Variant(kind, values, (event,)))
            yield Background("fresh", f"{profile}-{seed}", profile, times, clean,
                             {"season_length": 7, "training_size": TRAIN, "calibration_size": CALIBRATION}, tuple(variants))


def score(background, variant, variant_values, name):
    settings = background.settings | {"recipe": RECIPES[name]}
    if name == "adaptive":
        settings["trend"] = "auto"
    request = {"datasets": [{"timestamps": background.times, "frequency": "1d", "values": variant_values}],
               "config": settings}
    result = analyze(request)
    method, = result.methods
    if result.status != "completed":
        raise RuntimeError(f"{background.id}/{variant}/{name}: {result.status}, {method.error}")
    points = {e["index"]: e for e in method.evidence if e["signal_maturity"] == "calibrated"}
    signals = defaultdict(set)
    for i, e in points.items():
        if "point" in e["triggers"]:
            signals[i].add(("point", sign(e["standardized_residual"])))
    for p in result.anomaly_patterns:
        i = p["detection_index"]
        if i in points:
            direction = p["direction"] if p["kind"] == "location_shift" else None
            signals[i].add((p["rule"], direction))
    return points, dict(signals), method.diagnostics.get("detection_readiness", {}).get("status")


def detection(event, points, signals, control):
    dates = [i for i in event.indices if any(direction == event.direction for _, direction in signals.get(i, ()))]
    additional = [i for i in dates if not any(direction == event.direction for _, direction in control.get(i, ()))]
    available = any(i in points for i in event.indices)
    row = {}
    for key, hits in (("same_direction", dates), ("additional", additional)):
        first = min(hits, default=None)
        row.update({key + "_status": "detected" if hits else "missed" if available else "unassessed",
                    key + "_delay_days": first - event.onset if hits else None,
                    key + "_rules": ";".join(sorted(rule for rule, direction in signals.get(first, ())
                                                       if direction == event.direction))})
    return row


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def counts(rows, field):
    delays = [row[field + "_delay_days"] for row in rows if row[field + "_status"] == "detected"]
    status = Counter(row[field + "_status"] for row in rows)
    return dict(detected=status["detected"], missed=status["missed"], unassessed=status["unassessed"],
                median_delay_days=median(delays) if delays else None, longest_delay_days=max(delays, default=None))


def run(pack, output):
    results, events, buckets, inputs = [], [], [], []
    for bg in (*pack_backgrounds(pack), *fresh_backgrounds()):
        tags = dict(cohort=bg.cohort, background=bg.id, growth=bg.growth)
        variants = (Variant("control", bg.clean, ()), *bg.variants)
        for variant in variants:
            labels = {i: event.id for event in variant.incidents for i in event.indices}
            inputs.extend(dict(**tags, variant=variant.name, index=i, timestamp=bg.times[i], value=v,
                               clean_value=bg.clean[i], incident=labels.get(i)) for i, v in enumerate(variant.values))
        for recipe in RECIPES:
            control = {}
            for variant in variants:
                points, signals, readiness = score(bg, variant.name, variant.values, recipe)
                if variant.name == "control":
                    control = signals
                labels = {i for event in variant.incidents for i in event.indices}
                false = sorted(signals.keys() - labels)
                results.append(dict(**tags, variant=variant.name, recipe=recipe, scored=len(points),
                    scored_normal=len(points.keys() - labels), readiness=readiness, false_buckets=len(false),
                    false_point_buckets=sum(any(rule == "point" for rule, _ in signals[i]) for i in false),
                    false_runs=sum(j == 0 or i != false[j-1] + 1 for j, i in enumerate(false))))
                for event in variant.incidents:
                    events.append(dict(**tags, variant=variant.name, recipe=recipe, incident=event.id,
                        shift=event.kind, direction=event.direction, onset=event.onset,
                        onset_date=bg.times[event.onset][:10], duration=len(event.indices),
                        **detection(event, points, signals, control)))
                for i, point in points.items():
                    buckets.append(dict(**tags, variant=variant.name, recipe=recipe, index=i, timestamp=bg.times[i],
                        expected=point["expected"], z=point["standardized_residual"],
                        alerts=";".join(sorted(rule for rule, _ in signals.get(i, ()))),
                        increase_alerts=";".join(sorted(rule for rule, direction in signals.get(i, ()) if direction == "increase")),
                        decrease_alerts=";".join(sorted(rule for rule, direction in signals.get(i, ()) if direction == "decrease"))))
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("fixtures", inputs), ("cases", results), ("incidents", events), ("buckets", buckets)):
        write_csv(output / (name + ".csv"), rows)
    summary = {"anomalyzer": __version__, "pack_sha256": sha256(pack.read_bytes()).hexdigest(), "cohorts": {}}
    for cohort in ("pack", "fresh"):
        group = {}
        for recipe in RECIPES:
            def totals(control):
                rows = [row for row in results if row["cohort"] == cohort and row["recipe"] == recipe
                        and (row["variant"] == "control") == control]
                return {key: sum(row[key] for row in rows)
                        for key in ("scored_normal", "false_buckets", "false_point_buckets", "false_runs")}
            rows = [row for row in events if row["cohort"] == cohort and row["recipe"] == recipe]
            group[recipe] = dict(controls=totals(True), outside_incidents=totals(False),
                                 same_direction=counts(rows, "same_direction"), additional=counts(rows, "additional"))
        summary["cohorts"][cohort] = group
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=PACK)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.pack, args.output), indent=2))
