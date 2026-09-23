import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from anomalyzer import analyze
from anomalyzer.agent import get_case, replay_policy
from anomalyzer.contracts import RequestV11, ResultV11


def datasets(values_by_id, *, units=None, missing_statuses=None):
    size = len(next(iter(values_by_id.values())))
    times = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat()
             for i in range(size)]
    return [{
        "id": dataset_id, "timestamps": times, "values": values,
        "frequency": "1d", "units": (units or {}).get(dataset_id, dataset_id),
        "entity": {"account": "example"},
        **({"period_statuses": missing_statuses[dataset_id]}
           if missing_statuses and dataset_id in missing_statuses else {}),
    } for dataset_id, values in values_by_id.items()]


def request(values_by_id, relationships=(), **extra):
    return {
        "schema_version": "1.1", "datasets": datasets(values_by_id),
        "relationships": list(relationships),
        "config": {"season_length": 1, "training_size": 4,
                   "calibration_size": 3, "trend": "none"},
        **extra,
    }


def test_short_history_assessments_are_useful_and_prefix_invariant():
    full = analyze(request({"series": [10, 12, 11, 20]}))
    assessments = full.dataset_results[0].assessments
    assert [item.classification for item in assessments] == [
        "observation", "change", "change", "departure_candidate"]
    assert assessments[-1].maturity == "early"
    assert not assessments[-1].criterion_met
    assert not full.cases
    for length in range(1, 5):
        prefix = analyze(request({"series": [10, 12, 11, 20][:length]}))
        assert [item.model_dump() for item in prefix.dataset_results[0].assessments] == [
            item.model_dump() for item in assessments[:length]]


def test_explicit_rule_is_exact_but_not_actionable_without_policy():
    body = request({"series": [10, 12, 20]})
    body["datasets"][0]["rules"] = [{
        "id": "max-step", "kind": "maximum_absolute_change", "threshold": 5}]
    result = analyze(body)
    assessment = result.dataset_results[0].assessments[-1]
    assert assessment.classification == "criterion_violation"
    assert assessment.criterion_met is True
    assert assessment.action_eligible is False
    assert "does not establish" in assessment.not_established
    assert result.cases and not result.cases[0].action_eligible
    original_case = result.cases[0]
    replayed = replay_policy(result, {"allow_explicit_rules": True})
    assert replayed.dataset_results[0].assessments[-1].action_eligible
    replayed_case = get_case(replayed, replayed.cases[0].id)
    assert replayed_case.action_eligible
    assert replayed_case.id == original_case.id
    assert replayed_case.revision_id != original_case.revision_id


def test_cases_are_scoped_by_entity_at_the_same_event_time():
    body = request({"a": [10, 20], "b": [10, 20]})
    body["datasets"][0]["entity"] = {"account": "first"}
    body["datasets"][1]["entity"] = {"account": "second"}
    for dataset in body["datasets"]:
        dataset["rules"] = [{
            "id": "max-step", "kind": "maximum_absolute_change",
            "threshold": 5,
        }]
    result = analyze(body)
    assert len(result.cases) == 2
    assert {tuple(case.entity.items()) for case in result.cases} == {
        (("account", "first"),), (("account", "second"),)}
    assert len({case.id for case in result.cases}) == 2


def test_schema_11_requires_explicit_entity_scope():
    body = request({"a": [1, 2]})
    del body["datasets"][0]["entity"]
    with pytest.raises(ValueError, match="entity"):
        RequestV11.model_validate(body)


def test_dataset_order_does_not_change_fingerprint_or_evidence():
    body = request({"b": [2, 3, 4, 5], "a": [1, 2, 3, 4]})
    first = analyze(body)
    reordered = copy.deepcopy(body)
    reordered["datasets"].reverse()
    second = analyze(reordered)
    assert first.input_fingerprint == second.input_fingerprint
    assert [item.dataset_id for item in first.dataset_results] == ["a", "b"]
    assert [item.model_dump(exclude={"methods"}) for item in first.dataset_results] == [
        item.model_dump(exclude={"methods"}) for item in second.dataset_results]


def test_ratio_lineage_and_early_relationship_departure():
    body = request(
        {"visits": [100, 100, 100, 100], "orders": [10, 10, 10, 2]},
        [{"id": "conversion", "kind": "ratio", "numerator": "orders",
          "denominator": "visits", "units": "orders_per_visit"}])
    result = analyze(body)
    relationship = result.relationship_results[0]
    assert [point.value for point in relationship.lineage] == [.1, .1, .1, .02]
    assert relationship.lineage[-1].source_indexes == {"orders": 3, "visits": 3}
    assert relationship.lineage[-1].formula == "orders[t] / visits[t]"
    assert relationship.assessments[-1].classification == "departure_candidate"
    assert not relationship.observations
    ResultV11.model_validate_json(result.model_dump_json())


