"""Compact, drillable views over the unchanged public analysis results."""
from __future__ import annotations

from collections import Counter


def _targets(result):
    if result["schema_version"] == "1.0":
        dataset = result["resolved_config"]["datasets"][0]
        yield "dataset", dataset["id"], result
        return
    for item in result["dataset_results"]:
        yield "dataset", item["dataset_id"], item
    for item in result["relationship_results"]:
        yield "relationship", item["relationship_id"], item


def _definitions(result):
    request = result["resolved_config"]
    datasets = {item["id"]: item for item in request["datasets"]}
    definitions = {
        item["id"]: {"units": item.get("units"), "entity": item["entity"]}
        for item in request["datasets"]
    }
    for item in request.get("relationships", []):
        if item["kind"] == "ratio":
            source = item["numerator"]
        elif item["kind"] == "difference":
            source = item["minuend"]
        elif item["kind"] == "normalized_residual":
            source = item["observed"]
        elif item["kind"] == "lagged_response":
            source = item["response"]
        else:
            source = item["conditions"][0]["dataset"]
        definitions[item["id"]] = {
            "units": item.get("units"), "entity": datasets[source]["entity"],
        }
    return definitions


def _readiness(item):
    checks = [{
        "method": method["id"],
        **method.get("diagnostics", {}).get("detection_readiness", {
            "status": "not_assessed", "reasons": ["Readiness is unavailable."],
        }),
    } for method in item["methods"]]
    statuses = {check["status"] for check in checks}
    if not checks or statuses == {"not_assessed"}:
        status = "not_assessed"
    elif "caution" in statuses or "not_assessed" in statuses:
        status = "caution"
    else:
        status = "supported"
    return status, checks


def _quality(item):
    source = item["data_quality"]
    return {
        "status": item["status"],
        "observation_count": source.get("observation_count",
                                        source.get("aligned_count")),
        "missing_count": source.get("missing_count", source.get("unavailable_count", 0)),
        "incomplete_count": source.get("incomplete_count", 0),
        "regular": source.get("regular"),
        "latest_evidence_state": source.get("latest_evidence_state"),
        "error": item.get("error"),
    }


def _quality_issue(item):
    quality = _quality(item)
    return (item["status"] != "completed" or quality["missing_count"] > 0
            or quality["incomplete_count"] > 0 or quality["regular"] is False
            or quality["latest_evidence_state"] == "insufficient_evidence")


def _case_assessments(result, case):
    ids = set(case["supporting_evidence"])
    matches = [
        (kind, target_id, assessment)
        for kind, target_id, item in _targets(result)
        for assessment in item.get("assessments", [])
        if assessment["id"] in ids
    ]
    return sorted(matches, key=lambda entry: (entry[0] != "relationship",
                                              entry[1], entry[2]["id"]))


def _case_headline(case, matches, definitions):
    if case.get("explanation"):
        if matches:
            kind, target, _ = matches[0]
            return f"{kind} {target}: {case['explanation']}"
        return case["explanation"]
    if not matches:
        return f"Numerical case for {case['entity']} at {case['event_time']}."
    kind, target, assessment = matches[0]
    unit = definitions[target]["units"]
    unit_text = f" {unit}" if unit else ""
    observed = f"{assessment['observed']:.6g}{unit_text}"
    baseline = assessment["baseline"]
    if baseline["kind"] == "seasonal_residual":
        comparison = f" versus expected {baseline['expected']:.6g}{unit_text}"
    else:
        rules = ", ".join(rule["id"] for rule in baseline["violations"])
        comparison = f" crossed declared rule {rules}"
    return f"{kind} {target}: {observed}{comparison} at {case['event_time']}."


def _interval_text(interval):
    return str(interval[0]) if interval[0] == interval[-1] else (
        f"{interval[0]} to {interval[-1]}")


def _quality_headline(target, item, quality):
    if quality["latest_evidence_state"] == "insufficient_evidence":
        return f"{target}: latest relationship evidence is unavailable."
    if quality["incomplete_count"]:
        return (f"{target}: {quality['incomplete_count']} incomplete source "
                "period(s) were excluded from finalized scoring.")
    if quality["missing_count"]:
        return f"{target}: {quality['missing_count']} missing/unavailable value(s)."
    if item["status"] == "insufficient_history":
        return (f"{target}: insufficient history for calibrated detection "
                f"({quality['observation_count']} observations).")
    return f"{target}: analysis status is {item['status']}."


