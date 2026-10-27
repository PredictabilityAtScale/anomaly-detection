"""Sparse source semantics, causal replay, bounded preparation and public interfaces."""
import copy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

import pytest

from anomalyzer import analyze, analyze_series, analyze_relationships, get_case, replay_policy
from anomalyzer.contracts import DataPolicy, DatasetV11, Request, RequestV11, ResultV11
from anomalyzer.mcp import handle


def body(values=None, **dataset):
    values = [10, 11, 9, 10, 9, 10, 11, 10, None, 10, 11, 9, 10, 30] if values is None else values
    times = [(datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(hours=i)).isoformat() for i in range(len(values))]
    return {"schema_version": "1.1", "datasets": [{"id": "series", "entity": {"customer": "test"},
        "timestamps": times, "values": values, "frequency": "1h", **dataset}],
        "config": {"season_length": 1, "training_size": 4, "calibration_size": 3, "trend": "none"}}


def source(request):
    return analyze(request).dataset_results[0]


def evidence(item):
    return [row for method in item.methods for row in method.evidence]


def test_omitted_positions_equal_explicit_null_without_compressing_time():
    explicit = body()
    omitted = copy.deepcopy(explicit)
    del omitted["datasets"][0]["timestamps"][8]
    del omitted["datasets"][0]["values"][8]
    left, right = source(explicit), source(omitted)
    assert evidence(left) == evidence(right)
    assert left.data_quality["grid_count"] == right.data_quality["grid_count"] == 14
    assert left.data_quality["observation_count"] == right.data_quality["observation_count"] == 13
    assert left.data_quality["zero_filled_count"] == right.data_quality["zero_filled_count"] == 0
    assert right.data_quality["samples"][8]["source_index"] == -1
    assert not any(row["index"] == 8 for row in evidence(right))


def test_zero_is_only_authorized_for_complete_empty_additive_volume():
    request = body([2, None, None, 0, 9], data_policy={"missing": "zero_for_empty", "measurement": "additive_volume"},
                   coverage=["complete", "empty", "unknown", "complete", "incomplete"])
    result = source(request)
    rows = result.data_quality["samples"]
    assert [r["value"] for r in rows] == [2, 0, None, 0, None]
    assert [r["original_value"] for r in rows] == [2, None, None, 0, 9]
    assert rows[1]["reason"] == "confirmed_empty_additive_volume"
    assert rows[3]["reason"] is None
    assert result.data_quality["zero_filled_count"] == 1
    assert result.data_quality["latest_evidence_state"] == "insufficient_evidence"


def test_global_collection_contract_authorizes_omitted_slots_but_not_explicit_unknown():
    request = body([1, None, 2], data_policy={"missing": "zero_for_empty", "measurement": "additive_volume", "absence_means_zero": True})
    request["datasets"][0]["timestamps"][2] = "2026-01-01T03:00:00Z"
    assert [r["value"] for r in source(request).data_quality["samples"]] == [1, 0, 0, 2]
    request["datasets"][0]["coverage"] = ["complete", "unknown", "complete"]
    assert [r["value"] for r in source(request).data_quality["samples"]] == [1, None, 0, 2]


@pytest.mark.parametrize("policy", [
    {"missing": "zero_for_empty"}, {"absence_means_zero": True},
    {"observation_basis": "event_index", "grid_start": "2026-01-01T00:00:00Z"},
])
def test_incompatible_policy_is_rejected(policy):
    with pytest.raises(ValueError):
        DataPolicy.model_validate(policy)


@pytest.mark.parametrize("mutation,reason", [
    (lambda d: d["timestamps"].__setitem__(2, "2026-01-01T02:30:00Z"), "off"),
    (lambda d: d["data_policy"].update(grid_end="2036-01-01T00:00:00Z"), "max_points"),
    (lambda d: d["coverage"].__setitem__(1, "empty"), "nonzero"),
])
def test_invalid_or_unbounded_grid_fails_visibly(mutation, reason):
    request = body([1, 2, 3], data_policy={}, coverage=["complete"]*3)
    mutation(request["datasets"][0])
    result = source(request)
    assert result.status == "failed" and reason in result.error


