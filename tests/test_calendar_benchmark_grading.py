from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

import pytest


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "examples" / "comparison"))
    return import_module("benchmark_calendar_reference")


def make_case(benchmark, incidents=(), origin=0):
    start = datetime(2025, 1, 6, tzinfo=timezone.utc)
    times = [(start + timedelta(minutes=5*i)).isoformat() for i in range(10)]
    return benchmark.Case("test", "pair", "busy", "utc-smooth", times, [1] * 10,
                          origin, 2, 3, incidents)


def test_pattern_detection_and_native_alert_openings_survive_shared_filter(benchmark):
    pts = [{"index": i, "signal_maturity": "calibrated", "triggers": ["point"] if i == 3 else []}
           for i in range(10)]
    arm = benchmark._arm(pts, [{"detection_index": 4, "triggering_samples": [1, 2, 3, 4]}], [], {})
    assert arm.alerts == {3, 4} and arm.openings == {3}
    other = benchmark.Arm(set(range(10)) - {3}, set(), set(), set(), {3: "incomplete"})
    arms = {name: arm if name == "daily" else other for name in benchmark.SCOPES["native"]}
    rows, _ = benchmark.grade(make_case(benchmark), arms, ["young"] * 10)
    shared = next(row for row in rows if row["scope"] == "shared_three" and row["arm"] == "daily"
                  and row["group"] == "all")
    assert shared["false_alert_runs"] == 1 and shared["native_false_alert_starts"] == 0
    assert shared["false_point_buckets"] == 0


def test_gaps_resets_and_partial_incidents(benchmark):
    events = (benchmark.Incident("missed", 5, 2, 1),
              benchmark.Incident("boundary", 8, 2, 1, boundary=True),
              benchmark.Incident("partial_detection", 3, 2, 1))
    arm = benchmark.Arm({0, 1, 2, 4, 6, 7}, {0, 1, 2, 4}, {0, 1, 2, 4}, {2},
                        {3: "collection_unknown", 5: "period_incomplete", 8: "dst_target_exclusion", 9: "failure"})
    rows, incidents = benchmark.grade(make_case(benchmark, events), dict.fromkeys(benchmark.SCOPES["native"], arm),
                                      ["young"] * 10)
    native = next(row for row in rows if row["scope"] == "native" and row["arm"] == "daily"
                  and row["group"] == "all")
    assert native["false_alert_runs"] == 2
    grades = {row["incident"]: row for row in incidents if row["scope"] == "native" and row["arm"] == "daily"}
    assert grades["missed"]["outcome"] == "missed" and grades["missed"]["scored_fraction"] == 0.5
    assert grades["boundary"]["outcome"] == "unassessed"
    assert grades["partial_detection"]["outcome"] == "detected"
    assert grades["partial_detection"]["delay_minutes"] == 5


def test_case_bootstrap_uses_matched_case_difference(benchmark):
    left = [dict(pair="a", false_alert_runs=4, scored_normal=100),
            dict(pair="b", false_alert_runs=10, scored_normal=1000)]
    right = [dict(pair="a", false_alert_runs=3, scored_normal=100),
             dict(pair="b", false_alert_runs=30, scored_normal=1000)]
    result = benchmark.paired_run_delta(left, right)
    assert result["case_deltas"] == pytest.approx({"a": -10, "b": 20})
    assert result["mean"] == pytest.approx(5)
    assert result["case_bootstrap_95"] == pytest.approx([-10, 20])
