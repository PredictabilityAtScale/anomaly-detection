"""Replay the pinned PostHog Logs scan against the existing five-minute fixtures."""

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
import datetime as dt
from enum import StrEnum
from hashlib import sha1
from itertools import groupby
import json
import os
from pathlib import Path
from statistics import median
import sys
import time
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

from anomalyzer import __version__
from benchmark_five_minute_counts import HOLDOUT, ORIGIN, START, SUITES, score, write_csv
from benchmark_posthog import POSTHOG_BANDS, POSTHOG_BANDS_BLOB, POSTHOG_REVISION


SCAN_PATH = "products/logs/backend/anomaly_scan.py"
SCAN_BLOB = "0ef6205b433d7de47ca6734f5d4ccdc873047dc9"
APM = "products/apm/backend/logic/anomaly_detection"
DEPENDENCY_BLOBS = {
    POSTHOG_BANDS: POSTHOG_BANDS_BLOB,
    f"{APM}/baseline.py": "470725145300061337f6b9ec750dd77f98e8502a",
    f"{APM}/config.py": "ba09ca8d40dc63ecb2f897422960a4099d197283",
    f"{APM}/constants.py": "bd052a23e0959c5b98ab9a082339afc0992f5af0",
    f"{APM}/detector.py": "dcbd4b3f3d7a674fb0b80d8a957c273cb12e6456",
    f"{APM}/issues.py": "35f3e26c61306096113d64ab71f9da4a4b8421a2",
    f"{APM}/types.py": "0bec1ffc006b68638b411f1fde5b3f489154e696",
    "products/apm/backend/logic/grid.py": "5c4ee188bd5eb78b0459fc65a2277a6fdf94883e",
    "posthog/dataclasses.py": "c61f6512720500781df66f92aadb7d42a9e804b6",
}
BUCKET = dt.timedelta(minutes=5)
DAY = dt.timedelta(days=1)
SCOPES = ("native_coverage", "shared_buckets")
ARMS = ("anomalyzer", "posthog")
LEVELS = ("bucket_flag", "alert_start")


def read_pinned(root, path, expected_blob):
    data = (root / path).read_bytes().replace(b"\r\n", b"\n")
    if sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != expected_blob:
        raise ValueError(f"{path} differs from the pinned PostHog revision {POSTHOG_REVISION}")
    return data


def load_scan(root):
    """Load the unmodified scan definitions without Django or ClickHouse imports."""
    source = read_pinned(root, SCAN_PATH, SCAN_BLOB)
    for path, digest in DEPENDENCY_BLOBS.items():
        read_pinned(root, path, digest)
    overrides = [k for k in os.environ if k.startswith(("APM_ANOMALY_", "LOGS_ANOMALY_SCAN_"))]
    if overrides:
        raise RuntimeError("Unset PostHog scan overrides to run the benchmark with native defaults")
    sys.path.insert(0, str(root.resolve()))
    import numpy as np
    from products.apm.backend.logic.anomaly_detection import bands, baseline, config, constants, detector, issues, types

    # Use the exact bodies of run_scan and its pure helpers. The only substituted
    # service is fetch_bucket_counts, supplied by the fixture reader below.
    module = ModuleType("_pinned_posthog_scan")
    sys.modules[module.__name__] = module
    scope = vars(module)
    # Each run supplies a retention limit from the fixture's known history.
    scope.update(dt=dt, os=os, time=time, np=np, dataclass=dataclass, field=field, replace=replace,
                 StrEnum=StrEnum, ZoneInfo=ZoneInfo, Team=SimpleNamespace, DEFAULT_LOGS_RETENTION_DAYS=None)
    imports = {
        constants: ("BUCKET_MINUTES", "BUCKETS_PER_DAY", "BUCKETS_PER_WEEK"),
        types: ("BaselineStage", "BucketVerdict", "Direction", "SeriesHistory", "SeriesKey", "TrafficTier", "VerdictType"),
        config: ("DetectionConfig",),
        bands: ("NegativeBinomialBandModel",),
        baseline: ("TimeGrid", "candidate_slice_pad_buckets"),
        detector: ("evaluate_series_bucket_detail",),
        issues: ("IssueAction", "IssueFingerprint", "IssueSnapshot", "IssueState", "evaluate_issue_transition",
                 "fingerprint_for", "required_consecutive"),
    }
    for origin, names in imports.items():
        scope.update((name, getattr(origin, name)) for name in names)
    definitions = {
        "ScanBudgetExceeded", "ScanFetchTruncated", "BindingConstraint", "SeriesLimit", "TimeRange", "ScanAttempt",
        "ScanBucket", "ScanSeries", "ScanIssue", "ScanResult", "floor_to_bucket", "merge_ranges", "baseline_slice_ranges",
        "degradation_ladder", "_jit_config", "_IssueAccumulator", "_series_limit", "_replay", "run_scan",
    }
    assignments = {"BUCKET", "SCAN_LOOKBACK_WEEKS", "SCAN_MAX_EXECUTION_SECONDS"}
    tree = ast.parse(source, filename=SCAN_PATH)
    body = [node for node in tree.body if getattr(node, "name", None) in definitions
            or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in assignments for t in node.targets)]
    exec(compile(ast.Module(body=body, type_ignores=[]), SCAN_PATH, "exec"), scope)
    if module.BUCKET != BUCKET:
        raise RuntimeError("Expected the native scan to use a five-minute grid")
    return module, detector._trailing_rate