@pytest.mark.parametrize("policy,value", [("sum", 5), ("mean", 2.5)])
def test_declared_duplicate_aggregation_preserves_provenance(policy, value):
    request = body([2, 3, 4], data_policy={})
    request["datasets"][0]["timestamps"][1] = request["datasets"][0]["timestamps"][0]
    request["config"]["duplicate_policy"] = policy
    result = source(request)
    assert result.status != "failed"
    assert result.data_quality["samples"][0]["value"] == value
    assert result.data_quality["duplicate_sources"][0]["original_values"] == [2, 3]


def test_expansion_uses_shared_point_budget_and_keeps_valid_sibling():
    request = body([1, 2], data_policy={})
    request["datasets"][0]["timestamps"][-1] = "2026-01-01T03:00:00Z"
    request["datasets"].append({**copy.deepcopy(request["datasets"][0]), "id": "second"})
    request["config"]["max_points"] = 5
    result = analyze(request)
    assert result.status == "partial"
    assert result.dataset_results[0].status != "failed"
    assert "shared max_points" in result.dataset_results[1].error


def test_sparse_phase_references_match_elapsed_weekday_and_never_borrow_evaluation():
    request = body([100 + [0, 10, 20, 30, 40, 50, 60][i % 7] for i in range(60)], data_policy={})
    request["datasets"][0]["values"][8] = None
    request["config"].update(season_length=7, training_size=21, calibration_size=3)
    original = source(request)
    refs = original.methods[0].diagnostics["segments"][0]["phase_references"]
    for ref in refs:
        assert all(i % 7 == ref["phase"] for i in ref["indexes"])
    changed = copy.deepcopy(request)
    changed["datasets"][0]["values"][-10:] = [999]*10
    later = source(changed)
    assert later.methods[0].diagnostics["segments"][0]["phase_references"] == refs
    assert [(r["index"], r["expected"]) for r in evidence(original)] == [(r["index"], r["expected"]) for r in evidence(later)]


def test_sparse_phase_without_support_is_explicitly_unavailable():
    request = body([10]*30, data_policy={})
    request["config"].update(season_length=24, training_size=4)
    result = source(request)
    assert result.status == "insufficient_history"
    assert any(row["reason"] == "no_training_support_for_calendar_phase" for row in result.methods[0].diagnostics["unavailable"])


def test_gap_and_reset_do_not_join_nelson_or_cusum_streams():
    request = body([100]*4 + [99, 100, 101] + [102]*4 + [None] + [102]*7, data_policy={})
    request["config"]["point_threshold"] = 100
    item = source(request)
    assert not any(p["rule"] == "nelson_rule_2" for p in item.anomaly_patterns)
    for pattern in item.anomaly_patterns:
        assert not (min(pattern["triggering_samples"]) < 11 < max(pattern["triggering_samples"]))
    request["config"]["reset_points"] = [14]
    reset = source(request)
    for pattern in reset.anomaly_patterns:
        assert not (min(pattern["triggering_samples"]) < 14 <= max(pattern["triggering_samples"]))


def test_first_range_rule_survives_missing_history_and_policy_replay():
    request = body([100], data_policy={}, rules=[{"id": "measured-limit", "kind": "acceptable_range", "minimum": 0, "maximum": 20}])
    result = analyze(request)
    assert result.status == "insufficient_history"
    assert result.dataset_results[0].assessments[0].criterion_met
    assert not result.cases[0].action_eligible
    replayed = replay_policy(result, {"allow_explicit_rules": True})
    assert get_case(replayed, replayed.cases[0].id).action_eligible
    assert not result.cases[0].action_eligible


def test_changes_require_comparable_prior_and_reset_early_population():
    request = body([0, 20, None, 100, 120, 900], data_policy={}, rules=[
        {"id": "step", "kind": "maximum_absolute_change", "threshold": 30},
        {"id": "relative", "kind": "maximum_relative_change", "threshold": 10}])
    request["config"]["reset_points"] = [5]
    result = source(request)
    assert not any(a.criterion_met for a in result.assessments)
    assert result.assessments[-1].comparison_samples == 0
    assert result.assessments[1].baseline["unavailable_rules"][0]["reason"] == "relative_change_from_zero"


