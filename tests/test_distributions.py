"""Independent permutation references and population-change qualification."""
from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import (
    __version__, analyze, compare_distributions, monitor_distributions,
    DistributionRequest, DistributionMonitorRequest,
)
from anomalyzer.mcp import TOOLS, handle


def population(values, prefix):
    return {"samples": [{"id": f"{prefix}-{i}", "value": v} for i, v in enumerate(values)]}


def request(a, b, kind="numeric", **config):
    return dict(kind=kind, entity={"application": "synthetic"}, units="fraction" if kind == "numeric" else "feature",
        reference=population(a, "reference"), current=population(b, "current"), assume_exchangeable=True,
        config={"min_reference": 2, "min_current": 2, **config})


def cdf_distance(a, b):
    return max(abs(sum(v <= x for v in a) / len(a) - sum(v <= x for v in b) / len(b)) for x in set(a + b))


@pytest.mark.parametrize("a,b", [([0, 0, 1], [0, 1, 1]), ([0, 1], [2, 3]),
    ([0, 0], [0, 0]), ([0, .1, .2, 1], [0, .1, 1]), ([-1, 0, 1], [-2, 0, 2])])
def test_numeric_exact_matches_independent_exhaustive_labelings_including_ties(a, b):
    pooled = a + b
    observed = cdf_distance(a, b)
    tail, total = 0, 0
    for assignment in combinations(range(len(pooled)), len(a)):
        selected = set(assignment)
        left = [v for i, v in enumerate(pooled) if i in selected]
        right = [v for i, v in enumerate(pooled) if i not in selected]
        tail += cdf_distance(left, right) >= observed - 1e-12
        total += 1
    result = compare_distributions(request(a, b))
    assert result.statistic == pytest.approx(observed)
    assert result.p_value == pytest.approx(tail / total)


def test_same_mean_shape_shift_without_extreme_individual_values():
    a = [0, .25, .5, .75, 1] * 80
    b = [0, 0, .5, 1, 1] * 80
    result = compare_distributions(request(a, b))
    assert result.reference["mean"] == result.current["mean"] == .5
    import statistics
    assert max(abs(v-statistics.mean(a)) / statistics.stdev(a) for v in b) < 3
    assert result.change_detected
    assert result.statistic == pytest.approx(.2)
    assert result.details["permutation_method"] == "exact_tie_conditional"


def test_stable_zero_heavy_mixture_keeps_all_legitimate_hits():
    values = [0] * 90 + [.1, .5, .8, 1] * 3
    result = compare_distributions(request(values, list(reversed(values))))
    assert result.status == "completed"
    assert result.p_value == 1
    assert not result.change_detected
    assert result.reference["sample_count"] == len(values)
    assert result.reference["excluded_ids"] == []


def test_categorical_exact_handles_sparse_novel_categories():
    result = compare_distributions(request(["search"] * 4, ["export"] * 4, "categorical"))
    assert result.statistic == 1
    assert result.p_value == pytest.approx(2 / 70)
    assert result.details["permutation_method"] == "exact"
    assert result.details["total_variation"] == 1


def test_categorical_global_shift_is_reproducible_and_explains_every_share():
    a = [f"feature-{k}" for k in range(16) for _ in range(50)]
    b = [f"feature-{k}" for k in range(16) for _ in range(65 if k < 8 else 35)]
    body = request(a, b, "categorical", alpha=.05, min_effect=.005, permutations=1999)
    result = compare_distributions(body)
    assert result.change_detected
    assert result.details["permutation_method"] == "monte_carlo_plus_one"
    assert result.p_value > 0
    assert len(result.details["categories"]) == 16
    assert sum(row["share_change"] for row in result.details["categories"]) == pytest.approx(0)
    assert max(abs(row["share_change"]) for row in result.details["categories"]) < .02
    assert compare_distributions(body) == result


def test_weighted_composition_never_treats_tokens_as_independent_events():
    body = dict(kind="categorical", entity={"app": "synthetic"}, units="tokens",
                reference={"weights": {"search": 900000, "export": 100000}},
                current={"weights": {"search": 100000, "export": 900000}}, assume_exchangeable=True)
    result = compare_distributions(body)
    assert result.status == "descriptive"
    assert result.p_value is None and not result.change_detected
    assert result.reference["sample_count"] is None
    assert result.practical_change


def test_quantity_weighted_reports_are_permuted_as_whole_independent_events():
    body = request(["search", "export"] * 16, ["search", "export"] * 16,
                   "categorical", permutations=999)
    for i, sample in enumerate(body["reference"]["samples"]):
        sample["weight"] = 9 if i % 2 == 0 else 1
    for i, sample in enumerate(body["current"]["samples"]):
        sample["weight"] = 1 if i % 2 == 0 else 9
    result = compare_distributions(body)
    assert result.change_detected
    assert result.reference["sample_count"] == result.current["sample_count"] == 32
    assert result.reference["total_weight"] == result.current["total_weight"] == 160
    for population_key in ("reference", "current"):
        for sample in body[population_key]["samples"]:
            sample["weight"] *= 10000
    scaled = compare_distributions(body)
    assert scaled.p_value == result.p_value
    assert scaled.statistic == pytest.approx(result.statistic)
    assert scaled.reference["sample_count"] == 32


