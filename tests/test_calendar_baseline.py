from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import RequestV11, analyze, analyze_dataset, analyze_series, replay_policy
from anomalyzer.baseline import robust_expected_value
from anomalyzer.budget import RuntimeBudget
from anomalyzer.calendar_baseline import CalendarIndex
from anomalyzer.calendar_scoring import analyze_calendar
from anomalyzer.cli import main
from anomalyzer.mcp import _tool_call
from anomalyzer.trend import Trend


HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
START = datetime(2025, 1, 6, tzinfo=timezone.utc)
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def request(days=64, *, zone="UTC", start=START, step=HOUR, **policy):
    count = days * DAY // step
    return {
        "schema_version": "1.1",
        "datasets": [{
            "id": "counts", "entity": {"source": "counts"},
            "values": [20 + (i % 5) / 10 for i in range(count)],
            "timestamps": [(start + i * step).isoformat() for i in range(count)],
            "frequency": f"{step // timedelta(minutes=1)}min", "timezone": zone,
            "calendar_reference": {"profile": "local-calendar-v1", **policy},
        }],
        "config": {"trend": "none", "training_size": 48, "calibration_size": 8,
                   "scale_floor": 0.4, "max_points": 100_000},
    }


def run(document):
    target = analyze(document).dataset_results[0]
    assert target.status in ("completed", "insufficient_history"), target.error or [m.error for m in target.methods]
    return target, target.methods[0]


def at(method, index):
    return method.diagnostics["targets"][index]


def peers(method, target):
    return method.diagnostics["selections"][target["selection_id"]]["dates"]


def test_contract_and_public_entry_points(tmp_path, capsys):
    document = request(9)
    dataset = document["datasets"][0]
    config = document["config"]
    req_schema = json.loads((SCHEMAS / "request-1.1.schema.json").read_text())
    jsonschema.validate(document, req_schema)
    public = analyze_series(dataset, config)
    normalized = RequestV11.model_validate(document)
    direct = analyze_dataset(normalized.datasets[0], normalized.config, normalized.context)
    assert direct.methods[0].diagnostics == public.dataset_results[0].methods[0].diagnostics
    assert replay_policy(public, {}).input_fingerprint == public.input_fingerprint
    input_path = tmp_path / "request.json"
    input_path.write_text(json.dumps(document))
    assert main(["analyze", str(input_path), "--format", "json"]) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _tool_call("analyze_request", {"request": document})["structuredContent"]
    assert cli["input_fingerprint"] == mcp["input_fingerprint"] == public.input_fingerprint
    assert cli["dataset_results"][0]["methods"][0]["diagnostics"] == mcp["dataset_results"][0]["methods"][0]["diagnostics"]
    jsonschema.validate(cli, json.loads((SCHEMAS / "result-1.1.schema.json").read_text()))
    del config["trend"]
    with pytest.raises(ValidationError, match="explicit trend"):
        analyze(document)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, req_schema)
    config.update(trend="none", season_length=1)
    with pytest.raises(ValidationError, match="omitting season_length"):
        analyze(document)
    config.pop("season_length")
    dataset["timezone"] = "America/Fictional"
    with pytest.raises(ValidationError, match="unknown timezone"):
        analyze(document)
    dataset.update(timezone="UTC", calendar_reference={"profile": "local-calendar-v1", "guard_minutes": 59})
    with pytest.raises(ValidationError, match="one native bucket"):
        analyze(document)


