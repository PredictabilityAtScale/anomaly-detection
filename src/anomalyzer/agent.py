"""Strict, read-only Python facade for agent integrations."""
from __future__ import annotations

from .cases import compose_cases, target_entities
from .contracts import (
    ActionPolicy, Case, Dataset, RequestV11, ResultV11, Settings,
)
from .orchestrator import analyze_relationships as _analyze_relationships
from .recipes import analyze


def analyze_series(dataset: Dataset | dict | list[float | None],
                   settings: Settings | dict | None = None):
    """Analyze one series using the frozen schema-1.0 semantics."""
    if isinstance(dataset, list):
        return analyze(dataset, settings)
    validated = Dataset.model_validate(dataset)
    config = Settings.model_validate(settings or {})
    return analyze({"datasets": [validated.model_dump(mode="json")],
                    "config": config.model_dump(mode="json")})


def analyze_relationships(request: RequestV11 | dict) -> ResultV11:
    """Analyze declared relationships; this does not discover or prove causes."""
    return _analyze_relationships(request)


def get_case(result: ResultV11 | dict, case_id: str) -> Case | None:
    """Retrieve one immutable case revision from a completed result."""
    validated = ResultV11.model_validate(result)
    return next((case for case in validated.cases if case.id == case_id), None)


def replay_policy(result: ResultV11 | dict,
                  policy: ActionPolicy | dict) -> ResultV11:
    """Re-evaluate action/notification eligibility without recomputing evidence."""
    replayed = ResultV11.model_validate(result).model_copy(deep=True)
    policy = ActionPolicy.model_validate(policy)
    for collection in (replayed.dataset_results, replayed.relationship_results):
        for item in collection:
            for assessment in item.assessments:
                assessment.action_eligible = bool(
                    assessment.classification == "criterion_violation"
                    and policy.allow_explicit_rules or
                    assessment.classification == "supported_departure"
                    and policy.allow_calibrated_departures)
                assessment.notification_eligible = (
                    assessment.action_eligible
                    if policy.notification_requires_action else
                    assessment.criterion_met)
    request = RequestV11.model_validate(replayed.resolved_config)
    replayed.cases = compose_cases(
        replayed.dataset_results, replayed.relationship_results,
        target_entities(request))
    replayed.resolved_config["policy"] = policy.model_dump(mode="json")
    return replayed
