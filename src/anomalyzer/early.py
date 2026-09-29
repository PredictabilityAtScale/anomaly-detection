"""Causal descriptive assessments for histories too short to calibrate."""
from __future__ import annotations

import statistics
from typing import Iterable

from .contracts import (
    ActionPolicy, AnomalyPattern, Assessment, ExplicitRule, MethodResult,
)


def _direction(change: float | None) -> str:
    if change is None or change == 0:
        return "unchanged"
    return "increase" if change > 0 else "decrease"


def _rule_violations(value: float, previous: float | None,
                     rules: Iterable[ExplicitRule]) -> list[dict]:
    violations = []
    for rule in rules:
        if rule.kind == "acceptable_range":
            met = value < rule.minimum or value > rule.maximum
            boundary = {"minimum": rule.minimum, "maximum": rule.maximum}
        elif rule.kind == "maximum_absolute_change":
            met = previous is not None and abs(value - previous) > rule.threshold
            boundary = {"threshold": rule.threshold}
        else:
            relative = (abs((value - previous) / previous)
                        if previous not in (None, 0) else None)
            met = relative is not None and relative > rule.threshold
            boundary = {"threshold": rule.threshold}
        if met:
            violations.append({"id": rule.id, "kind": rule.kind, **boundary})
    return violations


def descriptive_assessments(target_id: str, times: list[str | None],
                            values: list[float | None],
                            rules: Iterable[ExplicitRule] = (),
                            policy: ActionPolicy | None = None,
                            relationship: bool = False) -> list[Assessment]:
    """Return prefix-invariant facts and simple-reference comparisons.

    Missing values break the comparison population. They are intentionally not
    converted to zero and do not allow a comparison across the gap.
    """
    policy = policy or ActionPolicy()
    result: list[Assessment] = []
    prior: list[float] = []
    previous: float | None = None
    for index, (observed_at, value) in enumerate(zip(times, values)):
        if value is None:
            prior = []
            previous = None
            continue
        change = value - previous if previous is not None else None
        relative = (change / abs(previous)
                    if change is not None and previous != 0 else None)
        violations = _rule_violations(value, previous, rules)
        if violations:
            classification = "criterion_violation"
            maturity = "early" if previous is not None else "observation_only"
            basis = "explicit_rule"
            criterion_met = True
            strength = None
            semantics = "exact comparison with caller-supplied rule boundaries"
            baseline = {"kind": "explicit_rules", "violations": violations}
            established = "One or more declared numerical criteria were crossed."
            not_established = (
                "A rule crossing does not establish a real-world anomaly, cause, "
                "incident, or business impact.")
        elif not prior:
            classification = "observation"
            maturity = "observation_only"
            basis = "declared_relationship" if relationship else "descriptive"
            criterion_met = False
            strength = None
            semantics = "no strength score; there is no comparison population"
            baseline = {"kind": "none"}
            established = "The numerical observation and its lineage are recorded."
            not_established = (
                "One observation does not establish a change, departure, or anomaly.")
        elif len(prior) == 1:
            classification = "change"
            maturity = "early"
            basis = "declared_relationship" if relationship else "descriptive"
            criterion_met = False
            strength = abs(change) if change is not None else None
            semantics = "absolute change in target units; not a probability"
            baseline = {"kind": "previous_observation", "value": previous}
            established = "The exact change and direction from the prior observation are established."
            not_established = (
                "Two observations do not establish an unusual departure, stable "
                "baseline, or real-world cause.")
        else:
            center = statistics.median(prior)
            low, high = min(prior), max(prior)
            outside = value < low or value > high
            width = high - low
            distance = low - value if value < low else value - high if value > high else 0.0
            classification = "departure_candidate" if outside else "change"
            maturity = "early"
            basis = "declared_relationship" if relationship else "descriptive"
            criterion_met = False
            strength = distance / width if width > 0 else distance
            semantics = (
                "distance beyond the prior range divided by that range when nonzero; "
                "descriptive only and not a probability")
            baseline = {
                "kind": "prior_median_and_range", "median": center,
                "minimum": low, "maximum": high,
            }
            established = (
                "The observation is outside the prior range under the named simple reference."
                if outside else
                "The observation is within the prior range under the named simple reference.")
            not_established = (
                "This short-history comparison is not statistically calibrated and "
                "does not establish a real-world anomaly or cause.")
        action = bool(
            criterion_met and policy.allow_explicit_rules)
        result.append(Assessment(
            id=f"{target_id}:assessment:{index}:early",
            target_id=target_id, index=index, timestamp=observed_at,
            classification=classification, maturity=maturity, basis=basis,
            action_eligible=action,
            notification_eligible=(action if policy.notification_requires_action else criterion_met),
            criterion_met=criterion_met,
            comparison_population=(
                "observations since the latest missing-value boundary, strictly before this sample"),
            comparison_samples=len(prior), baseline=baseline, observed=value,
            absolute_change=change, relative_change=relative,
            direction=_direction(change), evidence_strength=strength,
            evidence_strength_semantics=semantics,
            assumptions=[
                "Input order is chronological after preparation.",
                "Values share the declared target units and entity.",
                "No interpolation, resampling, or implicit unit conversion was performed.",
            ], established=established, not_established=not_established))
        prior.append(value)
        previous = value
    return result


