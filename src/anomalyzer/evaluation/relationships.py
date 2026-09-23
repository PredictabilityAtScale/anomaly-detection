"""Chronological summaries over already-causal relationship evidence."""
from ..contracts import ResultV11
from ..orchestrator import analyze_relationships


def replay_relationships(request):
    result = analyze_relationships(request)
    summaries = []
    for relationship in result.relationship_results:
        first = {}
        for assessment in relationship.assessments:
            key = {
                "observation": "first_observation",
                "departure_candidate": "first_candidate",
                "supported_departure": "first_supported_departure",
                "criterion_violation": "first_criterion_violation",
            }.get(assessment.classification)
            if key and key not in first:
                first[key] = assessment.timestamp if assessment.timestamp is not None else assessment.index
            if assessment.action_eligible and "first_policy_eligible_action" not in first:
                first["first_policy_eligible_action"] = (
                    assessment.timestamp if assessment.timestamp is not None else assessment.index)
        summaries.append({"relationship_id": relationship.relationship_id, **first})
    return {
        "status": result.status,
        "input_fingerprint": result.input_fingerprint,
        "relationships": summaries,
        "limitation": (
            "Replay reports when evidence first became available under the same "
            "causal update semantics; it does not estimate precision, recall, or probability."),
    }
