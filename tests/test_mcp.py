import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from anomalyzer import analyze
from anomalyzer.agent import analyze_relationships, analyze_series
from anomalyzer.mcp import TOOLS, handle


def stable_result(value):
    """Remove execution identity/timing while retaining semantic output."""
    if isinstance(value, dict):
        return {
            key: stable_result(item) for key, item in value.items()
            if key not in {"run_id", "runtime_seconds"}
        }
    if isinstance(value, list):
        return [stable_result(item) for item in value]
    return value


def test_mcp_lists_read_only_tools():
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [tool["name"] for tool in response["result"]["tools"]] == [
        "analyze", "list_findings", "get_evidence"]
    assert all(tool["annotations"]["readOnlyHint"] for tool in TOOLS)
    assert all("outputSchema" in tool for tool in TOOLS)
    assert len(json.dumps(TOOLS)) < 25_000
    assert "compact" in TOOLS[0]["description"]
    assert "overlap" in TOOLS[1]["description"]
    assert "lineage" in TOOLS[2]["description"]


def test_mcp_tool_call_returns_structured_content():
    request = {"schema_version": "1.0", "datasets": [{"values": [1, 2, 3]}]}
    response = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })
    assert response["id"] == 2
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["schema_version"] == "1.0"
    assert result["structuredContent"]["status"] == "insufficient_history"
    assert len(result["content"][0]["text"]) < 500
    assert "run_id" in result["structuredContent"]


def test_agent_can_drill_into_relationship_case():
    root = Path(__file__).parents[1]
    request = json.loads((root / "examples" / "agentic" / "conversion.json").read_text())
    response = handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })["result"]["structuredContent"]
    assert response["headline"].startswith("relationship conversion:")
    assert response["finding_count"] > 0
    assert response["findings_preview"][0]["kind"] == "case"
    assert len(json.dumps(response)) < 10_000
    run_id = response["run_id"]
    page = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "list_findings", "arguments": {
            "run_id": run_id, "limit": 1}},
    })["result"]["structuredContent"]
    assert page["total"] == response["finding_count"]
    assert page["next_cursor"] == 1
    finding_id = page["findings"][0]["id"]
    detail = handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_evidence", "arguments": {
            "run_id": run_id, "finding_id": finding_id}},
    })["result"]["structuredContent"]
    assert detail["assessments"][0]["observed"] == pytest.approx(8 / 130)
    assert detail["assessments"][0]["baseline"]["expected"] == pytest.approx(0.1)
    assert detail["lineage"][0]["source_indexes"] == {
        "orders": 14, "qualified_visits": 14}
    assert detail["readiness"][0]["status"] == "not_assessed"
    assert detail["sample_count"] == 1


def test_agent_sees_unavailable_latest_evidence():
    root = Path(__file__).parents[1]
    request = json.loads((root / "examples" / "agentic" / "incomplete-usage.json").read_text())
    response = handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })["result"]["structuredContent"]
    assert response["status"] == "partial"
    assert "unavailable" in response["headline"]
    assert response["findings_preview"][0]["kind"] == "quality"
    detail = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_evidence", "arguments": {
            "run_id": response["run_id"],
            "finding_id": response["findings_preview"][0]["id"]}},
    })["result"]["structuredContent"]
    assert detail["record"]["status"] == "insufficient_evidence"
    assert detail["sample_count"] == 0
    assert detail["lineage"][-1]["unavailable_reason"]


def test_short_history_candidate_is_visible_without_a_case():
    request = {
        "schema_version": "1.1",
        "datasets": [{
            "id": "series", "entity": {"account": "example"},
            "timestamps": [f"2026-01-0{day}T00:00:00Z" for day in range(1, 5)],
            "values": [10, 12, 11, 20], "frequency": "1d", "units": "units",
        }],
        "config": {"season_length": 1, "training_size": 4,
                   "calibration_size": 3, "trend": "none"},
    }
    summary = handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })["result"]["structuredContent"]
    candidate = next(item for item in summary["findings_preview"]
                     if item["kind"] == "candidate")
    assert candidate["maturity"] == "early"
    assert "prior range" in candidate["headline"]
    detail = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_evidence", "arguments": {
            "run_id": summary["run_id"], "finding_id": candidate["id"]}},
    })["result"]["structuredContent"]
    assert detail["record"]["observed"] == 20
    assert detail["record"]["criterion_met"] is False
    assert detail["record"]["not_established"]


def test_get_evidence_pages_pattern_samples():
    root = Path(__file__).parents[1]
    request = json.loads((root / "examples" / "location_shift_up.json").read_text())
    summary = handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })["result"]["structuredContent"]
    listing = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "list_findings", "arguments": {
            "run_id": summary["run_id"]}},
    })["result"]["structuredContent"]
    pattern = next(item for item in listing["findings"] if item["kind"] == "pattern")
    detail = handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_evidence", "arguments": {
            "run_id": summary["run_id"], "finding_id": pattern["id"],
            "limit": 1}},
    })["result"]["structuredContent"]
    assert detail["sample_count"] > 1
    assert len(detail["samples"]) == 1
    assert detail["next_cursor"] == 1
    assert "evidence_refs" not in detail["record"]