def unscored_reason(history, index, config, result, trailing_rate):
    if result.stage is not None:
        return "insufficient_comparable_history"
    first = history.first_active_index
    if first is None or index < first:
        return "no_activity_yet"
    if index - first < config.persistence_window_buckets:
        return "too_young"
    if result.observed == 0:
        last = history.last_active_index(index)
        if last is None or index - last > min(config.expiry_buckets, config.persistence_recent_buckets):
            return "not_recently_active_for_silence"
    if trailing_rate(history, index, config) < config.traffic_floor_per_bucket:
        return "below_traffic_floor"
    raise AssertionError("Unevaluated native bucket without an identified gate")


def scan_fixture(scan, trailing_rate, fixture):
    eval_detail = scan.evaluate_series_bucket_detail
    transition = scan.evaluate_issue_transition
    observations, action_rows, opened = {}, [], set()
    current_time = None

    def trace_bucket(history, index, key, grid, config, band_model):
        nonlocal current_time
        current_time = history.bucket_time(index)
        result = eval_detail(history, index, key, grid, config, band_model)
        if result.band is None:
            i = (current_time - START) // BUCKET
            observations[i] = (None, unscored_reason(history, index, config, result, trailing_rate))
        return result

    def trace_issue(snapshot, verdict_type, index, required, config):
        outcome = transition(snapshot, verdict_type, index, required, config)
        if outcome.action in (scan.IssueAction.OPEN, scan.IssueAction.REOPEN):
            i = (current_time - START) // BUCKET
            opened.add(i)
            action_rows.append(dict(index=i, timestamp=current_time.isoformat(), action=outcome.action.value,
                                    verdict=verdict_type.value, required_buckets=required))
        return outcome

    scan.evaluate_series_bucket_detail = trace_bucket
    scan.evaluate_issue_transition = trace_issue
    try:
        for known, rows in groupby(enumerate(fixture.values), key=lambda row: row[1] is not None):
            span = list(rows)
            start, end = span[0][0], span[-1][0]+1
            if end <= ORIGIN:
                continue
            first = max(start, ORIGIN)
            if not known:
                observations.update((i, (None, "unknown_collection")) for i in range(first, end))
                continue
            # A native omitted row means an observed zero. Preserve unknowns by
            # restarting after each gap with history from the new known span only.
            counts = {START + i*BUCKET: value for i, value in span if value != 0}
            eval_start, eval_end = START + first*BUCKET, START + end*BUCKET
            team = SimpleNamespace(timezone="UTC", logs_settings={"retention_days": (end-start)*BUCKET / DAY})

            def fetch_counts(_team, _name, ranges, *, max_execution_seconds):
                selected = {ts: value for ts, value in counts.items() if any(r.start <= ts < r.end for r in ranges)}
                return {"info": selected} if selected else {}

            scan.fetch_bucket_counts = fetch_counts
            result = scan.run_scan(team, fixture.name, eval_start, eval_end, now=eval_end)
            if result.degraded or result.eval_clipped or result.eval_start != eval_start or result.eval_end != eval_end:
                raise RuntimeError(f"Unexpected scan window degradation for {fixture.name}")
            if not result.series:
                observations.update((i, (None, "no_activity_yet")) for i in range(first, end))
                continue
            series, = result.series
            for bucket in series.buckets:
                i = (bucket.time - START) // BUCKET
                assert bucket.observed == fixture.values[i]
                if bucket.expected is not None:
                    observations[i] = (bucket, "scored")
            for issue in result.issues:
                assert (issue.opened_at - START) // BUCKET in opened
    finally:
        scan.evaluate_series_bucket_detail = eval_detail
        scan.evaluate_issue_transition = transition
    assert observations.keys() == set(range(ORIGIN, ORIGIN + HOLDOUT))
    return observations, opened, action_rows


