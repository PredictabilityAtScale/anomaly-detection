"""Compact contextual rate evidence with bounded source-count drilldown."""
from typing import Literal

from .contracts import Contract


class RateSummary(Contract):
    run_id: str
    schema_version: Literal["rate-v1"] = "rate-v1"
    task: str
    status: str
    entity: dict
    context: dict
    headline: str
    comparison_count: int
    significant_comparison_count: int
    latest: dict | None
    first_detection: dict | None
    findings_preview: list[dict]
    testing: dict
    limitations: list[str]
    next_step: str


def _comparisons(result):
    if result["task"] == "compare_rates":
        return [dict(index=None, window_size=None, status=result["status"], result=result,
                     change_detected=result["change_detected"])]
    return result["evaluations"]


def _finding(offset, row):
    return dict(id=f"rate:{offset}", kind="rate_comparison", index=row["index"],
                timestamp=row.get("timestamp"), window_size=row["window_size"], status=row["status"],
                criterion_met=row["change_detected"],
                headline=f"Rate comparison: {row['status']}; statistical criterion met: {row['change_detected']}")


def _population(population):
    keys = ("successes", "trials", "rate", "available", "low_support", "interval", "time_extent")
    return {**{key: population[key] for key in keys},
            "unknown_count": len(population["unknown_ids"]), "incomplete_count": len(population["incomplete_ids"])}


def summarize_rates(result):
    rows = _comparisons(result)
    findings = [_finding(i, row) for i, row in enumerate(rows)]
    significant = [f for f in findings if f["criterion_met"]]
    latest = rows[-1].get("result") if rows else None
    latest_view = None if latest is None else dict(status=latest["status"],
        reference=_population(latest["reference"]), current=_population(latest["current"]),
        effect=latest["effect"], p_value=latest["p_value"], threshold=latest["threshold"],
        observations=latest["observations"])
    return RateSummary(run_id=result["run_id"], task=result["task"], status=result["status"],
        entity=result["entity"], context=result["context"],
        headline=f"{len(significant)} rate comparison(s) met the statistical and effect criteria; alert decision remains with caller.",
        comparison_count=len(rows), significant_comparison_count=len(significant), latest=latest_view,
        first_detection=result.get("first_detection"), findings_preview=(significant[:3] or findings[-3:]),
        testing=result["testing"], limitations=result["limitations"],
        next_step="Use list_findings and get_evidence with this run_id to inspect comparisons and source counts; obtain additional context/data before deciding whether to alert.").model_dump(mode="json")


def list_rate_findings(result, cursor=0, limit=20):
    rows = _comparisons(result)
    end = min(cursor+limit, len(rows))
    return dict(run_id=result["run_id"], total=len(rows),
        findings=[_finding(i, rows[i]) for i in range(cursor, end)],
        next_cursor=end if end < len(rows) else None,
        note="Includes significant, non-significant and unassessed comparisons. Overlapping windows are not independent incidents or alert decisions.")


def get_rate_evidence(result, finding_id, cursor=0, limit=50):
    rows = _comparisons(result)
    matches = [i for i in range(len(rows)) if f"rate:{i}" == finding_id]
    if not matches:
        raise ValueError(f"finding not found: {finding_id}")
    offset = matches[0]
    row = rows[offset]
    record = row.get("result")
    request = result["_rate_request"]
    if result["task"] == "compare_rates":
        reference, current = request["reference"]["samples"], request["current"]["samples"]
    else:
        reference = request["samples"][:request["reference_size"]]
        current = request["samples"][max(request["reference_size"], row["current_start_index"]):row["index"]+1]
    sources = [dict(role=role, **sample) for role, samples in (("reference", reference), ("current", current)) for sample in samples]
    # Full ID arrays stay in cache; large source populations are paginated.
    if record is not None:
        record = {**{k: v for k, v in record.items() if not k.startswith("_") and k not in ("reference", "current", "run_id")},
                  "reference": _population(record["reference"]), "current": _population(record["current"])}
    end = min(cursor+limit, len(sources))
    return dict(run_id=result["run_id"], finding=_finding(offset, row), record=record,
        context=result["context"], entity=result["entity"], sample_count=len(sources), samples=sources[cursor:end],
        next_cursor=end if end < len(sources) else None,
        readiness=dict(status=row["status"], assume_independent_trials=request["assume_independent_trials"]),
        limitations=result["limitations"])
