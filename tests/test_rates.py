"""Independent integer-table references and sparse rate qualification."""
from fractions import Fraction
from math import comb
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import (
    RateRequest, RateResult, RateMonitorRequest, RateMonitorResult,
    analyze, compare_rates, monitor_rates,
)
from anomalyzer.budget import RuntimeBudget
from anomalyzer.mcp import TOOLS, handle
from anomalyzer.rates import _fisher


def sample(name, successes, trials, **extra):
    return dict(id=name, successes=successes, trials=trials, **extra)


def request(a=10, n=100, c=20, m=100, **config):
    return dict(schema_version="rate-v1", entity={"site": "test"},
        reference={"samples": [sample("reference", a, n)]},
        current={"samples": [sample("current", c, m)]},
        assume_independent_trials=True, config=config)


def monitor(samples, **extra):
    return dict(schema_version="rate-v1", task="monitor_rates", monitor_id="test", entity={"site": "test"},
        samples=samples, order="trusted_sequence", assume_independent_trials=True,
        reference_size=4, window_sizes=[1, 4], max_looks=16, **extra)


def test_exact_test_matches_independent_integer_tables_exhaustively():
    budget = RuntimeBudget(30)
    for n in range(1, 9):
        for m in range(1, 9):
            for a in range(n+1):
                for c in range(m+1):
                    k = a+c
                    weights = [comb(k, x)*comb(n+m-k, n-x)
                               for x in range(max(0, k-m), min(n, k)+1)]
                    observed = comb(k, a)*comb(n+m-k, n-a)
                    expected = Fraction(sum(w for w in weights if w <= observed), sum(weights))
                    p, _ = _fisher(a, n, c, m, 100, budget)
                    assert p == pytest.approx(float(expected), abs=1e-12)


def test_published_fisher_example_and_symmetries():
    # SciPy Fisher documentation: [[6,2],[1,4]], probability-ordered two-sided.
    result = compare_rates(request(6, 8, 1, 5))
    assert result.p_value == pytest.approx(0.10256410256410256)
    assert compare_rates(request(1, 5, 6, 8)).p_value == pytest.approx(result.p_value)
    assert compare_rates(request(2, 8, 4, 5)).p_value == pytest.approx(result.p_value)
    assert compare_rates(request(1, 5, 6, 8)).effect > 0
    assert result.effect < 0


@pytest.mark.parametrize("a,n,c,m", [(0, 10000, 2, 10000), (50, 100, 40, 1000),
                                    (400, 1000, 500, 1000), (0, 1_000_000_000, 1, 20)])
def test_large_and_unbalanced_tables_match_independent_combinations(a, n, c, m):
    k = a+c
    # Exact integer enumeration is independent of the production recurrence.
    weights = [comb(k, x)*comb(n+m-k, n-x) for x in range(max(0, k-m), min(n, k)+1)]
    observed = comb(k, a)*comb(n+m-k, n-a)
    expected = Fraction(sum(w for w in weights if w <= observed), sum(weights))
    result = compare_rates(request(a, n, c, m))
    assert result.p_value == pytest.approx(float(expected), rel=1e-10, abs=1e-250)


def test_same_percentage_change_has_different_weight_at_different_volumes():
    sparse = compare_rates(request(4, 20, 2, 20))
    busy = compare_rates(request(4000, 20000, 2000, 20000))
    assert sparse.effect == pytest.approx(busy.effect)
    assert sparse.status == busy.status == "completed"
    assert not sparse.change_detected and busy.change_detected
    sw = sparse.current["interval"]["upper"]-sparse.current["interval"]["lower"]
    bw = busy.current["interval"]["upper"]-busy.current["interval"]["lower"]
    assert sw > 20*bw
    assert sparse.current["successes"] == 2 and sparse.current["trials"] == 20


@pytest.mark.parametrize("a,c", [(0, 0), (5, 5), (0, 5), (5, 0)])
def test_zero_all_success_and_tiny_samples_keep_bounded_uncertainty(a, c):
    result = compare_rates(request(a, 5, c, 5))
    assert result.status == "completed"
    assert result.current["low_support"]
    for population in (result.reference, result.current):
        interval = population["interval"]
        assert 0 <= interval["lower"] < interval["upper"] <= 1
    assert result.p_value == pytest.approx(1 if a == c else 2/252)


@pytest.mark.parametrize("changes", [dict(successes=1.0), dict(successes=True), dict(successes=-1),
    dict(trials=3.0), dict(trials=False), dict(successes=4, trials=3), dict(successes=1, trials=0)])