def test_large_report_quantities_cannot_supply_missing_event_support():
    body = request(["search"], ["export"], "categorical")
    body["reference"]["samples"][0]["weight"] = 1000000
    body["current"]["samples"][0]["weight"] = 1000000
    result = compare_distributions(body)
    assert result.status == "insufficient_history"
    assert result.p_value is None and not result.change_detected


def test_extreme_finite_values_do_not_overflow_numeric_summaries():
    values = [sys.float_info.max] * 3
    result = compare_distributions(request(values, values))
    assert result.reference["mean"] == result.reference["median"] == sys.float_info.max
    assert result.p_value == 1
    json.dumps(result.model_dump(mode="json"), allow_nan=False)
    with pytest.raises(ValidationError):
        compare_distributions(request([10**10000, 1], [0, 1]))


def test_assumptions_effect_and_support_are_separate_gates():
    body = request([0] * 50, [1] * 50)
    body["assume_exchangeable"] = False
    descriptive = compare_distributions(body)
    assert descriptive.status == "descriptive" and descriptive.practical_change
    assert descriptive.p_value is None and not descriptive.change_detected
    insufficient = compare_distributions(request([0], [1]))
    assert insufficient.status == "insufficient_history" and insufficient.p_value is None
    practical = compare_distributions(request([0, 1] * 100, [0, 0, 0, 1] * 100, min_effect=.5))
    assert practical.statistical_change and not practical.practical_change and not practical.change_detected


def test_multiple_comparison_budget_and_permutation_resolution_are_visible():
    body = request(["a"] * 40, ["b"] * 40, "categorical", permutations=99, max_comparisons=100)
    result = compare_distributions(body)
    assert result.status == "resolution_limited"
    assert result.threshold == .0001
    assert result.p_value == .01
    assert result.adjusted_p_value == 1
    assert not result.change_detected


def test_family_budget_bounds_exhaustive_null_allocations_for_dependent_metrics():
    # Each indexed event has two measurements. Enumerate every exchangeable
    # assignment; the two tests share event labels and need not be independent.
    values = list(range(-5, 5))
    any_findings = 0
    allocations = list(combinations(range(10), 5))
    for allocation in allocations:
        left = set(allocation)
        found = False
        for index, transform in enumerate((lambda v: v, lambda v: v*v)):
            a = [transform(v) for i, v in enumerate(values) if i in left]
            b = [transform(v) for i, v in enumerate(values) if i not in left]
            result = compare_distributions(request(a, b, alpha=.1, min_effect=0,
                                                  max_comparisons=2, comparison_index=index))
            found |= result.change_detected
        any_findings += found
    assert 0 < any_findings / len(allocations) <= .1


@pytest.mark.parametrize("mutation", [
    lambda r: r["current"]["samples"][0].update(id="reference-0"),
    lambda r: r["current"]["samples"][1].update(id="current-0"),
    lambda r: r["current"]["samples"][0].update(value=True),
    lambda r: r["current"]["samples"][0].update(value=float("nan")),
    lambda r: r["current"]["samples"][0].update(value="0"),
    lambda r: r["config"].update(comparison_index=1),
    lambda r: r.update(unrecognized=True),
])
def test_invalid_population_contracts_fail_explicitly(mutation):
    body = request([0, 1], [0, 1])
    mutation(body)
    with pytest.raises((ValidationError, ValueError)):
        compare_distributions(body)


def monitor(values, **extra):
    return dict(kind="numeric", monitor_id="fixed-family", entity={"app": "synthetic"}, units="fraction",
        samples=population(values, "event")["samples"], order="trusted_sequence", assume_exchangeable=True,
        reference_size=40, window_sizes=[20, 40], max_looks=41,
        config=dict(min_reference=20, min_current=20, alpha=.05), **extra)


def test_monitor_is_causal_frozen_and_corrects_all_planned_windows():
    values = [.5] * 60 + [0, 1] * 30
    body = monitor(values)
    result = monitor_distributions(body)
    prefix = monitor_distributions({**body, "samples": body["samples"][:75]})
    assert result.reference_id == prefix.reference_id
    assert result.evaluations[:len(prefix.evaluations)] == prefix.evaluations
    assert result.testing["max_comparisons"] == 82
    assert all(row["result"]["threshold"] == .05/82 for row in result.evaluations)
    assert result.first_detection is not None
    for row in result.evaluations:
        assert not set(row["result"]["reference"]["sample_ids"]) & set(row["result"]["current"]["sample_ids"])
        assert row["result"]["reference_id"] == result.reference_id


