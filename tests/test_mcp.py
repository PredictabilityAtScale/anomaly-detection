import json
import subprocess
import sys
from pathlib import Path

from anomalyzer.agent import analyze_relationships
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


def test_mcp_lists_four_read_only_tools():
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [tool["name"] for tool in response["result"]["tools"]] == [
        "analyze_series", "analyze_relationships", "get_case", "replay_policy"]
    assert all(tool["annotations"]["readOnlyHint"] for tool in TOOLS)
    assert all("outputSchema" in tool for tool in TOOLS)


def test_mcp_tool_call_returns_structured_content():
    response = handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "analyze_series",
                   "arguments": {"dataset": {"values": [1, 2, 3]}}},
    })
    assert response["id"] == 2
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["schema_version"] == "1.0"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


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
        "params": {"name": "analyze_series", "arguments": {}},
    })
    assert response["result"]["isError"] is True


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
    assert len(responses[1]["result"]["tools"]) == 4


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
    listing = handle({
        "jsonrpc": "2.0", "id": "l", "method": "tools/list",
        "params": {"_meta": metadata}})
    assert listing["result"]["resultType"] == "complete"
    assert listing["result"]["cacheScope"] == "public"
    assert len(listing["result"]["tools"]) == 4