def case_rows(suite, fixture, reference, scan_rows, openings):
    points, patterns = reference
    anom_flags = {i for i, e in points.items() if "point" in e["triggers"]} | (patterns.keys() & points.keys())
    ph_flags = {i for i, (row, _) in scan_rows.items() if row is not None and row.verdict is not None}
    anom_starts = {i for i in anom_flags if i-1 not in anom_flags}
    scored = {"anomalyzer": set(points), "posthog": {i for i, (_, reason) in scan_rows.items() if reason == "scored"}}
    flags = dict(anomalyzer={"bucket_flag": anom_flags, "alert_start": anom_starts},
                 posthog={"bucket_flag": ph_flags, "alert_start": openings})
    common = scored["anomalyzer"] & scored["posthog"]
    truth = {i: e.kind for e in fixture.incidents for i in range(e.start, e.stop)}
    tag = dict(suite=suite, case=fixture.name)
    buckets = []
    for i, (native, why) in sorted(scan_rows.items()):
        source = fixture.values[i]
        buckets.append(dict(**tag, index=i, timestamp=(START+i*BUCKET).isoformat(), observed=source,
            incident=truth.get(i), anomalyzer_scored=i in points,
            anomalyzer_status="scored" if i in points else "unknown_collection" if source is None else "no_calibrated_evidence",
            posthog_status=why, expected=native.expected if native else None, lower=native.lower if native else None,
            upper=native.upper if native else None, stage=native.stage.value if native and native.stage else None,
            posthog_verdict=native.verdict.value if native and native.verdict else None,
            anomalyzer_flag=i in anom_flags if i in points else None, anomalyzer_alert_start=i in anom_starts,
            posthog_alert_start=i in openings))
    cases, incidents = [], []
    for scope in SCOPES:
        for arm in ARMS:
            eligible = scored[arm] if scope == "native_coverage" else common
            for level in LEVELS:
                alerts = flags[arm][level] & eligible
                false = alerts - truth.keys()
                cases.append(dict(**tag, scope=scope, arm=arm, level=level, scored=len(eligible),
                    unscored=HOLDOUT-len(eligible), normal_scored=len(eligible-truth.keys()), false_flags=len(false),
                    false_runs=sum(i-1 not in false for i in false)))
                for e in fixture.incidents:
                    window = set(range(e.start, e.stop))
                    first = min(window & alerts, default=None)
                    status = "detected" if first is not None else "missed" if window & eligible else "unassessed"
                    incidents.append(dict(**tag, scope=scope, arm=arm, level=level, incident=e.kind,
                        onset=e.start, stop=e.stop, onset_time=(START+e.start*BUCKET).isoformat(),
                        scored_incident_buckets=len(window & eligible), total_incident_buckets=len(window),
                        status=status, first_detection=first, delay_minutes=5*(first-e.start) if first is not None else None))
    return buckets, cases, incidents


def summarize(cases, incidents):
    delays = [e["delay_minutes"] for e in incidents if e["status"] == "detected"]
    outcomes = Counter(e["status"] for e in incidents)
    return dict(**{key: sum(row[key] for row in cases) for key in
                   ("scored", "unscored", "normal_scored", "false_flags", "false_runs")},
                **{key: outcomes[key] for key in ("detected", "missed", "unassessed")},
                median_delay_minutes=median(delays) if delays else None, longest_delay_minutes=max(delays, default=None))


def run(scan, trailing_rate, output):
    timestamps = [(START+i*BUCKET).isoformat() for i in range(ORIGIN + HOLDOUT)]
    buckets, cases, incidents, actions = [], [], [], []
    for suite, source in SUITES.items():
        for fixture in source():
            native, openings, trace = scan_fixture(scan, trailing_rate, fixture)
            traces = [dict(suite=suite, case=fixture.name, **row) for row in trace]
            actions.extend(traces)
            b, c, e = case_rows(suite, fixture, score(fixture, timestamps, None), native, openings)
            buckets.extend(b)
            cases.extend(c)
            incidents.extend(e)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("buckets", buckets), ("cases", cases), ("incidents", incidents)):
        write_csv(output / f"{name}.csv", rows)
    if actions:
        write_csv(output / "posthog_issue_events.csv", actions)
    summary = {"posthog": POSTHOG_REVISION, "anomalyzer": __version__, "results": {}, "coverage": {}}
    for suite in (*SUITES, "all"):
        results = summary["results"][suite] = {}
        summary["coverage"][suite] = {arm: dict(Counter(row[f"{arm}_status"] for row in buckets
            if suite == "all" or row["suite"] == suite)) for arm in ARMS}
        for scope in SCOPES:
            results[scope] = {}
            for level in LEVELS:
                results[scope][level] = {}
                for arm in ARMS:
                    def selected(rows):
                        return [r for r in rows if (r["scope"], r["level"], r["arm"]) == (scope, level, arm)
                                and (suite == "all" or r["suite"] == suite)]
                    results[scope][level][arm] = summarize(selected(cases), selected(incidents))
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary["results"]["all"], summary["coverage"]["all"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posthog-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    scan, trailing_rate = load_scan(args.posthog_source)
    print(json.dumps(run(scan, trailing_rate, args.output), indent=2))