def test_invalid_bounded_counts_rejected(changes):
    body = request()
    body["current"]["samples"][0].update(changes)
    with pytest.raises(ValidationError):
        compare_rates(body)


@pytest.mark.parametrize("changes", [dict(successes=0, trials=0), dict(trials=None),
                                      dict(successes=None), dict(complete=False)])
def test_no_exposure_unknown_and_incomplete_counts_are_not_negative_findings(changes):
    body = request()
    body["current"]["samples"][0].update(changes)
    result = compare_rates(body)
    assert result.status == "insufficient_history"
    assert result.current["rate"] is None and result.current["interval"] is None
    assert result.p_value is None and not result.change_detected


def test_pooled_rate_uses_trials_not_unweighted_bucket_rates():
    body = request(10, 100, 0, 1)
    body["current"]["samples"].append(sample("large", 90, 99))
    result = compare_rates(body)
    assert result.current["rate"] == 0.9
    assert result.current["successes"] == 90 and result.current["trials"] == 100
    body["current"]["samples"].append(sample("missing", None, 10))
    assert compare_rates(body).current["rate"] is None


def test_finite_reference_uncertainty_and_explicit_rule_are_separate():
    # A zero observed baseline is not proof that future successes are impossible.
    assert not compare_rates(request(0, 1, 1, 1)).change_detected
    body = request(4, 20, 2, 20)
    body.update(assume_independent_trials=False, limits=[dict(id="minimum", operator="lt", threshold=0.15)])
    result = compare_rates(body)
    assert result.status == "descriptive" and result.p_value is None
    assert not result.change_detected
    assert result.rate_limit_violations[0]["evidence_kind"] == "exact_caller_rule"
    kinds = {o["kind"] for o in result.observations}
    assert {"rate_comparison", "unassessed_statistical_comparison", "caller_rate_limit_violation"} <= kinds
    body["reference"]["samples"][0].update(successes=None)
    assert compare_rates(body).rate_limit_violations


def test_testing_family_effect_gate_limits_and_support():
    one = compare_rates(request(0, 5, 5, 5))
    family = compare_rates(request(0, 5, 5, 5, max_comparisons=10))
    assert one.change_detected and not family.change_detected
    assert family.adjusted_p_value == pytest.approx(one.p_value*10)
    tiny_effect = compare_rates(request(100, 10000, 200, 10000, min_effect=0.1))
    assert tiny_effect.statistical_change and not tiny_effect.change_detected
    limited = compare_rates(request(10, 100, 30, 100, max_tables=1))
    assert limited.status == "resolution_limited" and limited.p_value is None
    assert compare_rates(request(10, 100, 20, 100, min_current_trials=101)).status == "insufficient_history"


def test_duplicate_and_overlapping_populations_rejected():
    body = request()
    body["current"]["samples"][0]["id"] = "reference"
    with pytest.raises(ValidationError, match="disjoint"):
        compare_rates(body)


def test_monitor_pools_sparse_changes_without_future_or_reference_contamination():
    samples = [sample(str(i), 0 if i < 4 else 1, 1) for i in range(20)]
    body = monitor(samples)
    full = monitor_rates(body)
    prefix = monitor_rates({**body, "samples": samples[:12]})
    assert full.evaluations[:len(prefix.evaluations)] == prefix.evaluations
    assert full.reference["successes"] == 0 and full.reference["trials"] == 4
    assert full.testing["max_comparisons"] == 32
    assert full.evaluations[1]["result"] is None  # four-bucket window not available yet
    supported = [r for r in full.evaluations if r["result"] is not None]
    assert all(r["current_start_index"] >= 4 for r in supported)
    assert all(r["result"]["reference"] == full.reference for r in supported)
    strong = [sample(str(i), 2 if i < 4 else 9, 10) for i in range(20)]
    detected = monitor_rates(monitor(strong)).first_detection
    assert detected and detected["index"] >= 4
    assert detected["index"] >= detected["current_start_index"]