@pytest.mark.parametrize("fixture", ["spike.json", "agentic/conversion.json"])
def test_canonical_request_matches_python_cli_and_mcp(fixture):
    root = Path(__file__).parents[1]
    request = json.loads((root / "examples" / fixture).read_text())
    direct = analyze(request).model_dump(mode="json")
    cli = subprocess.run(
        [sys.executable, "-m", "anomalyzer", "analyze", "-",
         "--input-format", "json", "--format", "json"],
        input=json.dumps(request), text=True, capture_output=True, timeout=30)
    assert cli.returncode == 0, cli.stderr
    call = handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "analyze_request", "arguments": {"request": request}},
    })["result"]
    assert call["isError"] is False
    agent_call = handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {"request": request}},
    })["result"]
    canonical_tool = TOOLS[0]
    jsonschema.Draft202012Validator.check_schema(canonical_tool["inputSchema"])
    jsonschema.Draft202012Validator.check_schema(canonical_tool["outputSchema"])
    jsonschema.validate({"request": request}, canonical_tool["inputSchema"])
    jsonschema.validate(agent_call["structuredContent"], canonical_tool["outputSchema"])
    assert agent_call["structuredContent"]["schema_version"] == request["schema_version"]
    assert stable_result(direct) == stable_result(json.loads(cli.stdout))
    assert stable_result(direct) == stable_result(call["structuredContent"])


def test_single_series_context_matches_python_cli_and_mcp():
    root = Path(__file__).parents[1]
    request = json.loads((root / "examples" / "spike.json").read_text())
    request["context"] = {
        "as_of": request["datasets"][0]["timestamps"][70],
        "known_events": ["Reviewed deployment"],
    }
    direct = analyze_series(
        request["datasets"][0], request["config"], request["context"]
    ).model_dump(mode="json")
    cli = subprocess.run(
        [sys.executable, "-m", "anomalyzer", "analyze", "-",
         "--input-format", "json", "--format", "json"],
        input=json.dumps(request), text=True, capture_output=True, timeout=30)
    assert cli.returncode == 0, cli.stderr
    mcp = handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "analyze_series", "arguments": {
            "dataset": request["datasets"][0], "settings": request["config"],
            "context": request["context"]}},
    })["result"]["structuredContent"]
    assert direct["data_quality"]["observation_count"] == 71
    assert stable_result(direct) == stable_result(json.loads(cli.stdout))
    assert stable_result(direct) == stable_result(mcp)


def test_relationship_semantics_match_python_cli_and_mcp():
    root = Path(__file__).parents[1]
    request = json.loads(
        (root / "examples" / "agentic" / "conversion.json").read_text())
    direct = analyze_relationships(request).model_dump(mode="json")
    cli = subprocess.run(
        [sys.executable, "-m", "anomalyzer", "analyze", "-",
         "--input-format", "json", "--format", "json"],
        input=json.dumps(request), text=True, capture_output=True, timeout=30)
    assert cli.returncode == 0, cli.stderr
    mcp = handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "analyze_relationships", "arguments": request},
    })["result"]["structuredContent"]
    assert stable_result(direct) == stable_result(json.loads(cli.stdout))
    assert stable_result(direct) == stable_result(mcp)


def test_mcp_invalid_tool_input_is_a_tool_error():
    response = handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "analyze", "arguments": {}},
    })
    assert response["result"]["isError"] is True
    missing = handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "list_findings", "arguments": {"run_id": "missing"}},
    })
    assert missing["result"]["isError"] is True


def test_mcp_stdio_legacy_handshake_and_tool_listing():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    process = subprocess.run(
        [sys.executable, "-m", "anomalyzer.mcp"],
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert "Nelson Rules 2, 5, and 6" in responses[0]["result"]["instructions"]
    assert "readiness status and reasons" in responses[0]["result"]["instructions"]
    assert len(responses[1]["result"]["tools"]) == 3


def test_mcp_modern_discovery_and_stateless_tool_listing():
    metadata = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    discovery = handle({
        "jsonrpc": "2.0", "id": "d", "method": "server/discover",
        "params": {"_meta": metadata}})
    assert discovery["result"]["supportedVersions"] == ["2026-07-28"]
    assert discovery["result"]["resultType"] == "complete"
    assert "anomaly_patterns" in discovery["result"]["instructions"]
    listing = handle({
        "jsonrpc": "2.0", "id": "l", "method": "tools/list",
        "params": {"_meta": metadata}})
    assert listing["result"]["resultType"] == "complete"
    assert listing["result"]["cacheScope"] == "public"
    assert len(listing["result"]["tools"]) == 3
