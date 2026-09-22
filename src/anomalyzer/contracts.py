"""Versioned contracts. Unknown keys and nonfinite numbers are rejected."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import NotRequired, TypedDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Settings(Contract):
    recipe: Literal["seasonal-residual-v1", "multi-resolution-v1"] = "seasonal-residual-v1"
    season_length: int = Field(default=1, ge=1, le=10000, strict=True)
    completed_period_season_length: int = Field(default=7, ge=1, le=10000, strict=True)
    intraday_season_length: int | None = Field(default=None, ge=1, le=10000, strict=True)
    aggregate_function: Literal["sum", "mean", "last"] = "sum"
    aggregate_anchor: str | None = None
    trend: Literal["auto", "none", "linear", "exponential"] = "auto"
    outlier_handling: Literal["robust", "include"] = "robust"
    reset_points: list[int | str] = Field(default_factory=list)
    training_size: int = Field(default=28, ge=2, strict=True)
    calibration_size: int = Field(default=14, ge=3, strict=True)
    point_threshold: float = Field(default=3.0, gt=0)
    cusum_k: float = Field(default=0.5, gt=0)
    cusum_h: float = Field(default=5.0, gt=0)
    moving_range_threshold: float = Field(default=3.686, gt=0)
    scale_floor: float = Field(default=1e-8, gt=0)
    duplicate_policy: Literal["error", "mean", "sum"] = "error"
    max_points: int = Field(default=10000, ge=1, le=1000000, strict=True)
    max_bytes: int = Field(default=10000000, ge=1, le=100000000, strict=True)
    max_runtime_seconds: float = Field(default=60, gt=0, le=3600)

    @field_validator("reset_points")
    @classmethod
    def valid_reset_points(cls, values):
        if any(isinstance(value, bool) or not isinstance(value, (int, str))
               or isinstance(value, str) and not value.strip() for value in values):
            raise ValueError("reset_points must contain nonempty timestamps or integer sample positions")
        if len({(type(value), value) for value in values}) != len(values):
            raise ValueError("reset_points must be unique")
        return values

class Dataset(Contract):
    id: str = Field(default="series", min_length=1)
    timestamps: list[str] | None = None
    values: list[float | None]
    frequency: str | None = Field(default=None, pattern=r"^[1-9][0-9]*(s|min|h|d|w)$")
    timezone: str | None = None
    units: str | None = Field(default=None, min_length=1)
    entity: dict[str, str] = Field(default_factory=dict)
    period_statuses: list[Literal["complete", "incomplete"]] | None = None

    @model_validator(mode="before")
    @classmethod
    def numeric_values(cls, data):
        if isinstance(data, dict) and isinstance(data.get("values"), list) and any(v is not None and (isinstance(v, bool) or not isinstance(v, (float, int))) for v in data["values"]):
            raise ValueError("values must contain numbers or null")
        return data

    @model_validator(mode="after")
    def aligned(self):
        if self.timestamps is None:
            if self.frequency is not None or self.timezone is not None:
                raise ValueError("frequency and timezone require timestamps")
        elif self.frequency is None:
            raise ValueError("timestamps require frequency")
        elif len(self.timestamps) != len(self.values):
            raise ValueError("timestamps and values must have equal length")
        if self.period_statuses is not None and len(self.period_statuses) != len(self.values):
            raise ValueError("period_statuses and values must have equal length")
        return self


class Context(Contract):
    concern: str | None = None
    known_events: list[str] = Field(default_factory=list)
    as_of: str | None = None


class Request(Contract):
    schema_version: Literal["1.0"] = "1.0"
    task: Literal["analyze"] = "analyze"
    datasets: list[Dataset] = Field(min_length=1, max_length=1)
    config: Settings = Field(default_factory=Settings)
    context: Context = Field(default_factory=Context)


class Evidence(TypedDict):
    id: str
    method: str
    index: int
    timestamp: str | None
    training_cutoff: str | int
    observed: float
    expected: float
    residual: float
    relative_deviation: float | None
    standardized_residual: float | None
    signal_maturity: Literal["reference_only", "provisional", "calibrated"]
    calibration_samples: int
    triggers: list[Literal["point"]]
    score_semantics: str
    excluded_from_model: bool
    model_value: float
    exclusion_reason: str | None
    reference_action: Literal["use_observed", "use_expected"]


class Observation(TypedDict):
    id: str
    dataset: str
    interval: list[str | int]
    direction: Literal["increase", "decrease", "mixed"]
    magnitude: float
    observed_statistic: float
    reference: float
    triggering_samples: list[int]
    evidence_refs: list[str]
    supporting_methods: list[str]
    quiet_methods: list[str]
    business_impact: Literal["unresolved"]


class AnomalyPattern(TypedDict):
    id: str
    dataset: str
    kind: Literal["consecutive_run", "location_shift", "residual_trend",
                  "systematic_oscillation", "mixture_pattern", "variation_shift"]
    rule: Literal["adjacent_point_anomalies", "cusum", "moving_range",
                  "nelson_rule_2", "nelson_rule_3", "nelson_rule_4",
                  "nelson_rule_5", "nelson_rule_6", "nelson_rule_8"]
    description: str
    interval: list[str | int]
    sample_count: int
    triggering_samples: list[int]
    detection_index: int
    peak_standardized_residual: float
    direction: Literal["increase", "decrease", "mixed"]
    evidence_refs: list[str]
    peak_cusum: NotRequired[float]
    peak_moving_range: NotRequired[float]
    detector_threshold: NotRequired[float]


class MethodResult(Contract):
    id: str
    status: Literal["completed", "inapplicable", "insufficient_history", "failed", "budget_exceeded"]
    runtime_seconds: float = 0
    parameters: dict[str, Any] = Field(default_factory=dict)
    applicability: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None


class Result(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    task: Literal["analyze"] = "analyze"
    status: Literal["completed", "partial", "failed", "inapplicable", "insufficient_history"]
    input_fingerprint: str
    resolved_config: dict[str, Any]
    dependencies: dict[str, str]
    data_quality: dict[str, Any]
    methods: list[MethodResult]
    observations: list[Observation]
    anomaly_patterns: list[AnomalyPattern]
    limitations: list[str]
    suggested_checks: list[str]
    runtime_seconds: float
    stop_reason: str
