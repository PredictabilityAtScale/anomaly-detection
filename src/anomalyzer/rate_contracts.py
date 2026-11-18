"""Explicit bounded success/trial counts; separate from arbitrary ratios."""
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Contract
from .validation import timestamp


class RateSample(Contract):
    id: str = Field(min_length=1, max_length=128, strict=True)
    successes: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    trials: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    timestamp: str | None = None
    complete: bool = Field(default=True, strict=True)

    @field_validator("timestamp")
    @classmethod
    def normalized_time(cls, value):
        return timestamp(value).isoformat() if value is not None else None

    @model_validator(mode="after")
    def bounded_counts(self):
        if self.successes is not None and self.trials is not None and self.successes > self.trials:
            raise ValueError("successes cannot exceed trials")
        return self


class RatePopulation(Contract):
    samples: list[RateSample] = Field(default_factory=list, max_length=4096)

    @model_validator(mode="after")
    def unique_samples(self):
        if len({s.id for s in self.samples}) != len(self.samples):
            raise ValueError("duplicate logical sample IDs")
        return self


class RateSettings(Contract):
    alpha: float = Field(default=0.01, ge=1e-12, lt=1)
    max_comparisons: int = Field(default=1, ge=1, le=1_000_000, strict=True)
    comparison_index: int = Field(default=0, ge=0, strict=True)
    min_effect: float = Field(default=0.01, ge=0, le=1)
    min_reference_trials: int = Field(default=1, ge=1, strict=True)
    min_current_trials: int = Field(default=1, ge=1, strict=True)
    interval_coverage: float = Field(default=0.95, ge=0.5, le=0.999999)
    max_tables: int = Field(default=200_000, ge=1, le=1_000_000, strict=True)
    max_runtime_seconds: float = Field(default=30, gt=0, le=3600)

    @model_validator(mode="after")
    def testing_family(self):
        if self.comparison_index >= self.max_comparisons:
            raise ValueError("comparison_index exhausts the declared testing family")
        return self


class RateLimit(Contract):
    id: str = Field(min_length=1, strict=True)
    operator: Literal["lt", "lte", "gt", "gte"]
    threshold: float = Field(ge=0, le=1)


class RateContext(Contract):
    concern: str | None = Field(default=None, max_length=2000)
    metric_definition: str | None = Field(default=None, max_length=2000)
    known_events: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=16)


class RateRequest(Contract):
    schema_version: Literal["rate-v1"] = "rate-v1"
    task: Literal["compare_rates"] = "compare_rates"
    entity: dict[str, str] = Field(min_length=1)
    context: RateContext = Field(default_factory=RateContext)
    reference: RatePopulation
    current: RatePopulation
    assume_independent_trials: bool = Field(default=False, strict=True)
    limits: list[RateLimit] = Field(default_factory=list, max_length=16)
    config: RateSettings = Field(default_factory=RateSettings)

    @model_validator(mode="after")
    def disjoint_populations(self):
        if {s.id for s in self.reference.samples} & {s.id for s in self.current.samples}:
            raise ValueError("reference and current must have disjoint logical sample IDs")
        if len({r.id for r in self.limits}) != len(self.limits):
            raise ValueError("duplicate rate-limit IDs")
        return self


class RateResult(Contract):
    schema_version: Literal["rate-v1"] = "rate-v1"
    task: Literal["compare_rates"] = "compare_rates"
    status: Literal["completed", "descriptive", "insufficient_history", "resolution_limited", "budget_exceeded"]
    entity: dict[str, str]
    context: RateContext
    input_fingerprint: str
    method: Literal["fisher_exact_two_sided"] = "fisher_exact_two_sided"
    reference: dict
    current: dict
    effect: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    threshold: float
    statistical_change: bool = False
    practical_change: bool = False
    change_detected: bool = False
    rate_limit_violations: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    testing: dict
    details: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str]


class RateMonitorRequest(Contract):
    schema_version: Literal["rate-v1"] = "rate-v1"
    task: Literal["monitor_rates"] = "monitor_rates"
    monitor_id: str = Field(min_length=1, strict=True)
    entity: dict[str, str] = Field(min_length=1)
    context: RateContext = Field(default_factory=RateContext)
    samples: list[RateSample] = Field(max_length=10000)
    order: Literal["timestamp", "trusted_sequence"] = "timestamp"
    assume_independent_trials: bool = Field(default=False, strict=True)
    reference_size: int = Field(default=24, ge=1, le=4096, strict=True)
    window_sizes: list[int] = Field(default_factory=lambda: [1, 6], min_length=1, max_length=4)
    stride: int = Field(default=1, ge=1, strict=True)
    max_looks: int = Field(default=100, ge=1, le=1000, strict=True)
    config: RateSettings = Field(default_factory=RateSettings)

    @field_validator("window_sizes", mode="before")
    @classmethod
    def valid_windows(cls, value):
        if not isinstance(value, list) or any(type(n) is not int or not 1 <= n <= 4096 for n in value) or len(set(value)) != len(value):
            raise ValueError("window_sizes must contain distinct integer sizes in 1..4096")
        return value

    @model_validator(mode="after")
    def ordered_samples(self):
        if len({s.id for s in self.samples}) != len(self.samples):
            raise ValueError("duplicate logical sample IDs")
        times = [s.timestamp for s in self.samples]
        if any(t is not None for t in times):
            if any(t is None for t in times) or times != sorted(times):
                raise ValueError("supply all timestamps in nondecreasing UTC order")
            if self.order != "trusted_sequence" and len(set(times)) != len(times):
                raise ValueError("tied timestamps require trusted_sequence")
        elif self.order != "trusted_sequence":
            raise ValueError("positional counts require trusted_sequence")
        if self.config.max_comparisons != 1 or self.config.comparison_index != 0:
            raise ValueError("monitor owns max_comparisons/comparison_index")
        return self


class RateMonitorResult(Contract):
    schema_version: Literal["rate-v1"] = "rate-v1"
    task: Literal["monitor_rates"] = "monitor_rates"
    status: Literal["completed", "horizon_exhausted", "insufficient_history", "partial"]
    monitor_id: str
    entity: dict[str, str]
    context: RateContext
    input_fingerprint: str
    reference: dict
    evaluations: list[dict]
    first_detection: dict | None = None
    testing: dict
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str]