def test_excluded_model_value_is_not_training_but_can_violate_measured_rule():
    request = body([10, 999, 10, 10, 10, 9, 10, 11, 20], data_policy={},
        coverage=["complete", "excluded"]+["complete"]*7,
        rules=[{"id": "range", "kind": "acceptable_range", "minimum": 0, "maximum": 500}])
    result = source(request)
    assert result.assessments[1].criterion_met
    assert 1 not in result.methods[0].diagnostics["segments"][0]["training_indexes"]


def test_event_index_keeps_real_times_and_optional_time_separation():
    request = body([10, 100], data_policy={"observation_basis": "event_index", "change_max_gap_seconds": 3600},
        rules=[{"id": "step", "kind": "maximum_absolute_change", "threshold": 20}])
    ds = request["datasets"][0]
    ds.pop("frequency")
    ds["timestamps"][1] = "2026-02-01T00:00:00Z"
    result = analyze_series(ds, request["config"])
    assert isinstance(result, ResultV11)
    assert result.dataset_results[0].data_quality["coordinate"] == "event_index"
    assert result.dataset_results[0].assessments[-1].timestamp == "2026-02-01T00:00:00+00:00"
    assert not result.dataset_results[0].assessments[-1].criterion_met
    request["config"]["season_length"] = 7
    assert source(request).methods[0].status == "inapplicable"


def test_as_of_uses_original_revision_until_correction_was_available():
    request = body([10]*12, data_policy={})
    ds = request["datasets"][0]
    ds["revisions"] = [{"timestamp": ds["timestamps"][8], "value": 100,
        "available_at": "2026-01-02T00:00:00Z", "revision_id": "corrected"}]
    request["context"] = {"as_of": ds["timestamps"][-1]}
    early = source(request)
    no_revision = copy.deepcopy(request)
    no_revision["datasets"][0]["revisions"] = []
    assert evidence(early) == evidence(source(no_revision))
    request["context"]["as_of"] = "2026-01-02T00:00:00Z"
    later = source(request)
    assert later.data_quality["samples"][8]["value"] == 100
    assert later.data_quality["samples"][8]["revision_id"] == "corrected"


def test_late_value_is_unknown_before_arrival_and_cannot_train():
    request = body([10]*12, data_policy={})
    request["datasets"][0]["available_at"] = [None]*12
    request["datasets"][0]["available_at"][1] = "2026-01-02T00:00:00Z"
    request["context"] = {"as_of": "2026-01-01T11:00:00Z"}
    result = source(request)
    assert result.data_quality["samples"][1]["value"] is None
    assert result.data_quality["samples"][1]["original_value"] is None
    assert result.data_quality["samples"][1]["reason"] == "not_available_as_of"


def test_future_as_of_and_reset_do_not_change_previous_evidence():
    request = body([10, 11, 9, 10, 9, 10, 11, None, 10, 10, 30, 10, 11, 12], data_policy={})
    request["config"]["reset_points"] = [12]
    full = source(request)
    request["context"] = {"as_of": request["datasets"][0]["timestamps"][10]}
    prefix = source(request)
    assert evidence(prefix) == [r for r in evidence(full) if r["index"] <= 10]
    assert [a.model_dump() for a in prefix.assessments] == [a.model_dump() for a in full.assessments if a.index <= 10]


def ratio_request(top, bottom):
    request = body(top, data_policy={"measurement": "additive_volume"}, units="dollars")
    request["datasets"].append({**copy.deepcopy(request["datasets"][0]), "id": "calls", "units": "calls", "values": bottom})
    request["relationships"] = [{"id": "unit-cost", "kind": "ratio", "numerator": "series", "denominator": "calls", "units": "dollars_per_call"}]
    return request