def test_stages_distinct_dates_fallback_and_endpoint():
    document = request(46, guard_minutes=60)
    document["config"]["outlier_handling"] = "include"
    _, method = run(document)
    assert at(method, 71)["reason"] == "segment_younger_than_three_days"
    assert at(method, 72)["age_tier"] == "same_day_type"
    assert at(method, 72)["reason"] == "unsupported_calendar_reference"
    early_weekend = at(method, 12 * 24 + 8)
    assert early_weekend["reason"] == "unsupported_calendar_reference"
    developing = at(method, 14 * 24 + 8)
    assert [row["tier"] for row in developing["attempts"]] == ["developing_same_weekday", "same_day_type"]
    assert developing["fallback_used"] and developing["tier"] == "same_day_type"
    assert method.diagnostics["selections"][developing["selection_id"]]["distinct_weeks"] == 2
    mature = at(method, 42 * 24 + 8)
    assert mature["tier"] == mature["age_tier"] == "mature_same_weekday"
    assert [peer["local_date"] for peer in peers(method, mature)] == [
        "2025-01-20", "2025-01-27", "2025-02-03", "2025-02-10"]
    assert [peer["weight"] for peer in peers(method, mature)] == [0, 0, 0, 1]
    document["datasets"][0]["calendar_reference"]["fallback"] = "none"
    _, exclusive = run(document)
    assert at(exclusive, developing["index"])["reason"] == "unsupported_calendar_reference"
    assert len(at(exclusive, developing["index"])["attempts"]) == 1

    instants = [START + i * HOUR for i in range(12 * 24)]
    grid = CalendarIndex(instants, "UTC", HOUR, lambda: None)
    dataset = RequestV11.model_validate(request(12)).datasets[0]
    selection = grid.select(11 * 24 + 8, 0, dataset.calendar_reference,
                            lambda index: (float(index), None, None, False), lambda: None)
    guarded = instants[11 * 24 + 8] - DAY
    assert max(instants[i] + HOUR for p in selection.peers for i in p.indexes) < guarded
    # At width zero, the equal endpoint is supported. One minute more rejects it.
    selected_index = 11 * 24 + 8
    for guard, present in ((23 * 60, True), (23 * 60 + 1, False)):
        policy = dataset.calendar_reference.model_copy(update={"guard_minutes": guard})
        answer = grid.select(selected_index, 0, policy, lambda i: (float(i), None, None, False),
                             lambda: None, widths=0)
        assert any(i == selected_index - 24 for p in answer.peers for i in p.indexes) is present


def test_calibration_is_keyed_frozen_and_chronological():
    _, method = run(request(65))
    evidence = {row["index"]: row for row in method.evidence}
    mature_monday = at(method, 42 * 24 + 8)
    assert mature_monday["reason"] == "uncalibrated_calendar_key"
    assert not evidence[mature_monday["index"]]["triggers"]
    key = mature_monday["calibration_key"]
    rows = [row for row in method.diagnostics["targets"] if row.get("calibration_key") == key]
    calibration = method.diagnostics["calibrations"][key]["frozen"]
    assert calibration["target_date_count"] == calibration["target_week_count"] == 3
    eligible = [evidence[row["index"]]["residual"] for row in rows
                if row["index"] < calibration["effective_from_index"]
                and row["index"] not in calibration["excluded_residual_indexes"]]
    assert calibration["center"] == statistics.mean(eligible)
    assert calibration["raw_scale"] == statistics.stdev(eligible)
    first = next(row for row in rows if row["maturity"] == "calibrated")
    assert first["index"] == calibration["effective_from_index"]
    assert evidence[first["index"]]["standardized_residual"] == pytest.approx(
        (evidence[first["index"]]["residual"] - calibration["center"]) / calibration["scale"])
    assert method.diagnostics["detection_readiness"]["calendar_support"][
        "fixed_lag_repeatability"] == "not applicable to calendar selector"
    readiness = method.diagnostics["detection_readiness"]
    records = method.diagnostics["calibrations"].values()
    assessed = sum(bool(row["frozen"]) and
                   row["frozen"]["detection_readiness"]["status"] != "not_assessed"
                   for row in records)
    assert readiness["assessed_calibration_keys"] == assessed
    assert readiness["unassessed_calibration_keys"] == len(method.diagnostics["calibrations"]) - assessed
    assert "assessed_segments" not in readiness and "unassessed_segments" not in readiness
    assert any("calibration key(s) lacked" in reason for reason in readiness["reasons"])


