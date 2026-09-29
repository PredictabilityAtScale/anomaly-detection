"""Deterministic evidence grouping without causal inference."""
import hashlib
import json

from .contracts import (
    Assessment, Case, DatasetResultV11, RelationshipResult, RequestV11,
)
from .robust import EXTREME_Z


def target_entities(request: RequestV11) -> dict[str, dict[str, str]]:
    """Return the declared entity scope for every dataset and relationship."""
    entities = {dataset.id: dataset.entity for dataset in request.datasets}
    for relationship in request.relationships:
        if relationship.kind == "ratio":
            source_id = relationship.numerator
        elif relationship.kind == "difference":
            source_id = relationship.minuend
        elif relationship.kind == "normalized_residual":
            source_id = relationship.observed
        elif relationship.kind == "lagged_response":
            source_id = relationship.response
        else:
            source_id = relationship.conditions[0].dataset
        entities[relationship.id] = entities[source_id]
    return entities


def compose_cases(dataset_results: list[DatasetResultV11],
                  relationship_results: list[RelationshipResult],
                  entities: dict[str, dict[str, str]]) -> list[Case]:
    candidates: list[tuple[str, str, Assessment]] = []
    for result in dataset_results:
        for assessment in result.assessments:
            if assessment.classification in ("supported_departure", "criterion_violation"):
                candidates.append(("dataset", result.dataset_id, assessment))
    for result in relationship_results:
        for assessment in result.assessments:
            if assessment.classification in ("supported_departure", "criterion_violation"):
                candidates.append(("relationship", result.relationship_id, assessment))
    grouped = {}
    for source_kind, source_id, assessment in candidates:
        event = assessment.timestamp if assessment.timestamp is not None else assessment.index
        entity = entities[source_id]
        entity_key = json.dumps(entity, sort_keys=True, separators=(",", ":"))
        grouped.setdefault((event, entity_key), []).append(
            (source_kind, source_id, assessment))
    cases = []
    for (event, entity_key), items in sorted(
            grouped.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        entity = json.loads(entity_key)
        datasets = sorted({source_id for kind, source_id, _ in items if kind == "dataset"})
        relationships = sorted({source_id for kind, source_id, _ in items if kind == "relationship"})
        refs = sorted({ref for _, _, assessment in items
                       for ref in assessment.evidence_refs} |
                      {assessment.id for _, _, assessment in items})
        stable_material = json.dumps(
            {"event": event, "entity": entity, "datasets": datasets,
             "relationships": relationships},
            sort_keys=True, separators=(",", ":"))
        case_id = "case:" + hashlib.sha256(stable_material.encode()).hexdigest()[:16]
        maturity_order = {
            "observation_only": 0, "early": 1, "provisional": 2, "calibrated": 3,
        }
        maturity = max((assessment.maturity for _, _, assessment in items),
                       key=maturity_order.get)
        action = any(assessment.action_eligible for _, _, assessment in items)
        notification = any(assessment.notification_eligible
                           for _, _, assessment in items)
        strongest = max((assessment.evidence_strength or 0.0
                         for _, _, assessment in items), default=0.0)
        independent_datasets = sorted({
            source_id for kind, source_id, assessment in items
            if kind == "dataset" and assessment.criterion_met
        })
        severity_reasons = []
        if strongest >= EXTREME_Z:
            severity_reasons.append(
                f"standardized evidence reached {strongest:.3g}, at or above "
                f"the robust extreme threshold {EXTREME_Z:g}")
        if len(independent_datasets) >= 2:
            severity_reasons.append(
                "calibrated or declared criteria were met in multiple source "
                f"datasets: {', '.join(independent_datasets)}")
        severity = "critical" if severity_reasons else "warning"
        if not severity_reasons:
            severity_reasons.append(
                "one source criterion or correlated derived relationship was met")
        source_phrases = []
        seen_sources = set()
        for kind, source_id, assessment in sorted(
                items, key=lambda value: (value[0], value[1], value[2].id)):
            key = (kind, source_id, assessment.direction)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            direction = ("was unchanged" if assessment.direction == "unchanged"
                         else f"{assessment.direction}d")
            label = (f"source dataset {source_id}" if kind == "dataset"
                     else f"declared relationship {source_id}")
            source_phrases.append(f"{label} {direction}")
        explanation = (
            f"At {event}, " + "; ".join(source_phrases) + ". "
            f"Severity is {severity} because " + "; ".join(severity_reasons) + ".")
        revision_material = json.dumps({
            "evidence_refs": refs,
            "maturity": maturity,
            "severity": severity,
            "severity_reasons": severity_reasons,
            "explanation": explanation,
            "action_eligible": action,
            "notification_eligible": notification,
        }, sort_keys=True, separators=(",", ":"))
        revision_id = case_id + ":" + hashlib.sha256(
            revision_material.encode()).hexdigest()[:12]
        correlation_group = sorted(
            assessment.id for _, _, assessment in items)
        cases.append(Case(
            id=case_id, revision_id=revision_id, entity=entity, event_time=event,
            detection_time=event, source_availability_cutoff=event,
            contributing_dataset_ids=datasets,
            contributing_relationship_ids=relationships,
            supporting_evidence=refs, conflicting_evidence=[],
            unavailable_evidence=[],
            correlated_evidence_groups=[correlation_group] if len(correlation_group) > 1 else [],
            evidence_refs=refs, maturity=maturity, severity=severity,
            severity_reasons=severity_reasons, explanation=explanation,
            action_eligible=action, notification_eligible=notification,
            suggested_investigation_questions=[
                "Did collection completeness, entity scope, or unit semantics change?",
                "Which reviewed operational or business changes overlap this event time?",
                "Does the declared relationship remain appropriate for this regime?",
            ],
            non_claims=[
                "Correlated evidence is not counted as independent confirmation.",
                "Numerical association does not establish cause.",
                "Business impact remains unresolved unless supplied externally.",
            ]))
    return cases