def test_missing_and_zero_denominator_are_unavailable_not_zero():
    body = request(
        {"visits": [100, 0, 100], "orders": [10, 5, None]},
        [{"id": "conversion", "kind": "ratio", "numerator": "orders",
          "denominator": "visits", "units": "orders_per_visit",
          "zero_denominator": "inapplicable"}])
    complete = analyze(body)
    relationship = complete.relationship_results[0]
    assert [point.value for point in relationship.lineage] == [.1, None, None]
    assert [point.unavailable_reason for point in relationship.lineage] == [
        None, "zero_denominator", "missing_source_value"]
    assert relationship.data_quality["missing_values_are_zero"] is False
    assert relationship.status == "insufficient_evidence"
    assert complete.status == "partial"


def test_alignment_unit_and_partial_failure_are_specific():
    body = request(
        {"revenue": [10, 11, 12], "cost": [5, 6, 7]},
        [{"id": "margin", "kind": "difference", "minuend": "revenue",
          "subtrahend": "cost", "units": "usd"}])
    relationship = analyze(body).relationship_results[0]
    assert relationship.status == "failed"
    assert "identical declared source units" in relationship.error
    assert all(item.status == "insufficient_history"
               for item in analyze(body).dataset_results)


def test_lagged_response_uses_supplied_coefficient_and_prior_sample():
    body = request(
        {"orders": [0, 0, 20, 40], "leads": [10, 20, 30, 40]},
        [{"id": "response", "kind": "lagged_response", "response": "orders",
          "predictor": "leads", "lag": 2, "coefficient": 2,
          "units": "orders"}])
    relationship = analyze(body).relationship_results[0]
    assert [point.value for point in relationship.lineage] == [None, None, 0, 0]
    assert relationship.lineage[2].source_indexes == {"orders": 2, "leads": 0}
    assert relationship.lineage[2].latest_source_cutoff.endswith("00:00:00+00:00")


@pytest.mark.parametrize(
    "relationship,expected",
    [
        ({"id": "gap", "kind": "difference", "minuend": "a",
          "subtrahend": "b", "units": "count"}, [8, 7, 6]),
        ({"id": "residual", "kind": "normalized_residual", "observed": "a",
          "expected": "b", "scale": 2}, [4, 3.5, 3]),
        ({"id": "joint", "kind": "joint_condition",
          "conditions": [
              {"dataset": "a", "operator": "gte", "threshold": 10},
              {"dataset": "b", "operator": "lte", "threshold": 4}],
          "combine": "all", "units": "condition_met"}, [1, 1, 0]),
    ],
)
def test_remaining_relationship_primitives(relationship, expected):
    body = request({"a": [10, 11, 12], "b": [2, 4, 6]}, [relationship])
    for dataset in body["datasets"]:
        dataset["units"] = "count"
    result = analyze(body).relationship_results[0]
    assert [point.value for point in result.lineage] == expected
    assert all(point.source_indexes for point in result.lineage)


def test_estimated_lag_coefficient_is_frozen_and_prefix_invariant():
    values = {"orders": [0, 0, 20, 40, 60, 80, 100],
              "leads": [10, 20, 30, 40, 50, 60, 70]}
    relationship = {"id": "response", "kind": "lagged_response",
                    "response": "orders", "predictor": "leads", "lag": 2,
                    "training_size": 3, "units": "orders"}
    short = analyze(request({key: value[:6] for key, value in values.items()},
                            [relationship])).relationship_results[0]
    full = analyze(request(values, [relationship])).relationship_results[0]
    assert full.data_quality["parameters"]["coefficient"] == pytest.approx(2)
    assert [point.model_dump() for point in short.lineage] == [
        point.model_dump() for point in full.lineage[:6]]


def test_contract_rejects_ambiguous_relationship_fields():
    body = request(
        {"a": [1, 2], "b": [1, 2]},
        [{"id": "ratio", "kind": "ratio", "numerator": "a",
          "denominator": "b", "units": "a_per_b", "lag": 1}])
    with pytest.raises(ValueError):
        RequestV11.model_validate(body)


def test_v11_checked_in_schemas_exist():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for name, contract in (("request-1.1", RequestV11), ("result-1.1", ResultV11)):
        path = root / "schemas" / f"{name}.schema.json"
        if not path.exists():
            pytest.fail(f"missing generated schema {path}")
        schema = json.loads(path.read_text())
        schema.pop("$schema")
        assert schema == contract.model_json_schema()