def test_prefix_with_future_reset_arrival_revision_and_sparse_provenance():
    document = request(39, guard_minutes=60)
    dataset = document["datasets"][0]
    limit = 29 * 24
    delayed, revised = 12 * 24, 22 * 24
    dataset["available_at"] = [None] * len(dataset["values"])
    dataset["available_at"][delayed] = dataset["timestamps"][limit + 2]
    short = {**document, "context": {"as_of": dataset["timestamps"][limit - 1]}}
    _, prefix = run(short)
    dataset["revisions"] = [{"timestamp": dataset["timestamps"][revised], "value": 0,
                              "available_at": dataset["timestamps"][limit + 1], "revision_id": "late-fix"}]
    document["config"]["reset_points"] = [dataset["timestamps"][limit + 24]]
    _, full = run(document)
    assert full.diagnostics["targets"][:limit] == prefix.diagnostics["targets"]
    assert [row for row in full.evidence if row["index"] < limit] == prefix.evidence
    assert at(full, delayed)["reason"] == "not_available_at_target_start"
    assert any(any(index == revised and version[1] == "late-fix"
                   for index, version in peer["historical_versions"].items())
               for target in full.diagnostics["targets"][limit:limit + 24] if target.get("selection_id")
               for peer in peers(full, target))
    assert full.diagnostics["scoring_sample_overrides"][revised]["revision_id"] is None
    reset = at(full, limit + 24)
    assert reset["segment_start_index"] == limit + 24 and reset["reason"] == "segment_younger_than_three_days"


@pytest.mark.parametrize("gap_policy", ["same_phase", "restart"])
def test_missing_incomplete_and_authorized_zero(gap_policy):
    document = request(37)
    dataset = document["datasets"][0]
    size = len(dataset["values"])
    dataset["coverage"] = ["complete"] * size
    dataset["data_policy"] = {"reference_gaps": gap_policy, "measurement": "additive_volume",
                              "missing": "zero_for_empty"}
    first_missing = 31 * 24 + 8
    dataset["values"][first_missing-1:first_missing+2] = [None, None, 1.0]
    dataset["coverage"][first_missing-1:first_missing+2] = ["empty", "unknown", "incomplete"]
    result, method = run(document)
    assert result.data_quality["samples"][first_missing-1]["value"] == 0
    assert at(method, first_missing)["reason"] == "collection_unknown"
    assert at(method, first_missing+1)["reason"] == "period_incomplete"
    assert at(method, first_missing+1)["observed"] == 1
    after = at(method, first_missing+2)
    if gap_policy == "restart":
        assert after["segment_start_index"] == first_missing+2
        assert after["reason"] == "segment_younger_than_three_days"
    else:
        assert after["segment_start_index"] == 0
        assert after.get("selection_id")
    assert all(first_missing not in row["triggering_samples"] for row in result.anomaly_patterns)


def test_dst_transition_nondividing_cadence_and_midnight():
    spring = datetime(2025, 3, 9, 9, 58, tzinfo=timezone.utc)
    grid = CalendarIndex([spring + i * timedelta(minutes=7) for i in range(400)],
                         "America/Los_Angeles", timedelta(minutes=7), lambda: None)
    assert grid.dst[0] == "bucket_crosses_offset_transition"
    assert grid.slots(spring.date(), timedelta(hours=3), 10)[1] == "nonexistent_local_time"
    fall = datetime(2025, 11, 2, 8, tzinfo=timezone.utc)
    grid = CalendarIndex([fall + i * HOUR for i in range(24)], "America/Los_Angeles", HOUR, lambda: None)
    assert grid.dst[:2] == ["ambiguous_target_time", "ambiguous_target_time"]
    assert [row.fold for row in grid.locals[:2]] == [0, 1]
    assert grid.slots(fall.date(), HOUR, 10)[1] == "ambiguous_local_time"
    document = request(52, zone="Asia/Kathmandu", step=timedelta(minutes=37))
    _, method = run(document)
    target = next(row for row in method.diagnostics["targets"]
                  if row.get("tier") == "developing_same_weekday" and "T00:0" in row["local_timestamp"])
    date_record = peers(method, target)[0]
    local_labels = [at(method, i)["local_timestamp"] for i in date_record["peer_indexes"]]
    assert all(label.startswith(date_record["local_date"]) and label.endswith("+05:45")
               for label in local_labels)
    assert any("T23:" in label for label in local_labels)
    assert any("T00:" in label for label in local_labels)


