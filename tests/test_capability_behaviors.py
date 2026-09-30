"""Focused public-behavior checks for the capability map's remaining gaps."""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from anomalyzer import analyze, replay_policy


def request(values, **extra):
    times = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat()
             for index in range(len(values))]
    return {
        "schema_version": "1.1",
        "datasets": [{"id": "series", "timestamps": times, "values": values,
                      "frequency": "1d", "entity": {"account": "example"}}],
        "config": {"season_length": 1, "training_size": 4,
                   "calibration_size": 3, "trend": "none"},
        **extra,
    }


@pytest.mark.parametrize("mismatch,reason", [
    ("timestamps", "identical UTC-normalized timestamps"),
    ("frequency", "same cadence"),
    ("entity", "matching entity metadata"),
    ("duplicates", "unique source timestamps"),
    ("positional", "timestamped datasets"),
])
def test_relationship_requires_exact_source_alignment(mismatch, reason):
    body = request([10.0] * 12)
    second = copy.deepcopy(body["datasets"][0])
    second["id"] = "denominator"
    second["values"] = [100.0] * 12
    if mismatch == "timestamps":
        second["timestamps"] = [(datetime.fromisoformat(value) + timedelta(hours=1)).isoformat()
                                for value in second["timestamps"]]
    elif mismatch == "frequency":
        second["frequency"] = "2d"
    elif mismatch == "entity":
        second["entity"] = {"account": "another"}
    elif mismatch == "duplicates":
        second["timestamps"][1] = second["timestamps"][0]
        body["config"]["duplicate_policy"] = "mean"
    else:
        del second["timestamps"]
        del second["frequency"]
    body["datasets"].append(second)
    body["relationships"] = [{
        "id": "rate", "kind": "ratio", "numerator": "series",
        "denominator": "denominator", "units": "per_request",
    }]
    result = analyze(body)
    relationship = result.relationship_results[0]
    assert result.status == "partial"
    assert result.dataset_results[1].dataset_id == "series"
    assert result.dataset_results[1].status == "completed"
    assert relationship.status == "failed"
    if mismatch == "duplicates":
        assert reason in result.dataset_results[0].error
    else:
        assert reason in relationship.error
    assert not relationship.lineage


@pytest.mark.parametrize("rule,values,violations", [
    ({"id": "range", "kind": "acceptable_range", "minimum": 10, "maximum": 20},
     [10, 20, 9, 21], [2, 3]),
    ({"id": "absolute", "kind": "maximum_absolute_change", "threshold": 5},
     [10, 15, 21], [2]),
    ({"id": "relative", "kind": "maximum_relative_change", "threshold": 0.5},
     [10, 15, 24], [2]),
])
def test_explicit_rules_respect_boundaries(rule, values, violations):
    body = request(values)
    body["datasets"][0]["rules"] = [rule]
    result = analyze(body)
    crossed = [item for item in result.dataset_results[0].assessments
               if item.classification == "criterion_violation"]
    assert [item.index for item in crossed] == violations
    assert all(item.baseline["violations"][0]["id"] == rule["id"] for item in crossed)
    assert all(item.criterion_met and not item.action_eligible for item in crossed)
    assert all(not item.notification_eligible for item in crossed)
    assert len(result.cases) == len(violations)


def test_relative_rule_does_not_compare_across_zero_or_missing_values():
    body = request([0, 100, None, 200, 300, 500])
    body["datasets"][0]["rules"] = [{
        "id": "relative", "kind": "maximum_relative_change", "threshold": 0.5}]
    result = analyze(body)
    assessments = result.dataset_results[0].assessments
    assert [item.index for item in assessments
            if item.classification == "criterion_violation"] == [5]
    assert next(item for item in assessments if item.index == 1).relative_change is None
    after_gap = next(item for item in assessments if item.index == 3)
    assert after_gap.classification == "observation"
    assert after_gap.comparison_samples == 0


