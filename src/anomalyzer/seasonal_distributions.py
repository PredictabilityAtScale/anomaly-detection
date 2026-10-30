"""Explicit local-calendar population selection; no learned periods or resets."""
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from .budget import RuntimeBudget
from .contracts import Contract
from .distribution_contracts import (
    DistributionSample, DistributionSettings, DistributionRequest,
    DistributionPopulation, DistributionResult, _validate_kind,
)
from .distributions import compare_distributions, _fingerprint, LIMITATIONS
from .validation import timestamp


class SeasonalReferencePolicy(Contract):
    timezone: str = Field(min_length=1)
    matching: Literal["daily", "same_weekday", "weekday_weekend"] = "same_weekday"
    lookback_days: int = Field(default=28, ge=1, le=366, strict=True)
    min_windows: int = Field(default=3, ge=2, le=90, strict=True)
    max_windows: int = Field(default=14, ge=2, le=90, strict=True)
    min_samples_per_window: int = Field(default=8, ge=1, le=4096, strict=True)
    fallback: Literal["none", "daily"] = "none"

    @field_validator("timezone")
    @classmethod
    def named_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an available IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def compatible_policy(self):
        if self.min_windows > self.max_windows:
            raise ValueError("min_windows must not exceed max_windows")
        if self.matching == "daily" and self.fallback == "daily":
            raise ValueError("a daily policy cannot fall back to itself")
        return self