def test_monitor_preserves_unknown_and_incomplete_windows_and_rejects_bad_order():
    samples = [sample(str(i), 1, 5) for i in range(12)]
    samples[7].update(successes=None)
    samples[9].update(complete=False)
    result = monitor_rates(monitor(samples))
    for row in result.evaluations:
        if row["result"] and any(row["current_start_index"] <= i <= row["index"] for i in (7, 9)):
            assert row["status"] == "insufficient_history" and not row["change_detected"]
    body = monitor(samples)
    body["order"] = "timestamp"
    with pytest.raises(ValidationError, match="trusted_sequence"):
        monitor_rates(body)
    for s in samples:
        s["timestamp"] = "2026-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="tied"):
        monitor_rates(body)
    body["config"] = dict(max_comparisons=2)
    body["order"] = "trusted_sequence"
    with pytest.raises(ValidationError, match="monitor owns"):
        monitor_rates(body)


def test_budget_failure_preserves_counts_and_unassessed_status(monkeypatch):
    def exhausted(self):
        raise TimeoutError("fixture runtime budget")
    monkeypatch.setattr(RuntimeBudget, "check", exhausted)
    result = compare_rates(request())
    assert result.status == "budget_exceeded" and result.current["trials"] == 100
    assert result.p_value is None and not result.change_detected
    replay = monitor_rates(monitor([sample(str(i), 1, 5) for i in range(12)]))
    assert replay.status == "partial" and replay.first_detection is None


@pytest.mark.parametrize("task,body,model,output", [
    ("compare_rates", request(), RateRequest, RateResult),
    ("monitor_rates", monitor([sample(str(i), 1, 5) for i in range(12)]), RateMonitorRequest, RateMonitorResult),
])
def test_public_python_cli_mcp_and_schemas_agree(task, body, model, output):
    function = compare_rates if task == "compare_rates" else monitor_rates
    expected = function(body).model_dump(mode="json")
    assert analyze(body).model_dump(mode="json") == expected
    run = subprocess.run([sys.executable, "-m", "anomalyzer", task.replace("_", "-"), "-"],
        input=json.dumps(body), capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == expected
    rpc = handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name=task, arguments={"request": body})))
    summary = rpc["result"]["structuredContent"]
    assert summary["schema_version"] == "rate-v1" and summary["status"] == expected["status"]
    assert "evaluations" not in summary and "_rate_request" not in summary
    assert len(json.dumps(summary)) < 8000
    page = handle(dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(name="list_findings",
        arguments={"run_id": summary["run_id"], "limit": 1})))["result"]["structuredContent"]
    finding = page["findings"][0]
    detail = handle(dict(jsonrpc="2.0", id=3, method="tools/call", params=dict(name="get_evidence",
        arguments={"run_id": summary["run_id"], "finding_id": finding["id"], "limit": 1})))["result"]["structuredContent"]
    raw = expected if task == "compare_rates" else expected["evaluations"][0]["result"]
    assert detail["record"]["p_value"] == raw["p_value"]
    assert detail["record"]["current"]["trials"] == raw["current"]["trials"]
    assert detail["samples"][0]["role"] == "reference"
    assert detail["next_cursor"] == 1
    tool = next(t for t in TOOLS if t["name"] == task)
    jsonschema.validate({"request": body}, tool["inputSchema"])
    jsonschema.validate(summary, tool["outputSchema"])
    root = Path(__file__).parents[1]/"schemas"
    prefix = "rate" if task == "compare_rates" else "rate-monitor"
    for suffix, contract, value in (("request", model, body), ("result", output, expected)):
        schema = contract.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        assert json.loads((root/f"{prefix}-{suffix}.schema.json").read_text()) == schema
        jsonschema.validate(value, schema)
    readable = subprocess.run([sys.executable, "-m", "anomalyzer", task.replace("_", "-"), "-", "--format", "text"],
        input=json.dumps(body), capture_output=True, text=True, check=True)
    assert "Rate" in readable.stdout


def test_context_is_preserved_without_changing_numeric_inference_and_sources_are_paged():
    from anomalyzer.mcp import _tool_call
    body = request(4, 20, 2, 20)
    plain = compare_rates(body)
    body["context"] = dict(concern="Is a new customer's conversion change supported?", known_events=["New customer"])
    contextual = compare_rates(body)
    assert contextual.p_value == plain.p_value and contextual.change_detected == plain.change_detected
    summary = _tool_call("compare_rates", {"request": body})["structuredContent"]
    assert summary["context"]["concern"] == body["context"]["concern"]
    detail = _tool_call("get_evidence", dict(run_id=summary["run_id"], finding_id="rate:0", cursor=1, limit=1))["structuredContent"]
    assert detail["samples"] == [dict(role="current", id="current", successes=2, trials=20, timestamp=None, complete=True)]
    assert detail["next_cursor"] is None
    assert detail["record"]["observations"][0]["criterion_met"] is False
