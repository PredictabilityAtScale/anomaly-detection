"""Separate additive contracts for population comparisons (distribution-v1)."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Contract
from .validation import timestamp


class DistributionSample(Contract):
    id: str = Field(min_length=1, max_length=128, strict=True)
    value: float | str | None
    timestamp: str | None = None
    complete: bool = Field(default=True, strict=True)
    weight: float = Field(default=1.0, gt=0)

    @field_validator("weight", mode="before")
    @classmethod
    def genuine_weight(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("event weight must be a positive finite measured quantity")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def measured_value(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, str))):
            raise ValueError("value must be a finite number, category string or null")
        if isinstance(value, (int, float)):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("numeric values must be finite representable numbers")
        if isinstance(value, str) and (not value.strip() or value != value.strip() or len(value) > 128):
            raise ValueError("categories must be nonempty trimmed strings of at most 128 characters")
        return value

    @field_validator("timestamp")
    @classmethod
    def normalized_time(cls, value):
        return timestamp(value, None).isoformat() if value is not None else None


class DistributionPopulation(Contract):
    samples: list[DistributionSample] = Field(default_factory=list, max_length=4096)
    weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def population(self):
        ids = [sample.id for sample in self.samples]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate logical sample IDs; deduplicate deliveries upstream")
        try:
            total_weight = math.fsum(sample.weight for sample in self.samples)
        except OverflowError as exc:
            raise ValueError("total event weight must be finite") from exc
        if not math.isfinite(total_weight):
            raise ValueError("total event weight must be finite")
        if self.weights is not None:
            if self.samples or not self.weights or len(self.weights) > 128:
                raise ValueError("weights require a nonempty composition of at most 128 categories and no samples")
            if any(not key.strip() or key != key.strip() or len(key) > 128 for key in self.weights):
                raise ValueError("weight categories must be trimmed nonempty strings of at most 128 characters")
            try:
                total = math.fsum(self.weights.values())
            except OverflowError as exc:
                raise ValueError("total weight must be finite") from exc
            if any(value < 0 for value in self.weights.values()) or not math.isfinite(total) or not any(self.weights.values()):
                raise ValueError("weights must be finite, nonnegative and have a positive finite total")
        return self


class DistributionSettings(Contract):
    alpha: float = Field(default=0.01, gt=0, lt=1)
    max_comparisons: int = Field(default=1, ge=1, le=1000000, strict=True)
    comparison_index: int = Field(default=0, ge=0, strict=True)
    min_reference: int = Field(default=32, ge=2, le=4096, strict=True)
    min_current: int = Field(default=16, ge=2, le=4096, strict=True)
    min_effect: float = Field(default=0.05, ge=0, le=1)
    missing_current: Literal["exclude", "break"] = "exclude"
    permutations: int = Field(default=9999, ge=99, le=99999, strict=True)
    seed: int = Field(default=0, ge=0, le=2**32-1, strict=True)
    max_runtime_seconds: float = Field(default=30, gt=0, le=3600)

    @model_validator(mode="after")
    def testing_budget(self):
        if self.comparison_index >= self.max_comparisons:
            raise ValueError("comparison_index exhausts the declared testing family")
        return self


class DistributionRequest(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["compare_distributions"] = "compare_distributions"
    kind: Literal["numeric", "categorical"]
    entity: dict[str, str] = Field(min_length=1)
    units: str = Field(min_length=1)
    reference: DistributionPopulation
    current: DistributionPopulation
    assume_exchangeable: bool = Field(default=False, strict=True)
    config: DistributionSettings = Field(default_factory=DistributionSettings)

    @model_validator(mode="after")
    def compatible_populations(self):
        _validate_kind(self.kind, self.reference.samples + self.current.samples)
        if self.kind == "numeric" and (self.reference.weights is not None or self.current.weights is not None):
            raise ValueError("numeric comparisons require individual measured samples")
        if (self.reference.weights is None) != (self.current.weights is None):
            raise ValueError("both populations must use samples or both use weights")
        if {sample.id for sample in self.reference.samples} & {sample.id for sample in self.current.samples}:
            raise ValueError("reference and current populations must have disjoint logical IDs")
        return self


def _validate_kind(kind, samples):
    try:
        math.fsum(sample.weight for sample in samples)
    except OverflowError as exc:
        raise ValueError("pooled event weight must be finite") from exc
    for sample in samples:
        if sample.value is not None and (isinstance(sample.value, str) != (kind == "categorical")):
            raise ValueError(f"{kind} samples have incompatible value types")
        if kind == "numeric" and sample.weight != 1:
            raise ValueError("numeric samples cannot use event weights")


class DistributionMonitorRequest(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["monitor_distributions"] = "monitor_distributions"
    monitor_id: str = Field(min_length=1)
    kind: Literal["numeric", "categorical"]
    entity: dict[str, str] = Field(min_length=1)
    units: str = Field(min_length=1)
    samples: list[DistributionSample] = Field(max_length=10000)
    assume_exchangeable: bool = Field(default=False, strict=True)
    order: Literal["timestamp", "trusted_sequence"] = "timestamp"
    reference_size: int = Field(default=128, ge=2, le=4096, strict=True)
    window_sizes: list[int] = Field(default_factory=lambda: [32, 128], min_length=1, max_length=4)
    stride: int = Field(default=1, ge=1, strict=True)
    max_looks: int = Field(default=32, ge=1, le=10000, strict=True)
    config: DistributionSettings = Field(default_factory=DistributionSettings)

    @field_validator("window_sizes", mode="before")
    @classmethod
    def valid_windows(cls, value):
        if not isinstance(value, list) or any(type(n) is not int or n < 2 or n > 4096 for n in value) or len(set(value)) != len(value):
            raise ValueError("window_sizes must contain distinct integer sizes in 2..4096")
        return value

    @model_validator(mode="after")
    def ordered_samples(self):
        ids = [sample.id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate logical sample IDs")
        _validate_kind(self.kind, self.samples)
        times = [sample.timestamp for sample in self.samples]
        if any(time is not None for time in times):
            if any(time is None for time in times) or times != sorted(times):
                raise ValueError("supply all original timestamps in nondecreasing UTC order")
            if self.order != "trusted_sequence" and len(set(times)) != len(times):
                raise ValueError("tied timestamps require trusted_sequence; use explicit population comparisons for unordered cohorts")
        elif self.order != "trusted_sequence":
            raise ValueError("positional samples require an explicit trusted_sequence assertion")
        incomplete = False
        for sample in self.samples:
            incomplete |= not sample.complete
            if incomplete and sample.complete:
                raise ValueError("incomplete samples must form a trailing suffix")
        if self.reference_size < self.config.min_reference or min(self.window_sizes) < self.config.min_current:
            raise ValueError("reference_size and window_sizes must meet configured minimum support")
        if self.config.max_comparisons != 1 or self.config.comparison_index != 0:
            raise ValueError("monitor owns max_comparisons/comparison_index; allocate its total alpha across monitors externally")
        return self


class DistributionResult(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["compare_distributions"] = "compare_distributions"
    status: Literal["completed", "descriptive", "insufficient_history", "resolution_limited", "budget_exceeded"]
    kind: Literal["numeric", "categorical"]
    entity: dict[str, str]
    units: str
    reference_id: str
    current_id: str
    input_fingerprint: str
    method: str
    statistic: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    threshold: float
    statistical_change: bool = False
    practical_change: bool = False
    change_detected: bool = False
    reference: dict[str, Any]
    current: dict[str, Any]
    details: dict[str, Any] = Field(default_factory=dict)
    testing: dict[str, Any]
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str]
    business_impact: Literal["unresolved"] = "unresolved"


class DistributionMonitorResult(Contract):
    schema_version: Literal["distribution-v1"] = "distribution-v1"
    task: Literal["monitor_distributions"] = "monitor_distributions"
    monitor_id: str
    status: Literal["completed", "insufficient_history", "partial", "horizon_exhausted"]
    input_fingerprint: str
    reference_id: str
    evaluations: list[dict[str, Any]]
    first_detection: dict[str, Any] | None
    testing: dict[str, Any]
    data_quality: dict[str, Any]
    limitations: list[str]
