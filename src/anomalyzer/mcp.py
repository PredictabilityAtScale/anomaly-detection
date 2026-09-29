"""Agent-facing MCP stdio adapter over the public Python analysis core.

The adapter intentionally contains no analysis logic. It accepts newline-
delimited JSON-RPC messages, as required by MCP stdio transports, and provides
compact views over session-cached results from the same core used by Python/CLI.
"""
from __future__ import annotations

import json
import sys
from collections import OrderedDict

from pydantic import ValidationError

from .agent import analyze_relationships, analyze_series, get_case, replay_policy
from .contracts import (
    Contract, Request, RequestV11,
)
from .mcp_views import get_evidence, list_findings, summarize
from .recipes import analyze


class AnalyzeRequestArguments(Contract):
    request: Request | RequestV11


SERVER_INSTRUCTIONS = (
    "Use analyze to assess a canonical request, list_findings to browse its "
    "bounded findings, and get_evidence to inspect one finding. Results are "
    "cached only for this server session; use the returned run_id. "
    "Write user-facing summaries for analysts without statistical training: "
    "first say what changed, when, versus the expected level, how reliable the "
    "comparison is, and what to check next. Put scores and rule names in "
    "supporting detail. Report the run status before interpreting detections. "
    "Only calibrated point "
    "triggers are point-anomaly flags; observations groups adjacent flags into "
    "episodes. anomaly_patterns contains point runs and residual-rule findings, "
    "which may overlap and are not independent incidents. Nelson Rules 2, 5, and "
    "6 and CUSUM suggest a possible shift in residual location even with no point "
    "flag; they do not establish a change in the full distribution. Describe the "
    "rule, interval, direction, first detection index, and material limitations. "
    "Report the readiness status and reasons in plain "
    "language as a baseline-quality check, not measured alert accuracy. "
    "For recurring monitoring, distinguish new findings from overlapping or "
    "previously reported evidence using caller-held state. Policy eligibility "
    "does not check detection readiness and is not an action recommendation. "
    "The server does not schedule runs, deliver alerts, or execute actions. "
    "Do not infer cause, business impact, or normality from absent findings."
)


TOOLS = [
    {
        "name": "analyze",
        "description": (
            "Analyze a schema-1.0 or schema-1.1 request. Returns a compact "
            "assessment, readiness and data-quality checks, a preview of findings, "
            "and a run_id for drilldown. The full result stays in this MCP session. "
            "No finding establishes cause, incident status, or action authority."),
        "inputSchema": AnalyzeRequestArguments.model_json_schema(),
        "outputSchema": {
            "type": "object",
            "required": ["run_id", "schema_version", "status", "headline",
                         "finding_count", "findings_preview", "readiness",
                         "data_quality", "next_step", "limitations"],
            "properties": {
                "run_id": {"type": "string"}, "schema_version": {"type": "string"},
                "status": {"type": "string"}, "headline": {"type": "string"},
                "finding_count": {"type": "integer"},
                "findings_preview": {"type": "array", "items": {"type": "object"}},
                "readiness": {"type": "array", "items": {"type": "object"}},
                "data_quality": {"type": "array", "items": {"type": "object"}},
                "next_step": {"type": "string"}, "limitations": {"type": "array"},
            },
            "additionalProperties": True,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "list_findings",
        "description": (
            "Page through cases, early candidates, point episodes, residual patterns, and data-quality "
            "issues from a prior analyze call. These types can overlap and are not "
            "a count of separate incidents. The run_id lasts only for this session."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["run_id"],
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
                "cursor": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                          "default": 20},
            },
        },
        "outputSchema": {
            "type": "object", "additionalProperties": True,
            "required": ["run_id", "total", "findings", "next_cursor"],
            "properties": {
                "run_id": {"type": "string"}, "total": {"type": "integer"},
                "findings": {"type": "array", "items": {"type": "object"}},
                "next_cursor": {"type": ["integer", "null"]},
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "get_evidence",
        "description": (
            "Inspect one finding by run_id and finding_id. Returns the numerical "
            "record, relevant assessments and lineage, readiness, limitations, "
            "and a page of source samples. This does not establish cause or impact."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["run_id", "finding_id"],
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
                "finding_id": {"type": "string", "minLength": 1},
                "cursor": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                          "default": 50},
            },
        },
        "outputSchema": {
            "type": "object", "additionalProperties": True,
            "required": ["run_id", "finding", "record", "sample_count",
                         "samples", "next_cursor", "readiness"],
            "properties": {
                "run_id": {"type": "string"}, "finding": {"type": "object"},
                "record": {"type": "object"}, "sample_count": {"type": "integer"},
                "samples": {"type": "array", "items": {"type": "object"}},
                "next_cursor": {"type": ["integer", "null"]},
                "readiness": {"type": "array", "items": {"type": "object"}},
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
]


MAX_CACHED_RUNS = 8
MAX_CACHED_BYTES = 64_000_000
_RUNS = OrderedDict()
_RUN_BYTES = 0


def _remember(result):
    global _RUN_BYTES
    size = len(json.dumps(result, allow_nan=False).encode("utf-8"))
    if size > MAX_CACHED_BYTES:
        raise ValueError("analysis result exceeds the MCP session cache limit")
    if result["run_id"] in _RUNS:
        _RUN_BYTES -= _RUNS.pop(result["run_id"])[1]
    _RUNS[result["run_id"]] = (result, size)
    _RUN_BYTES += size
    while len(_RUNS) > MAX_CACHED_RUNS or (
            _RUN_BYTES > MAX_CACHED_BYTES and len(_RUNS) > 1):
        _, (_, evicted_size) = _RUNS.popitem(last=False)
        _RUN_BYTES -= evicted_size


def _cached(run_id):
    if run_id not in _RUNS:
        raise ValueError("run_id not found in this MCP session; analyze again")
    return _RUNS[run_id][0]


def _compact_result(structured, message):
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": structured, "isError": False,
    }


def _tool_call(name, arguments):
    if name == "analyze":
        result = analyze(AnalyzeRequestArguments.model_validate(arguments).request)
        full = result.model_dump(mode="json")
        _remember(full)
        summary = summarize(full)
        return _compact_result(
            summary, f"{summary['headline']} Run {summary['run_id']}; "
            f"{summary['finding_count']} finding(s). Use list_findings for details.")
    if name == "list_findings":
        run_id = arguments["run_id"]
        page = list_findings(_cached(run_id), arguments.get("cursor", 0),
                             arguments.get("limit", 20))
        return _compact_result(
            page, f"{len(page['findings'])} of {page['total']} findings for "
            f"run {run_id}.")
    if name == "get_evidence":
        run_id = arguments["run_id"]
        detail = get_evidence(_cached(run_id), arguments["finding_id"],
                              arguments.get("cursor", 0),
                              arguments.get("limit", 50))
        return _compact_result(
            detail, f"{detail['finding']['headline']} "
            f"{detail['sample_count']} supporting sample(s) available.")
    if name == "analyze_request":
        result = analyze(AnalyzeRequestArguments.model_validate(arguments).request)
    elif name == "analyze_series":
        result = analyze_series(arguments["dataset"], arguments.get("settings"),
                                arguments.get("context"))
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
            "instructions": SERVER_INSTRUCTIONS,
            "ttlMs": 3600000, "cacheScope": "public",
        })
    elif method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        supported = {"2025-03-26", "2025-06-18", "2025-11-25"}
        result = {
            "protocolVersion": requested if requested in supported else "2025-11-25",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "anomalyzer", "version": "0.1.0"},
            "instructions": SERVER_INSTRUCTIONS,
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
