"""Export portable, labelled README cases and actual checkout baselines.

Run from any directory with the repository's Python environment. No optional
dependencies, network access, or source-fixture regeneration is required.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Compare the checkout, even when the environment contains an older wheel.
sys.path.insert(0, str(ROOT / "src"))
from anomalyzer import (  # noqa: E402
    __version__, analyze, compare_distributions, compare_seasonal_distributions,
    forecast_with_model, monitor_distributions,
)

FIELDS = ["series_id", "index", "timestamp", "value", "is_anomaly",
          "anomaly_kind", "anomaly_scope", "anomaly_id", "score_anomaly",
          "split", "anomaly_free_value", "coverage", "reported_value",
          "value_origin", "event_id", "event_sequence", "reset_before",
          "population", "weight", "available_at", "revision_id", "units", "observation_basis"]


def read(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))


def request(values, **config):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {"schema_version": "1.0", "task": "analyze", "datasets": [{
        "id": "series", "values": values, "units": "calls", "frequency": "1d",
        "timestamps": [(start + timedelta(days=i)).isoformat() for i in range(len(values))],
    }], "config": config}


def scenarios():
    """Labels are declared from construction, never copied from detector flags."""
    cases = []

    def add(chapter, slug, req, note, *, labels=None, clean=None, forecast=False,
            expected="", population_change=None):
        cases.append(dict(id=f"{chapter:02d}_{slug}", chapter=chapter, request=deepcopy(req),
                          note=note, labels=labels or {}, clean=clean or {},
                          forecast=forecast, expected=expected,
                          population_change=population_change))

    def interval(start, stop, kind="level_shift", scope="interval"):
        return {i: (kind, scope) for i in range(start, stop)}

    def points(*indexes):
        return {i: ("spike_or_drop", "point") for i in indexes}

    clean = [80 + .65*i + [0, .25, -.15, .10, -.20][i % 5] for i in range(90)]
    values = clean.copy()
    values[65] += 22
    values[78] -= 18
    add(1, "linear_trend", request(values, season_length=1, trend="linear"),
        "Ordinary linear growth; introduced changes at 65 and 78.",
        labels={"series": points(65, 78)}, clean={"series": clean}, forecast=True)
    for chapter, source, slug in ((2, "growth_up", "linear_weekly"), (3, "compound", "compound_weekly")):
        req = read(source)
        clean = req["datasets"][0]["values"].copy()
        req["datasets"][0]["values"][65] += 40
        req["datasets"][0]["values"][78] -= 35
        req["config"]["outlier_handling"] = "include"
        add(chapter, slug, req, "Include-all reference deliberately permits one-week echoes; echoes are not labelled anomalies.",
            labels={"series": points(65, 78)}, clean={"series": clean}, forecast=True)
    clean = [200 + .6*i + .015*i*i + [0, 12, -5, 9, 3, -8, -11][i % 7]
             + [0, .8, -.5, 1.2, -.7, .4, -.3, 1, -.9][i % 9] for i in range(110)]
    values = clean.copy()
    values[80] += 45
    for recipe, slug in (("seasonal-residual-v1", "frozen_acceleration"), ("adaptive-seasonal-v1", "adaptive_acceleration")):
        add(4, slug, request(values, season_length=7, training_size=35, calibration_size=14, recipe=recipe),
            "Acceleration is ordinary; only sample 80 is injected. Same values under two references.",
            labels={"series": points(80)}, clean={"series": clean}, forecast=True)
    for reset in (False, True):
        req = read("steps_reset" if reset else "steps")
        req["config"]["outlier_handling"] = "include"
        add(5, "reviewed_regimes" if reset else "unreviewed_regimes", req,
            "Known boundaries 50/100 are accepted in the reviewed variant; no future boundary is inferred.",
            labels={} if reset else {"series": interval(50, 150, "unreviewed_regime")})
    req = read("ordinary")
    req["config"].pop("season_length")
    # README inference is positional. Retain source times in the portable CSV,
    # but remove calendar metadata from the executable inference request.
    times = req["datasets"][0].pop("timestamps")
    req["datasets"][0].pop("frequency")
    add(6, "discover_weekly_season", req, "Positional lag inference; no anomaly injected. CSV times are source annotations.",
        clean={"series": req["datasets"][0]["values"]}, forecast=True)
    cases[-1]["source_times"] = times
    for direction in ("up", "down"):
        req = read(f"location_shift_{direction}")
        clean = req["datasets"][0]["values"].copy()
        amount = 2 if direction == "up" else -2
        clean[60:] = [v - amount for v in clean[60:]]
        add(7, f"location_shift_{direction}", req,
            "Shift starts at 60; score first detection/delay, not just extreme-point flags.",
            labels={"series": interval(60, 90)}, clean={"series": clean},
            expected="No point flags; first location-pattern detection at 61.")
    for policy in ("include", "robust"):
        req = read("spike")
        req["config"]["outlier_handling"] = policy
        add(8, f"spike_{policy}", req, "Only 65 is injected; sample 72 is an ordinary recovery/echo check.",
            labels={"series": points(65)}, clean={"series": read("ordinary")["datasets"][0]["values"]}, forecast=True)
    clean = [100 + [0, 10, -5, 8, 2, -12, -8][i % 7] + [.2, -.4, .6, -.3, .1][i % 5] for i in range(120)]
    values = [v + (20 if i >= 60 else 0) for i, v in enumerate(clean)]
    for reset in (False, True):
        add(9, "reviewed_shift" if reset else "persistent_shift", request(values, season_length=7,
                **({"reset_points": [60]} if reset else {})),
            "At 60 the reviewed variant accepts a new regime; reset warmup is intentionally non-triggering.",
            labels={} if reset else {"series": interval(60, 120)},
            clean={"series": values if reset else clean})
    rng = random.Random(2)
    values = [100 + rng.gauss(0, 10) for _ in range(90)]
    add(10, "weak_reference_control", request(values, season_length=7),
        "Fixed random control; no injected anomaly. No flags does not establish reference quality.",
        clean={"series": values}, forecast=True, expected="Readiness caution even with zero findings.")
    rng = random.Random(11)
    clean = [100 + 12*math.sin(2*math.pi*(i % 24)/24) + [0, 5, -3, 4, 1, -6, -4][(i//24) % 7]
             + rng.gauss(0, 1.5) for i in range(60*24+12)]
    values = clean.copy()
    values[60*24+9] += 45
    req = request(values, recipe="multi-resolution-v1", aggregate_function="sum")
    ds = req["datasets"][0]
    ds["id"], ds["frequency"] = "calls", "1h"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ds["timestamps"] = [(start + timedelta(hours=i)).isoformat() for i in range(len(values))]
    add(11, "unfinished_day_spike", req, "Final day has only 12 finalized hours; daily sum must remain incomplete.",
        labels={"calls": points(1449)}, clean={"calls": clean})
    add(12, "conversion", read("agentic/conversion"), "Only the declared conversion relationship is labelled; source volumes are controls.",
        labels={"conversion": {14: ("conversion_drop", "relationship")}})
    add(12, "lagged_response", read("agentic/lagged-response"), "Declared lag=2 and coefficient=2; last response fails to match earlier leads.",
        labels={"lead_response": {11: ("missing_response", "relationship")}})
    # Cover the remaining declared relationship kinds in chapter 12's table.
    for kind in ("difference", "normalized_residual", "joint_condition"):
        common = [100 + 20*math.sin(i) for i in range(90)]
        left = request([v + [0, .2, -.2][i % 3] for i, v in enumerate(common)],
                       season_length=1, training_size=28, calibration_size=14, trend="none")
        left["schema_version"] = "1.1"
        left["datasets"][0].update(id="observed", entity={"customer": "synthetic"})
        right = deepcopy(left["datasets"][0])
        right.update(id="reference", values=common)
        left["datasets"].append(right)
        left["datasets"][0]["values"][65] += 10
        if kind == "difference":
            relationship = dict(kind=kind, minuend="observed", subtrahend="reference", units="calls")
        elif kind == "normalized_residual":
            relationship = dict(kind=kind, observed="observed", expected="reference", scale=2, units="standardized_residual")
        else:
            relationship = dict(kind=kind, combine="all", units="condition_met", conditions=[
                dict(dataset="observed", operator="gt", threshold=125),
                dict(dataset="reference", operator="gt", threshold=110)])
            # An exact caller rule makes the compound condition useful with a
            # zero-variance historical baseline, without claiming calibration.
            relationship["rules"] = [dict(id="joint-alert", kind="acceptable_range", minimum=0, maximum=0)]
        relationship["id"] = kind
        left["relationships"] = [relationship]
        add(12, kind, left, "Only the explicitly declared relationship departure at 65 is a scoring target.",
            labels={kind: {65: ("relationship_departure", "relationship")}})
    add(13, "unit_cost_rule", read("agentic/unit-cost"), "Exact illustrative 0.13 rule; statistical history is insufficient.",
        labels={"unit_cost": {3: ("rule_violation", "relationship")}})
    add(13, "incomplete_ingestion", read("agentic/incomplete-usage"), "Usage drop is unresolved because ingestion is incomplete; exclude final time from anomaly scoring.")
    cases[-1]["unscored"] = {"usage_events": [3]}
    sparse = [
        (14, "preserve", {"series": points(17)}), (14, "zero_empty", {"series": points(17)}),
        (15, "statuses", {"series": points(12)}), (16, "quiet_volume", {"series": points(83)}),
        (17, "cost_calendar", {"series": points(430)}), (17, "cost_events", {"series": points(11)}),
        (18, "weekday_phase", {"series": points(89)}),
        (19, "pattern_gap", {"series": {**interval(7, 11), **interval(12, 19)}}),
        (20, "first_rule", {"series": {0: ("rule_violation", "point")}}),
        (21, "relationships", {"unit-cost": {11: ("unit_cost_increase", "relationship")}}),
        (22, "unfinished_daily", {}),
        (23, "identified_calls", {"call-cost": points(7, 9)}),
        (24, "identified_retry", {"call-cost": points(7, 9, 10)}),
        (24, "identified_before_correction", {"call-cost": points(7, 9)}),
        (24, "identified_corrected", {"call-cost": points(7, 9)}),
        (24, "identified_pattern_ties", {"call-cost": interval(7, 19, "residual_shift")}),
        (24, "identified_pattern_sequence", {"call-cost": interval(7, 19, "residual_shift")}),
    ]
    for chapter, name, labels in sparse:
        add(chapter, name, read(f"sparse/{name}"), f"Exact examples/sparse/{name}.json input and declared data policy.", labels=labels)
    cases[-5]["expected"] = "Reject duplicate logical event IDs; do not count a retry as another call."
    cases[-1]["expected"] = "Trusted sequence permits pattern detection; timestamp-only ties do not establish a run."
    for chapter, name, change in ((25, "numeric-shape", True), (25, "numeric-ordinary", False),
                                  (25, "numeric-monitor", True), (26, "categorical-mix", True),
                                  (26, "weighted-composition", True), (26, "weighted-reports", True),
                                  (27, "seasonal-morning", False)):
        add(chapter, name.replace("-", "_"), read(f"distributions/{name}"),
            "Population-level label: individual calls are not extreme-point ground truth. Preserve populations/weights and testing budget.",
            population_change=change)
    # Straightforward extra import/forecast controls, under their matching chapter.
    for chapter, source in ((2, "ordinary"), (2, "growth_down"), (3, "compound_down"), (8, "drop")):
        req = read(source)
        add(chapter, f"control_{source}", req, "Additional control from the existing single-series fixtures.",
            labels={"series": points(65)} if source == "drop" else {},
            clean={"series": read("ordinary")["datasets"][0]["values"] if source == "drop" else req["datasets"][0]["values"]},
            forecast=True)
    for name, value in (("flat", 100.0), ("zero", 0.0)):
        values = [value]*90
        add(1, f"control_{name}", request(values, season_length=1, trend="none"),
            "Constant negative control; zero is a genuine complete measurement.", clean={"series": values}, forecast=True)
    return sorted(cases, key=lambda c: c["id"])


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]) if rows else fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v).lower() if isinstance(v, bool) else v for k, v in row.items()})


def record(case, series, index, value, **extra):
    kind, scope = case["labels"].get(series, {}).get(index, ("", ""))
    onset = index
    if scope in ("interval", "relationship"):
        while case["labels"].get(series, {}).get(onset-1) == (kind, scope):
            onset -= 1
    clean = case["clean"].get(series, [])
    row = {key: "" for key in FIELDS}
    row.update(series_id=series, index=index, value=value, reported_value=value,
               is_anomaly=bool(kind), anomaly_kind=kind, anomaly_scope=scope,
               anomaly_id=f"{case['id']}:{series}:{kind}:{onset}" if kind else "",
               score_anomaly=value is not None, split="test" if case["forecast"] and index >= 60
               else "train" if case["forecast"] else "not_applicable",
               anomaly_free_value=clean[index] if index < len(clean) else None,
               coverage="complete" if value is not None else "unknown", reset_before=False,
               value_origin="supplied")
    row.update(extra)
    if row["coverage"] in ("unknown", "incomplete", "excluded") or row["value"] is None:
        row["score_anomaly"] = False
    if index in case.get("unscored", {}).get(series, []):
        row["score_anomaly"] = False
    return row


def time_at(dataset, index):
    times = dataset.get("timestamps")
    if not times:
        return ""
    if dataset.get("frequency") and dataset.get("data_policy", {}).get("observation_basis") != "event_index":
        frequency = dataset["frequency"]
        seconds = int(frequency[:-1]) * {"h": 3600, "d": 86400, "m": 60, "s": 1}[frequency[-1]]
        return (datetime.fromisoformat(times[0].replace("Z", "+00:00")) + timedelta(seconds=index*seconds)).isoformat()
    return times[index]


def source_rows(case, result):
    rows = []
    req = case["request"]
    targets = result.get("dataset_results", [])
    for ds in req["datasets"]:
        target = next((t for t in targets if t["dataset_id"] == ds["id"] and t.get("resolution") != "completed_period"), None)
        quality = (target or result).get("data_quality", {})
        samples = quality.get("samples")
        if samples is None:
            samples = [dict(index=i, value=v, original_value=v) for i, v in enumerate(ds["values"])]
        for sample in samples:
            i = sample["index"]
            coverage = sample.get("coverage", "complete" if sample["value"] is not None else "unknown")
            raw = sample.get("original_value", sample["value"])
            value = raw if coverage == "incomplete" else sample["value"]
            row = record(case, ds["id"], i, value, timestamp=time_at(ds, i),
                         reported_value=raw, coverage=coverage,
                         value_origin="policy_zero" if raw is None and value == 0 else sample.get("origin", "supplied"),
                         event_id=sample.get("event_id", (ds.get("event_ids") or [""]*len(samples))[i]),
                         event_sequence=sample.get("event_sequence", (ds.get("event_sequence") or [""]*len(samples))[i]),
                         available_at=sample.get("available_at"), revision_id=sample.get("revision_id"))
            row.update(units=ds.get("units"), observation_basis=ds.get("data_policy", {}).get("observation_basis", "calendar"))
            resets = req.get("config", {}).get("reset_points", [])
            row["reset_before"] = i in resets or any(isinstance(r, str) and row["timestamp"].startswith(r) for r in resets)
            if "source_times" in case:
                row["timestamp"] = case["source_times"][i]
            rows.append(row)
    for target in result.get("relationship_results", []):
        if target.get("resolution") == "completed_period":
            continue
        for sample in target["lineage"]:
            rows.append(record(case, target["relationship_id"], sample["index"], sample["value"],
                               timestamp=sample["timestamp"], value_origin="declared_relationship",
                               units=target["definition"]["units"], observation_basis="declared_relationship",
                               coverage="complete" if sample["value"] is not None else "unknown"))
    return rows


def distribution_rows(case):
    req = case["request"]
    rows = []
    if req["task"] == "compare_distributions":
        for population in ("reference", "current"):
            body = req[population]
            samples = body.get("samples", [dict(id=k, value=k, weight=v) for k, v in body.get("weights", {}).items()])
            for i, sample in enumerate(samples):
                changed = population == "current" and case["population_change"]
                rows.append(record(case, "population", len(rows), sample["value"],
                    event_id=sample["id"], population=population, weight=sample.get("weight", 1),
                    score_anomaly=False, is_anomaly=changed, anomaly_scope="population" if changed else "",
                    units=req["units"], observation_basis="aggregate_category" if "weights" in body else "population_event",
                    anomaly_kind="composition_change" if changed else "",
                    anomaly_id=case["id"]+":population" if changed else ""))
    else:
        for i, sample in enumerate(req["samples"]):
            timestamp = sample.get("timestamp", "")
            if req["task"] == "monitor_distributions":
                population = "reference" if i < req["reference_size"] else "current"
                changed = i >= 160
            else:
                # Selection is performed by Anomalyzer, not by filtering these rows.
                dt = datetime.fromisoformat(timestamp)
                population = ("future_excluded" if dt > datetime.fromisoformat(req["as_of"])
                              else "current" if dt >= datetime.fromisoformat(req["window_start"]) else "history_pool")
                changed = False
            rows.append(record(case, "population", i, sample["value"], timestamp=timestamp,
                event_id=sample["id"], population=population, weight=sample.get("weight", 1),
                score_anomaly=False, is_anomaly=changed, anomaly_scope="population" if changed else "",
                units=req["units"], observation_basis="population_event",
                anomaly_kind="shape_change" if changed else "", anomaly_id=case["id"]+":population" if changed else ""))
    return rows


def baseline_rows(result):
    """Keep first detection separate from retrospective pattern membership."""
    targets = result.get("dataset_results", []) + result.get("relationship_results", [])
    if not targets:
        target_id = result["resolved_config"]["datasets"][0]["id"]
        targets = [dict(result, dataset_id=target_id)]
    rows = []
    for target in targets:
        covered = set()
        for method in target.get("methods", []):
            readiness = method.get("diagnostics", {}).get("detection_readiness", {})
            for evidence in method["evidence"]:
                i = evidence["index"]
                covered.add(i)
                patterns = [p for p in target.get("anomaly_patterns", []) if p.get("detection_index") == i]
                assessments = [a for a in target.get("assessments", []) if a["index"] == i]
                rows.append(dict(series_id=target.get("dataset_id", target.get("relationship_id")),
                    resolution=target.get("resolution") or (method["id"].split(":")[0]
                        if method["id"].startswith(("completed_period:", "intraday:")) else None),
                    method=method["id"], index=i,
                    timestamp=evidence.get("timestamp"), event_id=evidence.get("event_id"),
                    expected=evidence.get("expected"), point_flag="point" in evidence.get("triggers", []),
                    pattern_first_detection=";".join(sorted({p["rule"] for p in patterns})),
                    classifications=";".join(sorted({a["classification"] for a in assessments})),
                    signal_maturity=evidence.get("signal_maturity"), readiness=readiness.get("status"),
                    target_status=target["status"]))
        for i in sorted({a["index"] for a in target.get("assessments", [])} - covered):
            assessments = [a for a in target["assessments"] if a["index"] == i]
            rows.append(dict(series_id=target.get("dataset_id", target.get("relationship_id")),
                resolution=target.get("resolution"), method="assessment_only", index=i,
                timestamp=assessments[0].get("timestamp"), event_id=assessments[0].get("event_id"),
                expected=None, point_flag=False, pattern_first_detection="",
                classifications=";".join(sorted({a["classification"] for a in assessments})),
                signal_maturity=assessments[0]["maturity"], readiness="not_assessed", target_status=target["status"]))
    return rows


def forecast_rows(case):
    ds = case["request"]["datasets"][0]
    config = case["request"]["config"]
    values, origin = ds["values"], 60
    horizon = len(values) - origin
    candidate = dict(id="declared-anomalyzer", method="anomalyzer", period=config.get("season_length", 7),
                     trend=config.get("trend", "auto"), outlier_handling=config.get("outlier_handling", "robust"))
    predictions = {}
    for name, model in (("anomalyzer", candidate), ("naive", dict(id="naive", method="naive"))):
        result = forecast_with_model(values[:origin], model, {"horizon": horizon})
        if result.status != "completed":
            raise RuntimeError(f"{case['id']} forecast {name}: {result.reason}")
        predictions[name] = result.predicted
    return [dict(series_id=ds["id"], index=i, timestamp=time_at(ds, i) or case["source_times"][i],
                 actual=values[i], anomaly_free_value=case["clean"][ds["id"]][i],
                 anomalyzer_predicted=predictions["anomalyzer"][i-origin], naive_predicted=predictions["naive"][i-origin],
                 training_end_index=origin-1, horizon_step=i-origin+1) for i in range(origin, len(values))]


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "README.md").write_text(Path(__file__).with_name("README.md").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    chapters = {int(number): title for number, title in re.findall(r"^### (\d+)\. (.+)$", (ROOT / "README.md").read_text(encoding="utf-8"), re.M)}
    manifest, hashes, prediction_template = [], {}, []
    for case in scenarios():
        req, case_id = case["request"], case["id"]
        request_path = output / "requests" / f"{case_id}.json"
        request_path.parent.mkdir(exist_ok=True)
        request_path.write_text(json.dumps(req, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
        task = req.get("task", "analyze")
        rejected = case_id == "24_identified_retry"
        if rejected:
            try:
                analyze(req)
            except ValueError as exc:
                if "duplicate logical" not in str(exc):
                    raise
                result = {"status": "expected_rejection", "error": str(exc)}
            else:
                raise AssertionError("Duplicate logical IDs were accepted")
            rows = [record(case, ds["id"], i, v, timestamp=ds["timestamps"][i],
                           event_id=ds["event_ids"][i], score_anomaly=False)
                    for ds in req["datasets"] for i, v in enumerate(ds["values"])]
            baseline = []
        elif task == "analyze":
            result = analyze(req).model_dump(mode="json")
            if result["status"] == "failed":
                raise RuntimeError(f"{case_id}: {result.get('error')}")
            rows, baseline = source_rows(case, result), baseline_rows(result)
            write_csv(output / "baseline" / f"{case_id}.csv", baseline,
                      fields=["series_id", "resolution", "method", "index", "timestamp", "event_id", "expected",
                              "point_flag", "pattern_first_detection", "classifications", "signal_maturity", "readiness", "target_status"])
        else:
            function = {"compare_distributions": compare_distributions,
                        "monitor_distributions": monitor_distributions,
                        "compare_seasonal_distributions": compare_seasonal_distributions}[task]
            result = function(req).model_dump(mode="json")
            if result["status"] == "failed":
                raise RuntimeError(f"{case_id}: {result.get('error')}")
            rows, baseline = distribution_rows(case), []
            # These contracts contain no runtime/run UUIDs; retain selection,
            # statistical gates and repeated-testing evidence in full.
            path = output / "baseline" / f"{case_id}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
        write_csv(output / "data" / f"{case_id}.csv", rows, FIELDS)
        prediction_template.extend(dict(case_id=case_id, series_id=r["series_id"], index=r["index"],
            predicted_anomaly="", predicted_value="") for r in rows if r["score_anomaly"])
        forecast = forecast_rows(case) if case["forecast"] else []
        if forecast:
            write_csv(output / "forecasts" / f"{case_id}.csv", forecast)
        config = req.get("config", {})
        manifest.append(dict(case_id=case_id, readme_chapter=case["chapter"], readme_title=chapters[case["chapter"]], task=task,
            data_file=f"data/{case_id}.csv", request_file=f"requests/{case_id}.json",
            baseline_file=f"baseline/{case_id}.{'csv' if task == 'analyze' else 'json'}" if not rejected else "",
            forecast_file=f"forecasts/{case_id}.csv" if forecast else "",
            rows=len(rows), anomaly_rows=sum(r["is_anomaly"] for r in rows),
            scoreable_rows=sum(r["score_anomaly"] for r in rows),
            forecast_train_end_index=59 if forecast else None, forecast_horizon=len(forecast) if forecast else None,
            forecast_mae=sum(abs(r["anomalyzer_predicted"]-r["actual"]) for r in forecast)/len(forecast) if forecast else None,
            forecast_rmse=math.sqrt(sum((r["anomalyzer_predicted"]-r["actual"])**2 for r in forecast)/len(forecast)) if forecast else None,
            forecast_anomaly_free_mae=sum(abs(r["anomalyzer_predicted"]-r["anomaly_free_value"]) for r in forecast)/len(forecast) if forecast else None,
            naive_forecast_mae=sum(abs(r["naive_predicted"]-r["actual"]) for r in forecast)/len(forecast) if forecast else None,
            cadence=";".join(sorted({ds.get("frequency", "positional") for ds in req.get("datasets", [])})),
            season_length=config.get("season_length", "inferred" if task == "analyze" else ""),
            recipe=config.get("recipe", "seasonal-residual-v1" if task == "analyze" else ""),
            trend=config.get("trend", "auto" if task == "analyze" else ""),
            outlier_handling=config.get("outlier_handling", "robust" if task == "analyze" else ""),
            reset_points=json.dumps(config.get("reset_points", [])),
            expected_population_change=case["population_change"], anomalyzer_status=result["status"],
            anomalyzer_point_flags=sum(r["point_flag"] for r in baseline),
            anomalyzer_pattern_first_detections=sum(bool(r["pattern_first_detection"]) for r in baseline),
            note=case["note"], expected_behavior=case["expected"],
            anomalyzer_error=result.get("error", "")))
        print(f"{case_id}: {len(rows)} rows; {result['status']}")
    write_csv(output / "manifest.csv", manifest)
    write_csv(output / "prediction_template.csv", prediction_template)
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in ("checksums.json", "comparison-cases.zip"):
            hashes[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "checksums.json").write_text(json.dumps(dict(anomalyzer_version=__version__, sha256=hashes), indent=2)+"\n", encoding="utf-8", newline="\n")
    # Fixed ZIP timestamps make regeneration reproducible, including the archive.
    with zipfile.ZipFile(output / "comparison-cases.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.suffix != ".zip":
                info = zipfile.ZipInfo(path.relative_to(output).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "pack")
    args = parser.parse_args()
    generate(args.output)