def test_relationship_missing_zero_and_tiny_denominator_keep_lineage():
    request = ratio_request([1, None, 1, 1e308], [0, 10, None, 1e-308])
    relationship = analyze(request).relationship_results[0]
    assert [row.value for row in relationship.lineage] == [None]*4
    assert [row.unavailable_reason for row in relationship.lineage] == ["zero_denominator", "missing_source_value", "missing_source_value", "nonfinite_derived_value"]
    assert relationship.lineage[0].source_values == {"series": 1, "calls": 0}
    assert relationship.lineage[1].source_coverage["series"] == "unknown"


def test_complete_daily_ratio_divides_sums_and_missing_child_invalidates_only_its_view():
    request = ratio_request([1, 9]*24, [100, 10]*24)
    request["config"]["recipe"] = "multi-resolution-v1"
    result = analyze(request)
    daily = next(r for r in result.relationship_results if r.resolution == "completed_period")
    assert [r.value for r in daily.lineage] == pytest.approx([10/110, 10/110])
    request["datasets"][0]["values"][5] = None
    result = analyze(request)
    item = next(d for d in result.dataset_results if d.dataset_id == "series" and d.resolution == "completed_period")
    assert item.data_quality["aggregation"][0]["aggregate_value"] is None
    assert item.data_quality["aggregation"][0]["usable_children"] == 23
    assert any(d.resolution == "intraday" and d.status != "failed" for d in result.dataset_results)
    replayed = replay_policy(result, {"allow_explicit_rules": True})
    ResultV11.model_validate_json(replayed.model_dump_json())


def test_daily_rules_are_not_silently_reused_from_hourly_rules():
    request = body([1]*48, data_policy={"measurement": "additive_volume"},
        rules=[{"id": "hourly", "kind": "acceptable_range", "minimum": 0, "maximum": 2}])
    request["config"]["recipe"] = "multi-resolution-v1"
    result = analyze(request)
    daily = next(d for d in result.dataset_results if d.resolution == "completed_period")
    assert not any(a.criterion_met for a in daily.assessments)


def test_adaptive_sparse_support_uses_complete_spans_with_global_indexes():
    request = body([10]*12+[None]+[10]*12+[50], data_policy={"reference_gaps":"restart"})
    request["config"].update(recipe="adaptive-seasonal-v1", trend="auto")
    result = source(request)
    assert result.status == "completed"
    assert any(m.parameters.get("source_grid_offset") == 13 for m in result.methods)
    assert max(r["index"] for r in evidence(result)) == 25
    assert not any(r["index"] == 12 for r in evidence(result))


def test_adaptive_gap_does_not_silently_train_a_post_gap_episode():
    request = body([10]*12+[None]+[100]*20, data_policy={})
    request["config"].update(recipe="adaptive-seasonal-v1", trend="auto")
    result = source(request)
    assert all(row["index"] < 12 for row in evidence(result))
    assert result.data_quality["contiguous_spans"][-1]["reason"] == "post_gap_learning_requires_explicit_reset_or_restart"


def test_legacy_schema_still_rejects_new_policy_and_keeps_missing_inapplicable():
    request = body()
    request.pop("schema_version")
    assert analyze(request).status == "inapplicable"
    request["datasets"][0]["data_policy"] = {}
    with pytest.raises(ValueError):
        Request.model_validate(request)


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in ("run_id", "runtime_seconds")}
    return [stable(v) for v in value] if isinstance(value, list) else value


def test_sparse_python_cli_and_mcp_full_result_parity():
    request = body(data_policy={})
    direct = analyze_relationships(request).model_dump(mode="json")
    cli = subprocess.run([sys.executable, "-m", "anomalyzer", "analyze", "-", "--input-format", "json", "--format", "json"],
                         input=json.dumps(request), capture_output=True, text=True, timeout=30)
    assert cli.returncode == 0, cli.stderr
    mcp = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "analyze_relationships", "arguments": request}})
    assert stable(direct) == stable(json.loads(cli.stdout)) == stable(mcp["result"]["structuredContent"])


def test_internal_incomplete_status_breaks_models_and_changes_without_losing_grid():
    request = body([10]*10+[100]+[10]*10, period_statuses=["complete"]*10+["incomplete"]+["complete"]*10)
    result = source(request)
    assert result.data_quality["samples"][10]["original_value"] == 100
    assert result.data_quality["samples"][10]["original_period_status"] == "incomplete"
    assert not any(a.index == 10 for a in result.assessments)
    assert next(a for a in result.assessments if a.index == 11).comparison_samples == 0
    assert not any(r["index"] == 10 for r in evidence(result))