def build_findings(result):
    definitions = _definitions(result)
    findings = []
    if result["schema_version"] == "1.1":
        for case in result["cases"]:
            matches = _case_assessments(result, case)
            order = max((item["index"] for _, _, item in matches), default=-1)
            target = matches[0][1] if matches else None
            findings.append({
                "id": case["id"], "kind": "case", "target_id": target,
                "entity": case["entity"], "event_time": case["event_time"],
                "headline": _case_headline(case, matches, definitions),
                "maturity": case["maturity"],
                "severity": case["severity"],
                "readiness": (_readiness(next(item for _, name, item in _targets(result)
                                              if name == target))[0]
                              if target else "not_assessed"),
                "note": "A case is numerical evidence, not an incident or permission to act.",
                "_order": order, "_priority": 0,
            })
    for kind, target, item in _targets(result):
        readiness, _ = _readiness(item)
        for episode in item["observations"]:
            findings.append({
                "id": f"episode:{episode['id']}", "kind": "episode",
                "target_id": target, "entity": definitions[target]["entity"],
                "event_time": episode["interval"][-1],
                "headline": (
                    f"{target}: {episode['observed_statistic']:.6g} versus "
                    f"expected {episode['reference']:.6g} "
                    f"({episode['direction']}) over "
                    f"{_interval_text(episode['interval'])}."),
                "maturity": "calibrated", "readiness": readiness,
                "note": "A point episode can overlap residual patterns.",
                "_order": max(episode["triggering_samples"]), "_priority": 0,
            })
        if result["schema_version"] == "1.1":
            for assessment in item["assessments"]:
                if assessment["classification"] != "departure_candidate":
                    continue
                baseline = assessment["baseline"]
                findings.append({
                    "id": f"candidate:{assessment['id']}",
                    "kind": "candidate", "target_id": target,
                    "entity": definitions[target]["entity"],
                    "event_time": assessment["timestamp"],
                    "headline": (
                        f"{target}: early possible departure at "
                        f"{assessment['timestamp'] or assessment['index']}; "
                        f"observed {assessment['observed']:.6g} versus prior "
                        f"range {baseline['minimum']:.6g} to "
                        f"{baseline['maximum']:.6g}."),
                    "maturity": "early", "readiness": readiness,
                    "note": "This descriptive prior-range comparison is not calibrated and is not a case.",
                    "_order": assessment["index"], "_priority": 2,
                })
        for pattern in item["anomaly_patterns"]:
            findings.append({
                "id": f"pattern:{pattern['id']}", "kind": "pattern",
                "target_id": target, "entity": definitions[target]["entity"],
                "event_time": pattern["interval"][-1],
                "headline": (
                    f"{target}: possible {pattern['kind'].replace('_', ' ')} "
                    f"({pattern['direction']}, {pattern['rule']}) over "
                    f"{_interval_text(pattern['interval'])}."),
                "maturity": "calibrated", "readiness": readiness,
                "note": "Patterns can overlap cases, episodes, and each other.",
                "_order": max(pattern["triggering_samples"], default=-1),
                "_priority": 2,
            })
        if _quality_issue(item):
            quality = _quality(item)
            findings.append({
                "id": f"quality:{kind}:{target}", "kind": "quality",
                "target_id": target, "entity": definitions[target]["entity"],
                "event_time": item["data_quality"].get("window", [None, None])[-1]
                              if item["data_quality"].get("window") else None,
                "headline": _quality_headline(target, item, quality),
                "maturity": "observation_only", "readiness": readiness,
                "note": "Unavailable evidence must not be treated as normal.",
                "_order": (quality["observation_count"] or 0) - 1,
                "_priority": (1 if item["status"] in (
                    "failed", "partial", "inapplicable", "insufficient_evidence")
                    or quality["missing_count"] or quality["incomplete_count"]
                    else 3),
            })
    findings.sort(key=lambda item: (item["_priority"], -item["_order"], item["id"]))
    for item in findings:
        del item["_order"]
        del item["_priority"]
    return findings


def summarize(result):
    findings = build_findings(result)
    readiness = []
    quality = []
    for kind, target, item in _targets(result):
        status, checks = _readiness(item)
        readiness.append({
            "target_id": target, "kind": kind, "status": status,
            "methods": [{"id": check["method"], "status": check["status"],
                         "reasons": check["reasons"]} for check in checks],
        })
        quality.append({"target_id": target, "kind": kind, **_quality(item)})
    if findings:
        headline = findings[0]["headline"]
        next_step = ("Inspect the finding's evidence and check source completeness "
                     "and relevant operational context.")
    elif result["status"] == "completed":
        headline = "No configured point, pattern, or rule findings were detected."
        next_step = "Check readiness before interpreting the absence of findings."
    else:
        headline = f"Analysis is {result['status']}; absence of findings is inconclusive."
        next_step = "Inspect data quality and method applicability."
    return {
        "run_id": result["run_id"], "schema_version": result["schema_version"],
        "status": result["status"], "headline": headline,
        "finding_count": len(findings),
        "finding_counts_by_kind": dict(Counter(item["kind"] for item in findings)),
        "findings_preview": findings[:3],
        "readiness": readiness, "data_quality": quality,
        "next_step": next_step,
        "limitations": result["limitations"],
        "note": "Findings can overlap and are not independent incidents. Policy eligibility is not execution authority.",
    }