def test_policy_replay_separates_action_from_notification():
    body = request([10, 10, 20])
    body["datasets"][0]["rules"] = [{
        "id": "step", "kind": "maximum_absolute_change", "threshold": 5}]
    original = analyze(body)
    before = original.model_dump(mode="json")
    notify = replay_policy(original, {"notification_requires_action": False})
    action = replay_policy(original, {"allow_explicit_rules": True})
    reset = replay_policy(action, {})
    assert original.model_dump(mode="json") == before
    assert not notify.cases[0].action_eligible
    assert notify.cases[0].notification_eligible
    assert action.cases[0].action_eligible and action.cases[0].notification_eligible
    assert not reset.cases[0].action_eligible and not reset.cases[0].notification_eligible
    for result in (notify, action, reset):
        assert result.cases[0].id == original.cases[0].id
        assert result.dataset_results[0].methods == original.dataset_results[0].methods
        assert result.cases[0].evidence_refs == original.cases[0].evidence_refs
    assert notify.cases[0].revision_id != original.cases[0].revision_id
    assert reset.cases[0].revision_id == original.cases[0].revision_id


def test_policy_replay_enables_calibrated_departures_only_when_requested():
    original = analyze(request([100.0] * 11 + [150.0]))
    assert original.cases and not original.cases[0].action_eligible
    explicit_only = replay_policy(original, {"allow_explicit_rules": True})
    calibrated = replay_policy(original, {"allow_calibrated_departures": True})
    assert not explicit_only.cases[0].action_eligible
    assert calibrated.cases[0].action_eligible
    assert calibrated.dataset_results[0].methods == original.dataset_results[0].methods
    assert calibrated.cases[0].id == original.cases[0].id


def test_policy_keeps_early_candidates_ineligible():
    result = analyze(request([10, 12, 11, 20], policy={
        "allow_explicit_rules": True, "allow_calibrated_departures": True,
        "notification_requires_action": False,
    }))
    replayed = replay_policy(result, result.resolved_config["policy"])
    candidate = replayed.dataset_results[0].assessments[-1]
    assert candidate.classification == "departure_candidate"
    assert not candidate.criterion_met
    assert not candidate.action_eligible and not candidate.notification_eligible
    assert not replayed.cases


def test_season_inference_excludes_reserved_tail():
    season = [10, 20, 5, 15, 8, 30, 12]
    ordinary = analyze(season * 12)
    values = season * 12
    changed_tail = analyze(values[:69] + [500 + index * index for index in range(15)])
    for result in (ordinary, changed_tail):
        assert result.methods[0].parameters["season_length"] == 7
        assert result.methods[0].parameters["season_length_source"] == "inferred"
    assert ordinary.methods[0].diagnostics["season_inference"] == (
        changed_tail.methods[0].diagnostics["season_inference"])


def test_partial_analysis_preserves_healthy_siblings():
    body = request([100.0] * 12)
    failed = copy.deepcopy(body["datasets"][0])
    failed["id"] = "broken"
    failed["timestamps"][0] = "not-a-timestamp"
    body["datasets"].append(failed)
    result = analyze(body)
    by_id = {item.dataset_id: item for item in result.dataset_results}
    assert result.status == "partial"
    assert by_id["broken"].status == "failed"
    assert "invalid timestamp" in by_id["broken"].error
    assert by_id["series"].status == "completed"
    assert by_id["series"].methods[0].evidence
    assert not by_id["series"].observations


@pytest.mark.parametrize("aggregation,daily,partial", [
    ("sum", 300, 78), ("mean", 12.5, 6.5), ("last", 24, 12),
])
def test_multi_resolution_uses_selected_aggregation(aggregation, daily, partial):
    count = 8 * 24 + 12
    times = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index)).isoformat()
             for index in range(count)]
    result = analyze({
        "datasets": [{"timestamps": times, "values": [index % 24 + 1 for index in range(count)],
                      "frequency": "1h"}],
        "config": {"recipe": "multi-resolution-v1", "aggregate_function": aggregation,
                   "completed_period_season_length": 1, "training_size": 2,
                   "calibration_size": 3},
    })
    complete = next(method for method in result.methods
                    if method.id.startswith("completed_period:"))
    assert complete.evidence[-1]["observed"] == pytest.approx(daily)
    assert result.data_quality["views"]["completed_period"]["observation_count"] == 8
    unfinished = result.data_quality["incomplete_period"]
    assert unfinished["aggregate_function"] == aggregation
    assert unfinished["observed_aggregate"] == pytest.approx(partial)
    assert unfinished["included_in_completed_period_view"] is False