def test_unknowns_break_windows_and_incomplete_suffix_is_never_evaluated():
    values = [0, 1] * 20 + [None] + [0, 1] * 30
    body = monitor(values)
    body["samples"][-1]["complete"] = False
    result = monitor_distributions(body)
    first = result.evaluations[0]["result"]
    assert first["status"] == "insufficient_history"
    assert first["current"]["unknown_count"] == 1
    assert "event-40" in first["current"]["excluded_ids"]
    assert result.data_quality["unknown_samples"] == 1
    assert result.data_quality["incomplete_samples"] == 1
    assert all(row["index"] < len(values)-1 for row in result.evaluations)
    assert any(row["result"]["status"] == "completed" for row in result.evaluations)


def test_monitor_rejects_untrusted_ties_and_replenished_budgets():
    body = monitor([0, 1] * 35)
    body["order"] = "timestamp"
    with pytest.raises(ValidationError, match="trusted_sequence"):
        monitor_distributions(body)
    for sample in body["samples"]:
        sample["timestamp"] = "2026-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="tied timestamps"):
        monitor_distributions(body)
    body["order"] = "trusted_sequence"
    assert monitor_distributions(body).evaluations
    body["config"]["max_comparisons"] = 20
    with pytest.raises(ValidationError, match="monitor owns"):
        monitor_distributions(body)


def test_horizon_does_not_silently_restart_or_learn_current_population():
    body = monitor([0, 1] * 60)
    body["max_looks"] = 2
    result = monitor_distributions(body)
    assert result.status == "horizon_exhausted"
    assert result.testing["evaluated_looks"] == 2
    assert len(result.evaluations) == 4
    assert result.data_quality["after_horizon_samples"] == 59


def test_runtime_exhaustion_preserves_evidence_without_a_finding(monkeypatch):
    from anomalyzer.budget import RuntimeBudget
    def exhausted(self):
        raise TimeoutError("fixture")
    monkeypatch.setattr(RuntimeBudget, "check", exhausted)
    result = compare_distributions(request([0] * 40, [1] * 40))
    assert result.status == "budget_exceeded"
    assert result.reference["sample_count"] == 40
    assert result.p_value is None and not result.change_detected
    assert monitor_distributions(monitor([0, 1] * 40)).status == "partial"


def test_cli_mcp_api_and_schemas_agree(tmp_path):
    body = request([0] * 40, [1] * 40)
    expected = compare_distributions(body).model_dump(mode="json")
    assert analyze({"schema_version": "distribution-v1", **body}).model_dump(mode="json") == expected
    run = subprocess.run([sys.executable, "-m", "anomalyzer", "compare-distributions", "-"],
        input=json.dumps(body), capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == expected
    result = handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name="compare_distributions", arguments={"request": body})))
    assert result["result"]["structuredContent"] == expected
    tool = next(tool for tool in TOOLS if tool["name"] == "compare_distributions")
    jsonschema.validate({"request": body}, tool["inputSchema"])
    jsonschema.validate(expected, tool["outputSchema"])
    root = Path(__file__).parents[1]
    jsonschema.validate(body, json.loads((root / "schemas/distribution-request.schema.json").read_text()))
    jsonschema.validate(expected, json.loads((root / "schemas/distribution-result.schema.json").read_text()))
    assert subprocess.run([sys.executable, "-m", "anomalyzer", "--version"], capture_output=True, text=True).stdout.strip() == f"anomalyzer {__version__}"


def test_monitor_cli_mcp_and_schema_and_nontriggering_statuses():
    body = monitor([0, 1] * 40)
    body["task"] = "monitor_distributions"
    expected = monitor_distributions(body).model_dump(mode="json")
    run = subprocess.run([sys.executable, "-m", "anomalyzer", "monitor-distributions", "-"],
        input=json.dumps(body), capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == expected
    assert analyze({"schema_version": "distribution-v1", **body}).model_dump(mode="json") == expected
    result = handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name="monitor_distributions", arguments={"request": body})))
    assert result["result"]["structuredContent"] == expected
    tool = next(tool for tool in TOOLS if tool["name"] == "monitor_distributions")
    jsonschema.validate(expected, tool["outputSchema"])
    broken = subprocess.run([sys.executable, "-m", "anomalyzer", "compare-distributions", "-"],
        input=json.dumps({**request([0, 1], [0, 1]), "unrecognized": True}), capture_output=True, text=True)
    assert broken.returncode == 2 and not broken.stdout


def test_checked_in_schemas_match_current_models():
    from anomalyzer import DistributionResult, DistributionMonitorResult
    root = Path(__file__).parents[1] / "schemas"
    for name, model in (("distribution-request", DistributionRequest), ("distribution-result", DistributionResult),
                        ("distribution-monitor-request", DistributionMonitorRequest), ("distribution-monitor-result", DistributionMonitorResult)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        assert json.loads((root / f"{name}.schema.json").read_text()) == schema