def list_findings(result, cursor=0, limit=20):
    if cursor < 0 or limit < 1 or limit > 100:
        raise ValueError("cursor must be nonnegative and limit must be 1..100")
    findings = build_findings(result)
    end = min(cursor + limit, len(findings))
    return {
        "run_id": result["run_id"], "total": len(findings),
        "findings": findings[cursor:end],
        "next_cursor": end if end < len(findings) else None,
        "note": "Cases, episodes, patterns, and quality findings are different evidence types; overlapping findings are not separate incidents.",
    }


def get_evidence(result, finding_id, cursor=0, limit=50):
    if cursor < 0 or limit < 1 or limit > 100:
        raise ValueError("cursor must be nonnegative and limit must be 1..100")
    finding = next((item for item in build_findings(result)
                    if item["id"] == finding_id), None)
    if finding is None:
        raise ValueError(f"finding not found: {finding_id}")
    record = None
    assessments = []
    lineage = []
    references = set()
    related = []
    if finding["kind"] == "case":
        record = next(item for item in result["cases"] if item["id"] == finding_id)
        matches = _case_assessments(result, record)
        assessments = [assessment for _, _, assessment in matches]
        references = set(record["evidence_refs"])
        targets = {target for _, target, _ in matches}
        for kind, target, item in _targets(result):
            if target in targets:
                related.append((kind, target, item))
                if kind == "relationship":
                    indexes = {assessment["index"] for source_kind, name, assessment
                               in matches if source_kind == kind and name == target}
                    lineage.extend(point for point in item["lineage"]
                                   if point["index"] in indexes)
    else:
        kind, target, item = next((kind, target, item)
                                  for kind, target, item in _targets(result)
                                  if target == finding["target_id"])
        related = [(kind, target, item)]
        if finding["kind"] == "pattern":
            record = next(pattern for pattern in item["anomaly_patterns"]
                          if f"pattern:{pattern['id']}" == finding_id)
            references = set(record["evidence_refs"])
        elif finding["kind"] == "episode":
            record = next(episode for episode in item["observations"]
                          if f"episode:{episode['id']}" == finding_id)
            references = set(record["evidence_refs"])
        elif finding["kind"] == "candidate":
            record = next(assessment for assessment in item["assessments"]
                          if f"candidate:{assessment['id']}" == finding_id)
            if kind == "relationship":
                lineage = [point for point in item["lineage"]
                           if point["index"] == record["index"]]
        else:
            source_quality = item["data_quality"]
            incomplete = source_quality.get("incomplete_periods", [])
            record = {
                "status": item["status"], "data_quality": _quality(item),
                "transformations": source_quality.get("transformations", []),
                "incomplete_period_count": len(incomplete),
                "incomplete_periods_preview": incomplete[:5],
                "error": item.get("error"),
            }
            if kind == "relationship":
                unavailable = [point for point in item["lineage"]
                               if point["unavailable_reason"]]
                lineage = unavailable[-5:]
    samples = [
        evidence for _, _, item in related for method in item["methods"]
        for evidence in method["evidence"] if evidence["id"] in references
    ]
    samples.sort(key=lambda item: (item["index"], item["id"]))
    end = min(cursor + limit, len(samples))
    selected_samples = samples[cursor:end]
    if finding["kind"] in ("pattern", "episode"):
        record = {key: value for key, value in record.items()
                  if key not in ("evidence_refs", "triggering_samples")}
        if kind == "relationship":
            indexes = {sample["index"] for sample in selected_samples}
            lineage = [point for point in item["lineage"]
                       if point["index"] in indexes]
    readiness = [
        {"target_id": target, "kind": kind, "status": _readiness(item)[0],
         "methods": [{"id": check["method"], "status": check["status"],
                      "reasons": check["reasons"],
                      "limitations": method["limitations"]}
                     for check, method in zip(_readiness(item)[1], item["methods"])],
         "limitations": item["limitations"]}
        for kind, target, item in related
    ]
    return {
        "run_id": result["run_id"], "finding": finding,
        "record": record, "assessments": assessments,
        "lineage": lineage, "readiness": readiness,
        "sample_count": len(samples), "samples": selected_samples,
        "next_cursor": end if end < len(samples) else None,
        "note": "Evidence establishes numerical criteria only; source context, cause, impact, and action authority require external review.",
    }
