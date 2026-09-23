"""Schema-1.1 multi-dataset and relationship orchestration."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from .alignment import PreparedDataset, prepare_source
from .budget import RuntimeBudget
from .cases import compose_cases, target_entities
from .contracts import (
    DatasetResultV11, RelationshipResult, RequestV11, ResultV11,
)
from .early import calibrated_assessments, descriptive_assessments
from .recipes import _namespace_result, analyze_dataset
from .registry import versions
from .relationships import derive


def _canonical_request(request: RequestV11) -> dict:
    document = request.model_dump(mode="json")
    document["datasets"] = sorted(document["datasets"], key=lambda item: item["id"])
    document["relationships"] = sorted(
        document["relationships"], key=lambda item: item["id"])
    return document


def _empty_dataset_result(dataset_id: str, error: Exception) -> DatasetResultV11:
    return DatasetResultV11(
        dataset_id=dataset_id, status="failed", data_quality={}, methods=[],
        observations=[], anomaly_patterns=[], assessments=[],
        limitations=[
            "This dataset failed independently; sibling dataset results remain available.",
            "Failure does not establish normality or an anomaly."],
        error=f"{type(error).__name__}: {error}")


def _derived_analysis_view(derived):
    """Use the causal suffix after structural leading unavailability.

    Lags and frozen coefficient training intentionally create a leading run of
    unavailable values. Dropping only that leading run lets the ordinary engine
    analyze the later derived series without treating those points as zero.
    Internal or trailing gaps remain visible and make the engine inapplicable.
    """
    offset = 0
    while offset < len(derived.values) and derived.values[offset] is None:
        offset += 1
    if not offset or offset == len(derived.values):
        return derived, offset
    return derived.model_copy(update={
        "timestamps": derived.timestamps[offset:] if derived.timestamps else None,
        "values": derived.values[offset:],
    }), offset


def _shift_result_indexes(result, offset):
    if not offset:
        return result
    evidence_ids = {}
    for method in result.methods:
        for item in method.evidence:
            old = item["id"]
            item["index"] += offset
            item["id"] = f"{method.id}:{item['index']}"
            evidence_ids[old] = item["id"]
    for observation in result.observations:
        observation["triggering_samples"] = [value + offset
                                               for value in observation["triggering_samples"]]
        observation["evidence_refs"] = [evidence_ids.get(value, value)
                                         for value in observation["evidence_refs"]]
    for pattern in result.anomaly_patterns:
        pattern["triggering_samples"] = [value + offset
                                          for value in pattern["triggering_samples"]]
        pattern["detection_index"] += offset
        pattern["evidence_refs"] = [evidence_ids.get(value, value)
                                     for value in pattern["evidence_refs"]]
    return result


def analyze_relationships(request: RequestV11 | dict) -> ResultV11:
    request = RequestV11.model_validate(request)
    if request.config.recipe != "seasonal-residual-v1":
        raise ValueError("schema 1.1 relationships currently require seasonal-residual-v1")
    started = time.perf_counter()
    budget = RuntimeBudget(request.config.max_runtime_seconds)
    canonical = _canonical_request(request)
    fingerprint = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()
    prepared: dict[str, PreparedDataset] = {}
    dataset_results = []
    for dataset in sorted(request.datasets, key=lambda item: item.id):
        try:
            budget.check()
            source = prepare_source(dataset, request.config, request.context)
            prepared[dataset.id] = source
            result = analyze_dataset(
                dataset, request.config, request.context, budget=budget)
            _namespace_result(result, f"dataset:{dataset.id}")
            assessments = descriptive_assessments(
                dataset.id,
                source.times[:source.quality["observation_count"]],
                source.values[:source.quality["observation_count"]], dataset.rules,
                request.policy)
            assessments.extend(calibrated_assessments(
                dataset.id, result.methods, request.policy))
            dataset_results.append(DatasetResultV11(
                dataset_id=dataset.id, status=result.status,
                data_quality=result.data_quality, methods=result.methods,
                observations=result.observations,
                anomaly_patterns=result.anomaly_patterns,
                assessments=assessments, limitations=result.limitations))
        except Exception as exc:
            dataset_results.append(_empty_dataset_result(dataset.id, exc))

    relationship_results = []
    for relationship in sorted(request.relationships, key=lambda item: item.id):
        definition = relationship.model_dump(mode="json")
        try:
            budget.check()
            derived, lineage, quality = derive(relationship, prepared)
            analysis_view, analysis_offset = _derived_analysis_view(derived)
            result = analyze_dataset(
                analysis_view, request.config, request.context, budget=budget)
            _shift_result_indexes(result, analysis_offset)
            _namespace_result(result, f"relationship:{relationship.id}")
            quality["analysis_offset"] = analysis_offset
            assessments = descriptive_assessments(
                relationship.id, derived.timestamps or [], derived.values,
                relationship.rules, request.policy, relationship=True)
            assessments.extend(calibrated_assessments(
                relationship.id, result.methods, request.policy,
                relationship=True))
            if quality["available_count"] == 0 or quality["latest_evidence_state"] == "insufficient_evidence":
                status = "insufficient_evidence"
            elif quality["unavailable_count"] and result.status == "inapplicable":
                status = "partial"
            else:
                status = result.status
            relationship_results.append(RelationshipResult(
                relationship_id=relationship.id, kind=relationship.kind,
                status=status, definition=definition,
                applicability=(
                    "exact UTC timestamp alignment at one shared declared cadence; "
                    "missing and incomplete values remain unavailable"),
                data_quality=quality, lineage=lineage, methods=result.methods,
                observations=result.observations,
                anomaly_patterns=result.anomaly_patterns,
                assessments=assessments,
                limitations=list(dict.fromkeys(result.limitations + [
                    "The declared relationship is model input, not a discovered or causal relationship.",
                    "Derived and source evidence can be correlated and must not be counted as independent votes.",
                    "No interpolation, resampling, implicit zero, or unit conversion was performed.",
                ]))))
        except Exception as exc:
            relationship_results.append(RelationshipResult(
                relationship_id=relationship.id, kind=relationship.kind,
                status="failed", definition=definition,
                applicability="exact UTC timestamp alignment at one shared declared cadence",
                data_quality={}, lineage=[], methods=[], observations=[],
                anomaly_patterns=[], assessments=[],
                limitations=[
                    "Relationship failure is visible and does not suppress valid sibling results.",
                    "Unavailable relationship evidence must not be interpreted as normal."],
                error=f"{type(exc).__name__}: {exc}"))

    cases = compose_cases(
        dataset_results, relationship_results, target_entities(request))
    statuses = [item.status for item in dataset_results + relationship_results]
    failures = sum(status in ("failed", "partial") for status in statuses)
    if failures:
        status = "failed" if failures == len(statuses) else "partial"
    elif "insufficient_evidence" in statuses:
        status = ("partial" if any(value in ("completed", "insufficient_history")
                                   for value in statuses)
                  else "inapplicable")
    elif statuses and all(status == "insufficient_history" for status in statuses):
        status = "insufficient_history"
    elif statuses and all(status in ("inapplicable", "insufficient_evidence")
                          for status in statuses):
        status = "inapplicable"
    else:
        status = "completed"
    return ResultV11(
        run_id=str(uuid.uuid4()), status=status,
        input_fingerprint=fingerprint, resolved_config=canonical,
        dependencies=versions(), dataset_results=dataset_results,
        relationship_results=relationship_results, cases=cases,
        limitations=[
            "Assessment strength is not a probability or universal confidence percentage.",
            "Early descriptive candidates are non-triggering and cannot create a case.",
            "Cases group evidence deterministically; they do not assert causality or resolved business impact.",
            "Review state is unreviewed unless an external reviewer updates it."],
        runtime_seconds=time.perf_counter() - started,
        stop_reason="runtime_budget" if budget.remaining == 0 else
                    "method_failure" if failures else
                    "insufficient_evidence" if "insufficient_evidence" in statuses else
                    "completed")