def test_wall_clock_matches_after_dst_and_repeated_targets_abstain():
    start = datetime(2025, 9, 15, tzinfo=timezone.utc)
    document = request(65, zone="America/Los_Angeles", start=start)
    _, method = run(document)
    targets = method.diagnostics["targets"]
    selected = next(row for row in targets if row["local_timestamp"].startswith("2025-11-03T08:00"))
    assert selected["tier"] == "mature_same_weekday"
    peer_labels = [at(method, i)["local_timestamp"] for peer in peers(method, selected) for i in peer["peer_indexes"]]
    assert len(peer_labels) == 4 and all("T08:00:00-07:00" in label for label in peer_labels)
    repeated = [row for row in targets if row["local_timestamp"].startswith("2025-11-02T01:00")]
    assert {(row["fold"], row["dst_exclusion"]) for row in repeated} == {
        (0, "ambiguous_target_time"), (1, "ambiguous_target_time")}
    assert all(row["maturity"] == "unavailable" and "selection_id" not in row for row in repeated)
    document["datasets"][0]["timestamps"][repeated[0]["index"]] = "2025-11-02T01:00:00"
    failed = analyze(document)
    assert "ambiguous or nonexistent local timestamp" in failed.dataset_results[0].error


def test_guard_delays_admission_of_a_sustained_departure():
    document = request(73)
    document["config"]["outlier_handling"] = "include"
    dataset = document["datasets"][0]
    dataset["values"] = [20.0] * len(dataset["values"])
    start = 59 * 24 + 8
    dataset["values"][start:start + 9 * 24] = [26.0] * (9 * 24)
    _, method = run(document)
    evidence = {row["index"]: row for row in method.evidence}
    assert evidence[start]["expected"] == 20
    assert evidence[start + 24]["expected"] == 20
    echo = start + 7 * 24
    assert evidence[echo]["expected"] == 26
    assert start in peers(method, at(method, echo))[-1]["peer_indexes"]


def test_mcp_finding_exposes_selection_and_historical_cutoff():
    document = request(70)
    document["datasets"][0]["values"][-1] = 200
    summary = _tool_call("analyze", {"request": document})["structuredContent"]
    findings = _tool_call("list_findings", {"run_id": summary["run_id"], "limit": 100})["structuredContent"]
    episode = next(row for row in findings["findings"] if row["kind"] == "episode")
    evidence = _tool_call("get_evidence", {"run_id": summary["run_id"],
                                          "finding_id": episode["id"]})["structuredContent"]
    detail = evidence["calendar_evidence"][0]
    assert all(len(peer["peer_indexes"]) == len(peer["peer_times"]) for peer in detail["selection"]["dates"])
    assert detail["calibration"]["frozen"]["cutoff"] < detail["target"]["timestamp"]


def test_fixed_lag_reducer_preserves_arithmetic():
    values = [2e10 * math.sin(i) for i in range(80)]
    for index in range(20, 80):
        candidates = sorted((values[index - age * 5], 1.0 + 0.5 * (4 - age) / 3)
                            for age in (4, 3, 2, 1))[1:-1]
        original = sum(v * w for v, w in candidates) / sum(w for _, w in candidates)
        assert robust_expected_value(values, index, 5, 0, Trend(), 4) == original