class SeasonalDistributionRequest(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["compare_seasonal_distributions"] = "compare_seasonal_distributions"
    kind: Literal["numeric", "categorical"]
    entity: dict[str, str] = Field(min_length=1)
    units: str = Field(min_length=1)
    samples: list[DistributionSample] = Field(max_length=10000)
    window_start: str
    window_end: str
    as_of: str
    reference_policy: SeasonalReferencePolicy
    assume_exchangeable: bool = Field(default=False, strict=True)
    config: DistributionSettings = Field(default_factory=DistributionSettings)

    @field_validator("window_start", "window_end", "as_of")
    @classmethod
    def offset_aware_time(cls, value):
        return timestamp(value, None).isoformat()

    @model_validator(mode="after")
    def eligible_source(self):
        ids = [sample.id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate logical sample IDs; deduplicate deliveries upstream")
        if any(sample.timestamp is None for sample in self.samples):
            raise ValueError("seasonal selection requires original offset-aware timestamps on every sample")
        _validate_kind(self.kind, self.samples)
        start, end, cutoff = (datetime.fromisoformat(value) for value in (self.window_start, self.window_end, self.as_of))
        zone = ZoneInfo(self.reference_policy.timezone)
        local_start, local_end = start.astimezone(zone), end.astimezone(zone)
        if end <= start or cutoff <= start:
            raise ValueError("window_end and as_of must be after window_start")
        if local_start.date() != local_end.date() or local_end.time() <= local_start.time():
            raise ValueError("the explicit window must start and end on one local date in increasing wall-clock order")
        if local_start.utcoffset() != local_end.utcoffset():
            raise ValueError("current windows crossing a UTC-offset transition are unsupported; choose a window outside the transition")
        for value in (local_start, local_end, min(cutoff, end).astimezone(zone)):
            _, reason = _local_boundary(value.replace(tzinfo=None), zone)
            if reason:
                raise ValueError(f"current window has an {reason}; choose an unambiguous local window")
        return self


class SeasonalDistributionResult(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["compare_seasonal_distributions"] = "compare_seasonal_distributions"
    status: Literal["completed", "descriptive", "insufficient_history", "resolution_limited", "budget_exceeded"]
    kind: Literal["numeric", "categorical"]
    entity: dict[str, str]
    units: str
    input_fingerprint: str
    selection_id: str | None = None
    reference_id: str | None = None
    change_detected: bool = False
    selection: dict[str, Any] = Field(default_factory=dict)
    testing: dict[str, Any]
    comparison: DistributionResult | None = None
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str]
    business_impact: Literal["unresolved"] = "unresolved"


def _local_boundary(naive, zone):
    """Resolve a wall-clock boundary only when UTC round-trips are unique."""
    valid = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == naive:
            valid.add(candidate)
    if len(valid) != 1:
        return None, "ambiguous_local_time" if valid else "nonexistent_local_time"
    return valid.pop(), None


def _matches(day, current, mode):
    if mode == "weekday_weekend":
        return (day.weekday() < 5) == (current.weekday() < 5)
    return mode == "daily" or day.weekday() == current.weekday()


def _measured(samples):
    return [sample for sample in samples if sample.complete and sample.value is not None]


def _select(request, budget):
    policy = request.reference_policy
    zone = ZoneInfo(policy.timezone)
    start = datetime.fromisoformat(request.window_start)
    end = datetime.fromisoformat(request.window_end)
    cutoff = min(datetime.fromisoformat(request.as_of), end)
    local_start, local_cutoff = start.astimezone(zone), cutoff.astimezone(zone)
    clock_start, clock_end = local_start.time().replace(tzinfo=None), local_cutoff.time().replace(tzinfo=None)
    rows, by_date, current = [], {}, []
    for sample in request.samples:
        budget.check()
        instant = datetime.fromisoformat(sample.timestamp)
        rows.append((instant, sample))
    rows.sort(key=lambda row: (row[0], row[1].id))
    for instant, sample in rows:
        if start <= instant < cutoff:
            current.append(sample)
        elif instant < start:
            by_date.setdefault(instant.astimezone(zone).date(), []).append((instant, sample))

    def attempt(mode):
        windows, selected = [], []
        for age in range(1, policy.lookback_days+1):
            budget.check()
            day = local_start.date() - timedelta(days=age)
            row = dict(date=day.isoformat(), status="excluded", reason=None, sample_ids=[], measured_samples=0)
            windows.append(row)
            if not _matches(day, local_start.date(), mode):
                row["reason"] = "weekday_mismatch"
                continue
            left, reason = _local_boundary(datetime.combine(day, clock_start), zone)
            right, end_reason = _local_boundary(datetime.combine(day, clock_end), zone)
            if reason or end_reason:
                row["reason"] = reason or end_reason
                continue
            if left.astimezone(zone).utcoffset() != right.astimezone(zone).utcoffset():
                row["reason"] = "utc_offset_transition"
                continue
            samples = [sample for instant, sample in by_date.get(day, []) if left <= instant < right]
            row.update(start=left.isoformat(), end=right.isoformat(), sample_ids=[s.id for s in samples],
                       measured_samples=len(_measured(samples)))
            if row["measured_samples"] < policy.min_samples_per_window:
                row["reason"] = "insufficient_window_support"
            elif len(selected) >= policy.max_windows:
                row["reason"] = "reference_window_limit"
            else:
                row["status"] = "selected"
                selected.append((row, samples))
        measured = sum(row["measured_samples"] for row, _ in selected)
        sufficient = len(selected) >= policy.min_windows and measured >= request.config.min_reference
        summary = dict(matching=mode, selected_windows=len(selected), measured_samples=measured,
                       support_sufficient=sufficient)
        return windows, selected, summary

    windows, selected, primary = attempt(policy.matching)
    attempts, fallback_used = [primary], False
    if not primary["support_sufficient"] and policy.fallback == "daily":
        windows, selected, fallback = attempt("daily")
        attempts.append(fallback)
        fallback_used = True
    reference = sorted((sample for _, samples in selected for sample in samples), key=lambda s: (s.timestamp, s.id))
    if len(reference) > 4096 or len(current) > 4096:
        raise ValueError("selected populations exceed 4096 events; narrow the window or reduce max_windows; no silent subsampling is performed")
    included = {sample.id for sample in reference + current}
    records = {row["date"]: row for row in windows}
    excluded = []
    for instant, sample in rows:
        budget.check()
        if sample.id in included:
            continue
        local_day = instant.astimezone(zone).date()
        reason = ("at_or_after_assessed_end" if instant >= cutoff else
                  "outside_current_window" if local_day >= local_start.date() else
                  "outside_lookback" if (local_start.date()-local_day).days > policy.lookback_days else
                  records.get(local_day.isoformat(), {}).get("reason") or "outside_matching_clock_window")
        excluded.append(dict(id=sample.id, reason=reason))
    return reference, current, dict(policy=policy.model_dump(mode="json"),
        resolved_matching="daily" if fallback_used else policy.matching, fallback_used=fallback_used,
        attempts=attempts, windows=windows, reference_windows=len(selected),
        reference_measured_samples=len(_measured(reference)), current_measured_samples=len(_measured(current)),
        reference_sample_ids=[s.id for s in reference], current_sample_ids=[s.id for s in current], excluded_samples=excluded,
        current_window=dict(start=start.isoformat(), end=end.isoformat(), assessed_end=cutoff.isoformat(),
                            partial=cutoff < end, local_start=local_start.isoformat(), local_assessed_end=local_cutoff.isoformat()),
        weighting="pooled_events; higher-volume windows contribute more observations",
        selection_version="explicit-seasonal-v1")


def compare_seasonal_distributions(request: SeasonalDistributionRequest | dict) -> SeasonalDistributionResult:
    """Select declared prior clock windows and reuse the population detector once."""
    request = SeasonalDistributionRequest.model_validate(request)
    cfg = request.config
    result = SeasonalDistributionResult(status="insufficient_history", kind=request.kind, entity=request.entity,
        units=request.units, input_fingerprint=_fingerprint(request.model_dump(mode="json")),
        testing=dict(alpha=cfg.alpha, max_comparisons=cfg.max_comparisons, comparison_index=cfg.comparison_index,
                     correction="bonferroni", threshold=cfg.alpha/cfg.max_comparisons,
                     allocation_policy="caller-held family; selection and fallback do not reset its budget"),
        limitations=LIMITATIONS + [
            "Matching is caller-declared, never discovered. Collection completeness and as-of availability are caller responsibilities; a closed clock window does not prove complete telemetry.",
            "Matching local time does not remove within-run/day dependence. This version does not perform block resampling or validate exchangeability.",
            "Keep separate rate and overall composition checks to detect a missing, shifted or enlarged scheduled batch; no cross-midnight or offset-transition windows are inferred."])
    budget = RuntimeBudget(cfg.max_runtime_seconds)
    try:
        reference, current, selection = _select(request, budget)
        result.selection = selection
        population = DistributionPopulation(samples=reference)
        result.reference_id = _fingerprint(population.model_dump(mode="json"))
        result.selection_id = _fingerprint(dict(policy=selection["policy"], window=selection["current_window"],
            resolved_matching=selection["resolved_matching"], reference=population.model_dump(mode="json"),
            current=DistributionPopulation(samples=current).model_dump(mode="json")))
        if selection["reference_windows"] < request.reference_policy.min_windows:
            result.reasons.append("Too few distinct supported prior windows; pooled call volume cannot replace distinct-day support.")
            return result
        comparison = compare_distributions(DistributionRequest(kind=request.kind, entity=request.entity, units=request.units,
            reference=population, current=DistributionPopulation(samples=current), config=cfg,
            assume_exchangeable=request.assume_exchangeable), _budget=budget)
        result.comparison, result.status, result.change_detected = comparison, comparison.status, comparison.change_detected
        result.reasons = comparison.reasons.copy()
        if selection["fallback_used"]:
            result.reasons.append("The declared daily fallback supplied the reference; the primary matching policy lacked support.")
    except TimeoutError:
        result.status = "budget_exceeded"
        result.change_detected = False
        result.reasons.append("Runtime budget exhausted during selection; no unfinished comparison can trigger.")
    return result
