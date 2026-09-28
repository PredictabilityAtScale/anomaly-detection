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


SERVER_INSTRUCTIONS = (
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
    "Report methods[].diagnostics.detection_readiness and its reasons in plain "
    "language as a baseline-quality check, not measured alert accuracy. "
    "For recurring monitoring, distinguish new findings from overlapping or "
    "previously reported evidence using caller-held state. Policy eligibility "
    "does not check detection readiness and is not an action recommendation. "
    "The server does not schedule runs, deliver alerts, or execute actions. "
    "Do not infer cause, business impact, or normality from absent findings."
)


def _output_schema(model, descriptions):
    """Explain ambiguous result fields without changing the public contracts."""
    schema = model.model_json_schema()
    for field, description in descriptions.items():
        schema["properties"][field]["description"] = description
    return schema


TOOLS = [
    {
        "name": "analyze_series",
        "description": (
            "Analyze one ordered numerical series against a causal seasonal/trend "
            "reference. Use methods[].evidence for individual scores and point "
            "flags, observations for point-anomaly episodes, and anomaly_patterns "
            "for overlapping Nelson, CUSUM, moving-range, and point-run findings. "
            "A pattern can indicate a possible shift without any point flag. "
            "Report diagnostics.detection_readiness, status, and limitations; "
            "readiness is not measured alert accuracy. No finding establishes a cause or incident."),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["dataset"],
            "properties": {
                "dataset": Dataset.model_json_schema(),
                "settings": Settings.model_json_schema(),
            },
        },
        "outputSchema": _output_schema(Result, {
            "methods": "Per-sample evidence and diagnostics.detection_readiness, a training/calibration reference-quality check.",
            "observations": "Point-anomaly episodes: consecutive calibrated point flags, including singletons.",
            "anomaly_patterns": "Overlapping point-run and residual-rule findings; a pattern may exist without a point episode.",
            "limitations": "Model and detector limits that qualify any interpretation.",
        }),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "analyze_relationships",
        "description": (
            "Analyze one to four declared datasets and optional explicit relationships "
            "with lineage. Each result retains point-anomaly episodes and pattern "
            "findings. Cases group calibrated point departures or explicit rule "
            "violations; Nelson-only and CUSUM-only findings do not create cases. "
            "Check method detection_readiness, maturity, policy eligibility, "
            "data quality, and limitations. Eligibility does not check readiness "
            "or establish that an automated action is appropriate. "
            "This does not discover relationships or prove causality."),
        "inputSchema": RequestV11.model_json_schema(),
        "outputSchema": _output_schema(ResultV11, {
            "dataset_results": "Dataset methods include detection readiness; episodes and pattern findings may overlap.",
            "relationship_results": "Relationship methods include detection readiness; derived and source findings may be correlated.",
            "cases": "Evidence groupings from point departures or explicit rule violations, not from pattern-only findings.",
            "limitations": "Limits on the scope and reliability of the analysis.",
        }),
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "get_case",
        "description": (
            "Retrieve a deterministic evidence grouping by case ID. A case is "
            "formed from point departures or explicit rule violations, not "
            "pattern-only findings. It is not an incident declaration or causal explanation."),
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
            "existing point departures and explicit rule violations without "
            "recomputing detections or executing an external action. Pattern-only "
            "findings do not become cases or eligible actions. Eligibility does "
            "not check detection readiness; callers must evaluate that diagnostic "
            "and their own alert or action policy separately."),
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
