"""Logical event identity, honest tie semantics and deterministic consumer replay."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

from anomalyzer import analyze, analyze_series, get_case, replay_policy
from anomalyzer.contracts import RequestV11, ResultV11
from anomalyzer.mcp import handle, TOOLS
from anomalyzer.mcp_views import build_findings, get_evidence, summarize


def request(values=None, cohorts=None, trusted=False):
    values = [10, 10, 9, 10, 11, 30, 40] if values is None else values
    cohorts = [0, 0, 1, 1, 1, 2, 2] if cohorts is None else cohorts
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ds = dict(id="cost", entity={"application": "synthetic"}, units="dollars_per_call",
        timestamps=[(start+timedelta(hours=i)).isoformat() for i in cohorts], values=values,
        event_ids=[f"call-{i:04}" for i in range(len(values))],
        data_policy={"observation_basis": "event_index"},
        rules=[dict(id="cap", kind="acceptable_range", minimum=0, maximum=20),
               dict(id="jump", kind="maximum_absolute_change", threshold=5)])
    if trusted:
        ds["event_sequence"] = list(range(100, 100+len(values)))
        ds["data_policy"]["event_order"] = "trusted_sequence"
    return dict(schema_version="1.1", datasets=[ds],
                config=dict(training_size=2, calibration_size=3, trend="none", season_length=1))


def rows(result):
    return [item for method in result.dataset_results[0].methods for item in method.evidence]


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in ("run_id", "runtime_seconds", "source_index", "source_indexes")}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def test_distinct_same_time_calls_keep_values_references_and_cases():
    result = analyze(request())
    item = result.dataset_results[0]
    assert item.status == "completed"
    assert item.data_quality["event_identity_contract"] == "event-identity-v1"
    assert [s["original_value"] for s in item.data_quality["samples"]] == [10,10,9,10,11,30,40]
    assert item.data_quality["observation_count"] == 7
    points = [e for e in rows(result) if e["signal_maturity"] == "calibrated"]
    assert len(points) == 2 and {e["expected"] for e in points} == {10}
    assert all(e["training_cutoff"] < e["timestamp"] for e in points)
    assert {e["observed"] for e in points} == {30,40}
    assert len({e["id"] for e in points}) == 2
    assert len(result.cases) == 2 and len({c.id for c in result.cases}) == 2
    assert {c.event_id for c in result.cases} == {"call-0005", "call-0006"}
    assert len({c.event_time for c in result.cases}) == 1
    assert all(not c.action_eligible for c in result.cases)
    assert not item.anomaly_patterns
    assert all(len(o["triggering_samples"]) == 1 for o in item.observations)
    for case in result.cases:
        assert get_case(result, case.id) == case
        detail = get_evidence(result.model_dump(mode="json"), case.id)
        assert {s["event_id"] for s in detail["source_samples"]} == {case.event_id}


@pytest.mark.parametrize("mutation", [
    lambda d: d["event_ids"].__setitem__(1, d["event_ids"][0]),
    lambda d: d["event_ids"].pop(),
    lambda d: d["event_ids"].__setitem__(0, ""),
    lambda d: d["event_ids"].__setitem__(0, " padded "),
    lambda d: d["event_ids"].__setitem__(0, 4),
    lambda d: d["event_ids"].__setitem__(0, "x"*129),
    lambda d: d.update(frequency="1h"),
    lambda d: d["data_policy"].update(observation_basis="calendar"),
    lambda d: d.update(event_sequence=list(range(7))),
    lambda d: d["data_policy"].update(event_order="trusted_sequence"),
])
def test_invalid_identity_contract_is_rejected(mutation):
    body = request()
    mutation(body["datasets"][0])
    with pytest.raises(ValueError):
        RequestV11.model_validate(body)


def test_whole_cohorts_cannot_train_or_calibrate_one_another():
    body = request([10,10,10,9,10,11,9,10,11,40], [0,0,0,1,1,1,1,2,2,3])
    item = analyze(body).dataset_results[0]
    segment = item.methods[0].diagnostics["segments"][0]
    assert segment["training_indexes"] == [0,1,2]  # target 2 cannot split the cohort
    assert segment["calibration_indexes"] == [3,4,5,6]  # target 3 cannot split it either
    assert all(e["signal_maturity"] == "reference_only" for e in item.methods[0].evidence if e["index"] < 7)
    assert all(e["signal_maturity"] == "calibrated" for e in item.methods[0].evidence if e["index"] >= 7)
    assert len({e["calibration_samples"] for e in item.methods[0].evidence if e["timestamp"] == body["datasets"][0]["timestamps"][3]}) == 1


def test_missing_last_cohort_member_does_not_pull_next_timestamp_into_calibration():
    body = request([10,10,9,10,11,None,40], [0,0,1,1,1,1,2])
    result = analyze(body)
    assert rows(result)[-1]["signal_maturity"] == "calibrated"
    assert rows(result)[-1]["triggers"] == ["point"]


def test_unordered_ties_break_change_and_pattern_continuity_but_keep_ranges():
    body = request([10,10,9,10,11]+[40]*12+[50], [0,0,1,1,1]+[2]*12+[3])
    result = analyze(body)
    item = result.dataset_results[0]
    assert not item.anomaly_patterns
    for assessment in item.assessments:
        if assessment.id.endswith(":early") and assessment.index >= 5:
            assert assessment.absolute_change is None
            assert {v["id"] for v in assessment.baseline["violations"]} == {"cap"}
            assert assessment.baseline["unavailable_rules"] == [{"id":"jump", "reason":"no_comparable_prior"}]
    assert len(result.cases) == 13


def test_trusted_sequence_is_explicit_and_enables_order_without_changing_time():
    body = request([10,10,9,10,11]+[12]*12, [0,0,1,1,1]+[2]*12, trusted=True)
    body["config"]["point_threshold"] = 100
    result = analyze(body)
    item = result.dataset_results[0]
    assert any(p["rule"] == "nelson_rule_2" for p in item.anomaly_patterns)
    assert {s["original_timestamp"] for s in item.data_quality["samples"][5:]} == {body["datasets"][0]["timestamps"][5]}
    assert item.data_quality["event_order"] == "trusted_sequence"
    assert not item.data_quality["unordered_tie_positions"]


@pytest.mark.parametrize("sequence", [[1]*7, [False,1,2,3,4,5,6], [6,5,4,3,2,1,0]])
def test_bad_trusted_sequence_is_rejected_or_fails_visibly(sequence):
    body = request(trusted=True)
    body["datasets"][0]["event_sequence"] = sequence
    try:
        result = analyze(body)
    except ValueError:
        return
    assert result.dataset_results[0].status == "failed"
    assert "contradicts" in result.dataset_results[0].error


def test_reordering_deliveries_does_not_change_evidence_or_case_identity():
    body = request()
    original = analyze(body)
    reordered = deepcopy(body)
    ds = reordered["datasets"][0]
    for name in ("timestamps", "values", "event_ids"):
        ds[name] = list(reversed(ds[name]))
    again = analyze(reordered)
    assert rows(original) == rows(again)
    assert [c.model_dump() for c in original.cases] == [c.model_dump() for c in again.cases]
    assert [a.model_dump() for a in original.dataset_results[0].assessments] == [a.model_dump() for a in again.dataset_results[0].assessments]
    assert semantic(original.dataset_results[0].data_quality) == semantic(again.dataset_results[0].data_quality)


def test_repeat_replay_and_duplicate_delivery_do_not_create_new_logical_events():
    body = request()
    a, b = analyze(body), analyze(body)
    assert [c.model_dump() for c in a.cases] == [c.model_dump() for c in b.cases]
    replayed = replay_policy(a, {"allow_explicit_rules":True})
    assert [c.id for c in replayed.cases] == [c.id for c in a.cases]
    assert all(c.action_eligible for c in replayed.cases)
    ds = body["datasets"][0]
    for name in ("timestamps", "values", "event_ids"):
        ds[name].append(ds[name][-1])
    with pytest.raises(ValueError, match="duplicate logical"):
        analyze(body)


def test_late_same_time_event_does_not_change_an_earlier_asof_snapshot():
    body = request()
    body["context"] = {"as_of":"2026-01-01T03:00:00Z"}
    original = analyze(body)
    ds = body["datasets"][0]
    ds["available_at"] = [None]*7+["2026-01-01T04:00:00Z"]
    ds["event_ids"].append("a-new-layout-first")
    ds["values"].append(35)
    ds["timestamps"].append(ds["timestamps"][-1])
    earlier = analyze(body)
    assert rows(original) == rows(earlier)
    assert [c.model_dump() for c in original.cases] == [c.model_dump() for c in earlier.cases]
    body["context"]["as_of"] = "2026-01-01T05:00:00Z"
    later = analyze(body)
    assert len(later.cases) == 3
    old = {c.event_id:c for c in original.cases}
    for case in later.cases:
        if case.event_id in old:
            assert case.model_dump() == old[case.event_id].model_dump()
    assert {e["id"] for e in rows(original)} <= {e["id"] for e in rows(later)}


def test_prefix_extension_at_a_later_timestamp_preserves_prior_evidence():
    body = request()
    original = analyze(body)
    ds = body["datasets"][0]
    ds["event_ids"].append("call-last")
    ds["values"].append(10)
    ds["timestamps"].append("2026-01-01T03:00:00Z")
    later = analyze(body)
    assert rows(original) == rows(later)[:-1]
    assert [c.model_dump() for c in original.cases] == [c.model_dump() for c in later.cases]


def test_identified_correction_changes_only_the_addressed_event_and_case_revision():
    body = request()
    body["context"] = {"as_of":"2026-01-01T03:00:00Z"}
    original = analyze(body)
    ds = body["datasets"][0]
    ds["revisions"] = [dict(event_id="call-0005", timestamp=ds["timestamps"][5], value=35,
        available_at="2026-01-01T04:00:00Z", revision_id="corrected-a")]
    earlier = analyze(body)
    assert [c.model_dump() for c in original.cases] == [c.model_dump() for c in earlier.cases]
    body["context"]["as_of"] = "2026-01-01T05:00:00Z"
    later = analyze(body)
    a = next(c for c in original.cases if c.event_id == "call-0005")
    b = next(c for c in later.cases if c.event_id == "call-0005")
    assert a.id == b.id and a.revision_id != b.revision_id
    sample = later.dataset_results[0].data_quality["samples"][5]
    assert sample["initial_value"] == 30 and sample["original_value"] == 35
    assert sample["revision_id"] == "corrected-a"
    assert later.dataset_results[0].data_quality["observation_count"] == 7
    assert next(c for c in later.cases if c.event_id == "call-0006").model_dump() == next(c for c in original.cases if c.event_id == "call-0006").model_dump()


@pytest.mark.parametrize("override,reason", [
    ({"event_id":None}, "require event_id"),
    ({"event_id":"unknown"}, "existing logical"),
    ({"timestamp":"2026-01-01T01:00:00Z"}, "original event timestamp"),
    ({"available_at":"2026-01-01T02:00:00Z"}, "strictly after"),
])
def test_ambiguous_corrections_are_rejected(override, reason):
    body = request()
    ds = body["datasets"][0]
    ds["revisions"] = [{**dict(event_id="call-0005", timestamp=ds["timestamps"][5], value=35,
                    available_at="2026-01-01T04:00:00Z", revision_id="r"), **override}]
    try:
        result = analyze(body)
    except ValueError as exc:
        assert reason in str(exc)
        return
    assert result.dataset_results[0].status == "failed" and reason in result.dataset_results[0].error


def test_reset_starts_whole_timestamp_cohort_and_cannot_split_it():
    body = request()
    body["config"]["reset_points"] = [body["datasets"][0]["timestamps"][2]]
    item = analyze(body).dataset_results[0]
    assert item.status != "failed" and item.data_quality["event_reset_positions"] == [2]
    body["config"]["reset_points"] = [3]
    item = analyze(body).dataset_results[0]
    assert item.status == "failed" and "cannot split" in item.error


def test_pointwise_relationships_align_logical_events_and_expose_source_ids():
    body = request()
    other = deepcopy(body["datasets"][0])
    other.update(id="quantity", units="calls", values=[1]*7, rules=[])
    body["datasets"].append(other)
    body["relationships"] = [dict(id="unit-cost", kind="ratio", numerator="cost", denominator="quantity", units="dollars_per_call")]
    result = analyze(body)
    relationship = result.relationship_results[0]
    assert relationship.status == "completed"
    assert relationship.lineage[-1].source_event_ids == {"cost":"call-0006", "quantity":"call-0006"}
    assert relationship.assessments[-1].event_id == "call-0006"
    other["event_ids"][-1] = "different-call"
    failed = analyze(body).relationship_results[0]
    assert failed.status == "failed" and "matching logical event IDs" in failed.error


def test_python_schema_cli_and_mcp_retain_identity_contract():
    body = request()
    direct = analyze(body).model_dump(mode="json")
    assert semantic(analyze_series(body["datasets"][0], body["config"]).model_dump(mode="json")) == semantic(direct)
    root = Path(__file__).parents[1]
    jsonschema.validate(body, json.loads((root/"schemas/request-1.1.schema.json").read_text()))
    jsonschema.validate(direct, json.loads((root/"schemas/result-1.1.schema.json").read_text()))
    jsonschema.validate({"request":body}, TOOLS[0]["inputSchema"])
    cli = subprocess.run([sys.executable,"-m","anomalyzer","analyze","-","--input-format","json","--format","json"],
        input=json.dumps(body), text=True, capture_output=True, timeout=30)
    assert cli.returncode == 0, cli.stderr
    assert semantic(json.loads(cli.stdout)) == semantic(direct)
    def call(name, **arguments):
        result = handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name=name, arguments=arguments)))["result"]
        assert not result["isError"]
        return result["structuredContent"]
    compact = call("analyze", request=body)
    assert compact["data_quality"][0]["event_identity_contract"] == "event-identity-v1"
    findings = call("list_findings", run_id=compact["run_id"], limit=10)
    cases = [f for f in findings["findings"] if f["kind"] == "case"]
    assert len(cases) == 2
    for case in cases:
        detail = call("get_evidence", run_id=compact["run_id"], finding_id=case["id"])
        assert {s["event_id"] for s in detail["source_samples"]} == {case["event_id"]}
    bad = deepcopy(body)
    bad["datasets"][0]["event_ids"][1] = bad["datasets"][0]["event_ids"][0]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, TOOLS[0]["inputSchema"])


def test_tied_event_results_and_mcp_views_remain_bounded():
    sizes = []
    for count in (192,384):
        values = [10+(i%3-1)*.1 for i in range(count)]
        values[-1] = 40
        body = request(values, [i//3 for i in range(count)])
        body["config"].update(training_size=12,calibration_size=12)
        result = analyze(body)
        assert result.status == "completed"
        sizes.append(len(result.model_dump_json().encode()))
        compact = summarize(result.model_dump(mode="json"))
        assert len(json.dumps(compact).encode()) < 15_000
        assert len(result.dataset_results[0].data_quality["samples"]) == count
        assert len({r["id"] for r in rows(result)}) == len(rows(result))
    assert sizes[-1] < 2_000_000 and sizes[-1] < 2.3*sizes[0]


def test_revision_order_is_deterministic_and_duplicate_revision_delivery_is_rejected():
    body = request()
    ds = body["datasets"][0]
    ds["revisions"] = [dict(event_id="call-0005", timestamp=ds["timestamps"][5], value=value,
        available_at=f"2026-01-01T0{hour}:00:00Z", revision_id=f"r{hour}") for hour,value in ((4,35),(5,36))]
    original = analyze(body)
    ds["revisions"].reverse()
    reordered = analyze(body)
    assert rows(original) == rows(reordered)
    assert [c.model_dump() for c in original.cases] == [c.model_dump() for c in reordered.cases]
    ds["revisions"].append(deepcopy(ds["revisions"][0]))
    failed = analyze(body).dataset_results[0]
    assert failed.status == "failed" and "duplicate event revision" in failed.error


def test_trusted_same_time_prefix_and_shared_point_budget():
    body = request(trusted=True)
    original = analyze(body)
    ds = body["datasets"][0]
    ds["values"].append(50)
    ds["timestamps"].append(ds["timestamps"][-1])
    ds["event_ids"].append("trusted-next-call")
    ds["event_sequence"].append(ds["event_sequence"][-1]+1)
    assert rows(analyze(body))[:-1] == rows(original)
    body["config"]["max_points"] = 7
    with pytest.raises(ValueError, match="max_points"):
        analyze(body)


def test_identified_lag_does_not_invent_an_order_and_lineage_keeps_original_time():
    body = request()
    body["datasets"][0]["timestamps"][0] = "2026-01-01T01:00:00+01:00"
    other = deepcopy(body["datasets"][0])
    other.update(id="predictor",rules=[])
    body["datasets"].append(other)
    body["relationships"] = [dict(id="lag",kind="lagged_response",response="cost",predictor="predictor",lag=1,coefficient=1,units="dollars_per_call")]
    result = analyze(body)
    assert result.dataset_results[0].data_quality["samples"][0]["original_timestamp"] == "2026-01-01T01:00:00+01:00"
    assert result.relationship_results[0].status == "failed"
    assert "cannot order tied events" in result.relationship_results[0].error


def test_corrected_reference_revises_supported_event_without_changing_its_identity():
    body = request()
    original = analyze(body)
    ds = body["datasets"][0]
    ds["revisions"] = [dict(event_id="call-0002",timestamp=ds["timestamps"][2],value=8,
        available_at="2026-01-01T04:00:00Z",revision_id="recalibration")]
    corrected = analyze(body)
    a, b = original.cases[0], corrected.cases[0]
    assert a.id == b.id and a.revision_id != b.revision_id
    points = [a for a in corrected.dataset_results[0].assessments if a.basis == "statistical_baseline"]
    assert all(a.baseline["known_input_availability_cutoff"] == "2026-01-01T04:00:00+00:00" for a in points)


def test_entity_scope_separates_case_and_evidence_identity():
    body = request()
    customer = analyze(body)
    body["datasets"][0]["entity"] = {"customer":"synthetic"}
    application = analyze(body)
    assert {c.id for c in customer.cases}.isdisjoint(c.id for c in application.cases)
    assert {e["id"] for e in rows(customer)}.isdisjoint(e["id"] for e in rows(application))
