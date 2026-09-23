"""Small read-only MCP stdio adapter over the public Python facade.

The adapter intentionally contains no analysis logic. It accepts newline-
delimited JSON-RPC messages, as required by MCP stdio transports, and returns
structured JSON content from the same validated contracts used by Python/CLI.
"""
from __future__ import annotations

import json
import sys

from pydantic import TypeAdapter, ValidationError

from .agent import analyze_series, get_case, replay_policy
from .contracts import (
    ActionPolicy, Case, Dataset, RequestV11, Result, ResultV11, Settings,
)
from .orchestrator import analyze_relationships


TOOLS = [
    {
        "name": "analyze_series",
        "description": (
            "Analyze one numerical series with causal seasonal evidence. Early "
            "evidence is non-triggering and results do not establish a real-world cause."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["dataset"],
            "properties": {
                "dataset": Dataset.model_json_schema(),
                "settings": Settings.model_json_schema(),
            },
        },
        "outputSchema": Result.model_json_schema(),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "analyze_relationships",
        "description": (
            "Analyze two to four declared datasets and explicit relationships "
            "with lineage. This does not discover relationships or prove causality."),
        "inputSchema": RequestV11.model_json_schema(),
        "outputSchema": ResultV11.model_json_schema(),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "get_case",
        "description": (
            "Retrieve a deterministic evidence grouping by case ID. A case is "
            "not an incident declaration or causal explanation."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["result", "case_id"],
            "properties": {
                "result": ResultV11.model_json_schema(),
                "case_id": {"type": "string", "minLength": 1},
            },
        },
        "outputSchema": TypeAdapter(Case | None).json_schema(),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "replay_policy",
        "description": (
            "Re-evaluate deterministic action and notification eligibility over "
            "existing evidence without executing an external action."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["result", "policy"],
            "properties": {
                "result": ResultV11.model_json_schema(),
                "policy": ActionPolicy.model_json_schema(),
            },
        },
        "outputSchema": ResultV11.model_json_schema(),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
]


def _tool_call(name, arguments):
    if name == "analyze_series":
        result = analyze_series(arguments["dataset"], arguments.get("settings"))
    elif name == "analyze_relationships":
        result = analyze_relationships(arguments)
    elif name == "get_case":
        result = get_case(arguments["result"], arguments["case_id"])
    elif name == "replay_policy":
        result = replay_policy(arguments["result"], arguments["policy"])
    else:
        raise ValueError(f"unknown tool: {name}")
    structured = (result.model_dump(mode="json")
                  if hasattr(result, "model_dump") else result)
    return {
        "content": [{"type": "text", "text": json.dumps(structured, allow_nan=False)}],
        "structuredContent": structured,
        "isError": False,
    }


def _modern(message):
    metadata = message.get("params", {}).get("_meta", {})
    return metadata.get("io.modelcontextprotocol/protocolVersion") == "2026-07-28"


def _modern_result(result):
    return {
        "resultType": "complete", **result,
        "_meta": {"io.modelcontextprotocol/serverInfo": {
            "name": "anomalyzer", "version": "0.1.0"}},
    }


def handle(message):
    method = message.get("method")
    request_id = message.get("id")
    modern = _modern(message)
    if method == "server/discover":
        result = _modern_result({
            "supportedVersions": ["2026-07-28"],
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": (
                "Read-only numerical evidence tools. Results do not establish "
                "real-world causality, incidents, or business impact."),
            "ttlMs": 3600000, "cacheScope": "public",
        })
    elif method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        supported = {"2025-03-26", "2025-06-18", "2025-11-25"}
        result = {
            "protocolVersion": requested if requested in supported else "2025-11-25",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "anomalyzer", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
        if modern:
            result.update(ttlMs=3600000, cacheScope="public")
            result = _modern_result(result)
    elif method == "tools/call":
        params = message.get("params", {})
        try:
            result = _tool_call(params.get("name"), params.get("arguments", {}))
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            if modern:
                return {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32602,
                                  "message": f"invalid tool input: {exc}"}}
            result = {
                "content": [{"type": "text", "text": f"Invalid tool input: {exc}"}],
                "isError": True,
            }
        if modern:
            result = _modern_result(result)
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return None
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        message = None
        try:
            message = json.loads(line)
            response = handle(message)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            response = {
                "jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32602, "message": f"invalid request: {exc}"},
            }
        except Exception as exc:
            response = {
                "jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32603,
                          "message": f"internal error: {type(exc).__name__}: {exc}"},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":"),
                                        allow_nan=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