def test_restart_policy_cannot_reuse_a_prior_regime_reference():
    request = body([10]*10+[None]+[100], data_policy={})
    reuse = source(request)
    assert any(r["index"] == 11 and r["triggers"] for r in evidence(reuse))
    request["datasets"][0]["data_policy"]["reference_gaps"] = "restart"
    restart = source(request)
    assert not any(r["index"] == 11 for r in evidence(restart))
    assert restart.methods[0].diagnostics["segments"][-1]["training_indexes"] == [11]


def test_case_retains_delayed_correction_availability_cutoff():
    request = body([10], data_policy={}, rules=[{"id":"range","kind":"acceptable_range","minimum":0,"maximum":20}])
    ds = request["datasets"][0]
    ds["revisions"] = [{"timestamp":ds["timestamps"][0],"value":100,
                         "available_at":"2026-01-02T00:00:00Z","revision_id":"r1"}]
    request["context"] = {"as_of":"2026-01-02T00:00:00Z"}
    result = analyze(request)
    assert result.cases[0].event_time == "2026-01-01T00:00:00+00:00"
    assert result.cases[0].source_availability_cutoff == "2026-01-02T00:00:00+00:00"
    request["context"]["as_of"] = "2026-01-01T00:00:00Z"
    assert not analyze(request).cases


def test_future_late_event_cannot_move_an_earlier_event_index_or_calendar_origin():
    for basis in ("calendar", "event_index"):
        request = body([10]*12, data_policy={"observation_basis":basis})
        ds = request["datasets"][0]
        if basis == "event_index":
            ds.pop("frequency")
        request["context"] = {"as_of":"2026-01-01T11:00:00Z"}
        original = source(request)
        ds["timestamps"].insert(0,"2025-12-31T23:00:00Z")
        ds["values"].insert(0,999)
        ds["available_at"] = ["2026-01-02T00:00:00Z"]+[None]*12
        later = source(request)
        assert evidence(original) == evidence(later)
        assert original.data_quality["window"] == later.data_quality["window"]


def test_model_exclusion_retains_exact_relationship_range_rules():
    request = ratio_request([100, 1, 1, 1, 1], [1]*5)
    request["datasets"][0]["coverage"] = ["excluded"]+["complete"]*4
    request["relationships"][0]["rules"] = [{"id":"range","kind":"acceptable_range","minimum":0,"maximum":10}]
    result = analyze(request).relationship_results[0]
    assert result.lineage[0].value == 100
    assert result.assessments[0].criterion_met
    assert not any(row["index"] == 0 for method in result.methods for row in method.evidence)


@pytest.mark.parametrize("values", [[0]*20, [1e-308]*20, [1e308, -1e308]])
def test_degenerate_finite_measurements_keep_valid_rule_results(values):
    request = body(values, data_policy={}, rules=[{"id":"range","kind":"acceptable_range","minimum":0,"maximum":1}])
    result = analyze(request)
    assert result.dataset_results[0].status != "failed"
    ResultV11.model_validate_json(result.model_dump_json())


def test_sibling_failure_and_exhausted_budget_are_visible():
    request = body([1, 2, 3], data_policy={})
    request["datasets"].append({**copy.deepcopy(request["datasets"][0]), "id":"bad"})
    request["datasets"][1]["timestamps"][1] = "2026-01-01T01:30:00Z"
    result = analyze(request)
    assert result.status == "partial"
    assert next(d for d in result.dataset_results if d.dataset_id == "series").status != "failed"
    request["config"]["max_runtime_seconds"] = 1e-9
    result = analyze(request)
    assert result.stop_reason == "runtime_budget"
    assert all(d.error and "budget" in d.error for d in result.dataset_results)