def calibrated_assessments(target_id: str, methods: list[MethodResult],
                           policy: ActionPolicy | None = None,
                           relationship: bool = False) -> list[Assessment]:
    """Translate only calibrated point triggers into supported assessments."""
    policy = policy or ActionPolicy()
    assessments = []
    for method in methods:
        for item in method.evidence:
            if item["signal_maturity"] != "calibrated" or not item["triggers"]:
                continue
            action = policy.allow_calibrated_departures
            residual = item["residual"]
            assessments.append(Assessment(
                id=f"{target_id}:assessment:{item['index']}:{method.id}",
                target_id=target_id, index=item["index"],
                timestamp=item["timestamp"], classification="supported_departure",
                maturity="calibrated",
                basis=("declared_relationship" if relationship
                       else "statistical_baseline"),
                action_eligible=action,
                notification_eligible=(action if policy.notification_requires_action else True),
                criterion_met=True,
                comparison_population="frozen calibration residual window",
                comparison_samples=item["calibration_samples"],
                baseline={
                    "kind": "seasonal_residual", "method": method.id,
                    "expected": item["expected"],
                    "point_threshold": method.parameters.get("point_threshold"),
                },
                observed=item["observed"], absolute_change=residual,
                relative_change=item["relative_deviation"],
                direction="increase" if residual > 0 else "decrease" if residual < 0 else "unchanged",
                evidence_strength=abs(item["standardized_residual"]),
                evidence_strength_semantics=(
                    "absolute standardized residual under the frozen baseline; not a probability"),
                assumptions=[
                    "The declared cadence, seasonal reference, and frozen calibration are appropriate.",
                    "The score is interpreted as model-conditional evidence, not event truth.",
                ],
                established="The configured calibrated numerical criterion was met.",
                not_established=(
                    "The criterion does not establish a real-world anomaly, cause, "
                    "incident, or business impact."),
                evidence_refs=[item["id"]]))
    return assessments


def location_pattern_assessments(
        target_id: str, methods: list[MethodResult],
        patterns: list[AnomalyPattern], policy: ActionPolicy | None = None,
        relationship: bool = False) -> list[Assessment]:
    """Turn overlapping calibrated location rules into one early case signal.

    Nelson location rules and CUSUM can accumulate moderate departures before
    any individual point crosses the point threshold. Overlapping rules in the
    same direction are one correlated signal, so they produce one assessment
    at the earliest detection position rather than several apparent incidents.
    """
    policy = policy or ActionPolicy()
    candidates = [pattern for pattern in patterns
                  if pattern["kind"] == "location_shift"
                  and pattern["direction"] in ("increase", "decrease")]
    groups: list[dict] = []
    for pattern in sorted(
            candidates,
            key=lambda item: (item["direction"], min(item["triggering_samples"]),
                              item["detection_index"], item["id"])):
        start = min(pattern["triggering_samples"])
        stop = max(pattern["triggering_samples"])
        if (groups and groups[-1]["direction"] == pattern["direction"]
                and start <= groups[-1]["stop"]):
            groups[-1]["patterns"].append(pattern)
            groups[-1]["stop"] = max(groups[-1]["stop"], stop)
        else:
            groups.append({"direction": pattern["direction"], "start": start,
                           "stop": stop, "patterns": [pattern]})

    evidence = {item["index"]: item for method in methods
                for item in method.evidence
                if item["signal_maturity"] == "calibrated"}
    evidence_by_id = {item["id"]: item for method in methods
                      for item in method.evidence
                      if item["signal_maturity"] == "calibrated"}
    assessments = []
    for group in groups:
        patterns_in_group = group["patterns"]
        detection = min(pattern["detection_index"]
                        for pattern in patterns_in_group)
        item = evidence.get(detection)
        if item is None:
            continue
        detected_patterns = [
            pattern for pattern in patterns_in_group
            if pattern["detection_index"] == detection
        ]
        rules = sorted({pattern["rule"] for pattern in detected_patterns})
        pattern_ids = sorted(pattern["id"] for pattern in detected_patterns)
        evidence_refs = sorted({
            ref for pattern in detected_patterns
            for ref in pattern["evidence_refs"]
            if ref in evidence_by_id
            and evidence_by_id[ref]["index"] <= detection
        })
        peak = max(
            abs(evidence_by_id[ref]["standardized_residual"])
            for ref in evidence_refs)
        action = policy.allow_calibrated_departures
        assessments.append(Assessment(
            id=(f"{target_id}:assessment:{detection}:location_shift:"
                f"{group['direction']}"),
            target_id=target_id, index=detection,
            timestamp=item["timestamp"], classification="supported_departure",
            maturity="calibrated",
            basis=("declared_relationship" if relationship
                   else "statistical_baseline"),
            action_eligible=action,
            notification_eligible=(
                action if policy.notification_requires_action else True),
            criterion_met=True,
            comparison_population="frozen calibration residual stream",
            comparison_samples=item["calibration_samples"],
            baseline={
                "kind": "location_shift_pattern",
                "method": item["method"], "expected": item["expected"],
                "rules": rules, "pattern_ids": pattern_ids,
                "detection_index": detection,
            },
            observed=item["observed"], absolute_change=item["residual"],
            relative_change=item["relative_deviation"],
            direction=group["direction"], evidence_strength=peak,
            evidence_strength_semantics=(
                "peak absolute standardized residual within overlapping "
                "calibrated location-shift rules; not a probability or an "
                "independent-evidence count"),
            assumptions=[
                "The declared cadence, seasonal reference, and frozen residual calibration are appropriate.",
                "Overlapping Nelson and CUSUM findings in one direction are correlated and grouped once.",
            ],
            established=(
                "At least one configured calibrated location-shift rule was met; "
                "the detection position is the earliest point where that rule could be established."),
            not_established=(
                "The numerical shift criterion does not establish a real-world "
                "anomaly, cause, incident, or business impact."),
            evidence_refs=evidence_refs))
    return assessments