def test_resource_failure_is_visible():
    document = request(12)
    document["config"]["max_points"] = 500
    document["datasets"][0]["data_policy"] = {"grid_end": (START + 40 * DAY).isoformat()}
    failure = analyze(document)
    assert failure.status == "failed" and "max_points" in failure.dataset_results[0].error
    normalized = RequestV11.model_validate(request(4))
    with pytest.raises(TimeoutError, match="runtime budget"):
        analyze_calendar(normalized.datasets[0], normalized.config, {}, RuntimeBudget(0))


def test_calibrated_fallback_keeps_broader_key_and_learns_preferred_key():
    document = request(65, calibrated_fallback=True, expected_range_coverage=0.95)
    _, method = run(document)
    target = at(method, 42 * 24 + 8)
    assert target["maturity"] == "calibrated"
    assert target["tier"] != target["age_tier"]
    assert target["fallback_reason"] == "preferred_tier_not_calibrated"
    assert target["expected_range"]["status"] == "available"
    assert target["expected_range"]["effective_from_index"] <= target["index"]
    key = target["calibration_key"]
    assert method.diagnostics["calibrations"][key]["tier"] == target["tier"]
    later = at(method, 64 * 24 + 8)
    assert later["tier"] == later["age_tier"]
    assert later["calibration_key"] != key
    assert any(42*24 <= i <= later["index"] for i in method.diagnostics["pattern_boundaries"])
    prefix = {**document, "context": {"as_of": document["datasets"][0]["timestamps"][43*24-1]}}
    _, early = run(prefix)
    assert method.diagnostics["targets"][:43*24] == early.diagnostics["targets"]
    assert [e for e in method.evidence if e["index"] < 43*24] == early.evidence


def test_expected_ranges_do_not_change_point_or_pattern_evidence():
    document = request(45)
    reference_result, reference = run(document)
    document["datasets"][0]["calendar_reference"]["expected_range_coverage"] = 0.95
    ranged_result, ranged = run(document)
    assert reference.evidence == ranged.evidence
    assert reference_result.anomaly_patterns == ranged_result.anomaly_patterns
    assert reference_result.observations == ranged_result.observations
    available = [t for t in ranged.diagnostics["targets"] if t.get("expected_range", {}).get("status") == "available"]
    assert available
    for target in available:
        expected_range = target["expected_range"]
        record = ranged.diagnostics["calibrations"][target["calibration_key"]]["expected_range"]
        assert record["rank"] == math.ceil((record["sample_count"]+1)*0.95)
        assert expected_range["cutoff"] < target["timestamp"]
        evidence = next(e for e in ranged.evidence if e["index"] == target["index"])
        assert expected_range["lower"] <= evidence["expected"] <= expected_range["upper"]


def test_fallback_and_ranges_relearn_after_reset_and_validate_options():
    document = request(70, calibrated_fallback=True, expected_range_coverage=0.95)
    document["config"]["reset_points"] = [50*24]
    _, method = run(document)
    assert at(method, 49*24)["maturity"] == "calibrated"
    after_reset = [t for t in method.diagnostics["targets"][50*24:] if "calibration_key" in t]
    assert after_reset and all(t["calibration_key"].startswith(f"{50*24}:") for t in after_reset)
    assert after_reset[0]["maturity"] != "calibrated"
    assert after_reset[0]["expected_range"]["status"] == "insufficient_history"
    for t in after_reset:
        band = t["expected_range"]
        if band["status"] == "available":
            assert band["cutoff"] >= document["datasets"][0]["timestamps"][50*24]
    policy = document["datasets"][0]["calendar_reference"]
    policy["fallback"] = "none"
    with pytest.raises(ValidationError, match="requires broader_calendar"):
        analyze(document)
    schema = json.loads((SCHEMAS / "request-1.1.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)
    policy.update(fallback="broader_calendar", expected_range_coverage=1.0)
    with pytest.raises(ValidationError):
        analyze(document)