def test_multi_resolution_mcp_drilldown_selects_correct_view_and_replays_case_ids():
    from anomalyzer.mcp_views import build_findings, get_evidence
    request = body([1]*60, data_policy={"measurement":"additive_volume"},
        completed_period_rules=[{"id":"daily","kind":"acceptable_range","minimum":0,"maximum":20}])
    request["config"]["recipe"] = "multi-resolution-v1"
    result = analyze(request)
    assert result.cases and all(c.resolution == "completed_period" for c in result.cases)
    replayed = replay_policy(result, {"allow_explicit_rules":True})
    assert {c.id for c in replayed.cases} == {c.id for c in result.cases}
    assert all(c.action_eligible for c in replayed.cases)
    doc = result.model_dump(mode="json")
    findings = build_findings(doc)
    assert len({f["id"] for f in findings}) == len(findings)
    for finding in findings:
        detail = get_evidence(doc, finding["id"])
        assert detail["finding"]["resolution"] == finding["resolution"]


def test_unsupported_daily_relationship_is_explicit_and_does_not_reinterpret_lag():
    request = ratio_request([1]*48, [1]*48)
    request["config"]["recipe"] = "multi-resolution-v1"
    request["relationships"] = [{"id":"lag","kind":"lagged_response","response":"series","predictor":"calls","lag":2,"coefficient":1,"units":"dollars"}]
    result = analyze(request)
    daily = next(r for r in result.relationship_results if r.resolution == "completed_period")
    assert daily.status == "inapplicable" and "lag" in daily.limitations[0]


@pytest.mark.parametrize("exclusion", ["reset", "excluded_child"])
def test_complete_daily_measurement_survives_model_exclusion(exclusion):
    request = body([1]*48, data_policy={"measurement":"additive_volume"},
        completed_period_rules=[{"id":"daily","kind":"acceptable_range","minimum":0,"maximum":20}])
    request["config"]["recipe"] = "multi-resolution-v1"
    if exclusion == "reset":
        request["config"]["reset_points"] = [12]
    else:
        request["datasets"][0]["coverage"] = ["excluded"]+["complete"]*47
    result = analyze(request)
    daily = next(d for d in result.dataset_results if d.resolution == "completed_period")
    row = daily.data_quality["aggregation"][0]
    assert row["complete"] and row["aggregate_value"] == 24 and not row["model_eligible"]
    assert daily.assessments[0].criterion_met


def test_duplicate_relationship_lineage_lists_all_original_inputs():
    request = ratio_request([1, 2, 3], [10, 20, 30])
    for ds in request["datasets"]:
        ds["timestamps"][1] = ds["timestamps"][0]
    request["config"]["duplicate_policy"] = "sum"
    row = analyze(request).relationship_results[0].lineage[0]
    assert row.value == 0.1
    assert row.source_indexes == {"series":-1, "calls":-1}
    assert row.source_input_indexes == {"series":[0,1], "calls":[0,1]}


def test_event_timestamp_ties_are_rejected_without_fabricated_offsets():
    request = body([1, 2], data_policy={"observation_basis":"event_index"})
    request["datasets"][0].pop("frequency")
    request["datasets"][0]["timestamps"][1] = request["datasets"][0]["timestamps"][0]
    result = source(request)
    assert result.status == "failed" and "unique event timestamps" in result.error


def test_future_arrival_inside_old_unknown_slot_does_not_rewrite_earlier_assessments():
    request = body(data_policy={})
    request["context"] = {"as_of":request["datasets"][0]["timestamps"][-1]}
    original = source(request)
    request["datasets"][0]["values"][8] = 999
    request["datasets"][0]["available_at"] = [None]*14
    request["datasets"][0]["available_at"][8] = "2026-01-02T00:00:00Z"
    future = source(request)
    assert evidence(original) == evidence(future)
    assert [a.model_dump() for a in original.assessments] == [a.model_dump() for a in future.assessments]


def test_multi_resolution_recomputation_keeps_profile_parameters_deterministic():
    request = ratio_request([1,9]*24, [100,10]*24)
    request["config"]["recipe"] = "multi-resolution-v1"
    assert stable(analyze(request).model_dump(mode="json")) == stable(analyze(request).model_dump(mode="json"))
