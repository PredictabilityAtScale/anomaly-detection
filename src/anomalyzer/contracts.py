"""Versioned contracts. Unknown keys and nonfinite numbers are rejected."""
from typing import Annotated, Any, Literal
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


# Schema 1.1 is deliberately separate from the frozen 1.0 contracts above.
# This avoids changing the generated 1.0 schemas while giving agent-facing
# callers explicit evidence and relationship semantics.

Classification = Literal[
    "observation", "change", "departure_candidate", "supported_departure",
    "criterion_violation",
]
Maturity = Literal["observation_only", "early", "provisional", "calibrated"]
Basis = Literal[
    "descriptive", "explicit_rule", "statistical_baseline",
    "declared_relationship",
]
ReviewState = Literal[
    "unreviewed", "expected_change", "confirmed_incident", "new_regime",
]


class AcceptableRangeRule(Contract):
    id: str = Field(min_length=1)
    kind: Literal["acceptable_range"]
    minimum: float
    maximum: float

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("acceptable range minimum must not exceed maximum")
        return self


class MaximumAbsoluteChangeRule(Contract):
    id: str = Field(min_length=1)
    kind: Literal["maximum_absolute_change"]
    threshold: float = Field(ge=0)


class MaximumRelativeChangeRule(Contract):
    id: str = Field(min_length=1)
    kind: Literal["maximum_relative_change"]
    threshold: float = Field(ge=0)


ExplicitRule = Annotated[
    AcceptableRangeRule | MaximumAbsoluteChangeRule | MaximumRelativeChangeRule,
    Field(discriminator="kind"),
]


class DatasetV11(Dataset):
    entity: dict[str, str] = Field(min_length=1)
    rules: list[ExplicitRule] = Field(default_factory=list)

    @field_validator("rules")
    @classmethod
    def unique_rule_ids(cls, rules):
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset rule ids must be unique")
        return rules


class RatioRelationship(Contract):
    id: str = Field(min_length=1)
    kind: Literal["ratio"]
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)
    alignment: Literal["exact"] = "exact"
    units: str = Field(min_length=1)
    zero_denominator: Literal["inapplicable", "error"] = "inapplicable"
    rules: list[ExplicitRule] = Field(default_factory=list)


class DifferenceRelationship(Contract):
    id: str = Field(min_length=1)
    kind: Literal["difference"]
    minuend: str = Field(min_length=1)
    subtrahend: str = Field(min_length=1)
    alignment: Literal["exact"] = "exact"
    units: str = Field(min_length=1)
    rules: list[ExplicitRule] = Field(default_factory=list)


class NormalizedResidualRelationship(Contract):
    id: str = Field(min_length=1)
    kind: Literal["normalized_residual"]
    observed: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    scale: float = Field(gt=0)
    alignment: Literal["exact"] = "exact"
    units: Literal["standardized_residual"] = "standardized_residual"
    rules: list[ExplicitRule] = Field(default_factory=list)


class LaggedResponseRelationship(Contract):
    id: str = Field(min_length=1)
    kind: Literal["lagged_response"]
    response: str = Field(min_length=1)
    predictor: str = Field(min_length=1)
    lag: int = Field(ge=0, strict=True)
    coefficient: float | None = None
    training_size: int | None = Field(default=None, ge=2, strict=True)
    alignment: Literal["exact"] = "exact"
    units: str = Field(min_length=1)
    rules: list[ExplicitRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def coefficient_source(self):
        if (self.coefficient is None) == (self.training_size is None):
            raise ValueError(
                "lagged_response requires exactly one of coefficient or training_size")
        return self


class JointConditionTerm(Contract):
    dataset: str = Field(min_length=1)
    operator: Literal["lt", "lte", "gt", "gte", "eq"]
    threshold: float


class JointConditionRelationship(Contract):
    id: str = Field(min_length=1)
    kind: Literal["joint_condition"]
    conditions: list[JointConditionTerm] = Field(min_length=2, max_length=4)
    combine: Literal["all", "any"] = "all"
    alignment: Literal["exact"] = "exact"
    units: Literal["condition_met"] = "condition_met"
    rules: list[ExplicitRule] = Field(default_factory=list)


Relationship = Annotated[
    RatioRelationship | DifferenceRelationship |
    NormalizedResidualRelationship | LaggedResponseRelationship |
    JointConditionRelationship,
    Field(discriminator="kind"),
]


class ActionPolicy(Contract):
    allow_explicit_rules: bool = False
    allow_calibrated_departures: bool = False
    notification_requires_action: bool = True


class RequestV11(Contract):
    schema_version: Literal["1.1"]
    task: Literal["analyze"] = "analyze"
    datasets: list[DatasetV11] = Field(min_length=1, max_length=4)
    relationships: list[Relationship] = Field(default_factory=list, max_length=4)
    config: Settings = Field(default_factory=Settings)
    context: Context = Field(default_factory=Context)
    policy: ActionPolicy = Field(default_factory=ActionPolicy)

    @model_validator(mode="after")
    def unique_ids_and_references(self):
        dataset_ids = [dataset.id for dataset in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("dataset ids must be unique")
        relationship_ids = [relationship.id for relationship in self.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("relationship ids must be unique")
        if set(dataset_ids).intersection(relationship_ids):
            raise ValueError("dataset and relationship ids must not overlap")
        known = set(dataset_ids)
        for relationship in self.relationships:
            if relationship.kind == "ratio":
                refs = [relationship.numerator, relationship.denominator]
            elif relationship.kind == "difference":
                refs = [relationship.minuend, relationship.subtrahend]
            elif relationship.kind == "normalized_residual":
                refs = [relationship.observed, relationship.expected]
            elif relationship.kind == "lagged_response":
                refs = [relationship.response, relationship.predictor]
            else:
                refs = [condition.dataset for condition in relationship.conditions]
            missing = sorted(set(refs) - known)
            if missing:
                raise ValueError(
                    f"relationship {relationship.id!r} references unknown datasets: {missing}")
            if len(set(refs)) != len(refs):
                raise ValueError(
                    f"relationship {relationship.id!r} must reference distinct datasets")
        total_points = sum(len(dataset.values) for dataset in self.datasets)
        if total_points > self.config.max_points:
            raise ValueError("request exceeds max_points across all datasets")
        return self


class Assessment(Contract):
    id: str
    target_id: str
    index: int
    timestamp: str | None
    classification: Classification
    maturity: Maturity
    basis: Basis
    action_eligible: bool = False
    notification_eligible: bool = False
    review_state: ReviewState = "unreviewed"
    criterion_met: bool = False
    comparison_population: str
    comparison_samples: int = Field(ge=0)
    baseline: dict[str, Any]
    observed: float
    absolute_change: float | None = None
    relative_change: float | None = None
    direction: Literal["increase", "decrease", "unchanged"]
    evidence_strength: float | None = None
    evidence_strength_semantics: str
    assumptions: list[str]
    established: str
    not_established: str
    evidence_refs: list[str] = Field(default_factory=list)


class LineagePoint(Contract):
    index: int
    timestamp: str
    value: float | None
    source_dataset_ids: list[str]
    source_indexes: dict[str, int]
    source_timestamps: dict[str, str]
    formula: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    units: str
    alignment: Literal["exact"] = "exact"
    lag: int = 0
    unavailable_reason: str | None = None
    latest_source_cutoff: str


class DatasetResultV11(Contract):
    dataset_id: str
    status: Literal[
        "completed", "partial", "failed", "inapplicable",
        "insufficient_history",
    ]
    data_quality: dict[str, Any]
    methods: list[MethodResult]
    observations: list[Observation]
    anomaly_patterns: list[AnomalyPattern]
    assessments: list[Assessment]
    limitations: list[str]
    error: str | None = None


class RelationshipResult(Contract):
    relationship_id: str
    kind: Literal[
        "ratio", "difference", "normalized_residual", "lagged_response",
        "joint_condition",
    ]
    status: Literal[
        "completed", "partial", "failed", "inapplicable",
        "insufficient_history", "insufficient_evidence",
    ]
    definition: dict[str, Any]
    applicability: str
    data_quality: dict[str, Any]
    lineage: list[LineagePoint]
    methods: list[MethodResult]
    observations: list[Observation]
    anomaly_patterns: list[AnomalyPattern]
    assessments: list[Assessment]
    limitations: list[str]
    error: str | None = None


class Case(Contract):
    id: str
    revision_id: str
    entity: dict[str, str]
    event_time: str | int
    detection_time: str | int
    source_availability_cutoff: str | int
    contributing_dataset_ids: list[str]
    contributing_relationship_ids: list[str]
    supporting_evidence: list[str]
    conflicting_evidence: list[str]
    unavailable_evidence: list[str]
    correlated_evidence_groups: list[list[str]]
    evidence_refs: list[str]
    maturity: Maturity
    action_eligible: bool
    notification_eligible: bool
    business_impact: Literal["unresolved"] = "unresolved"
    suggested_investigation_questions: list[str]
    non_claims: list[str]


class ResultV11(Contract):
    schema_version: Literal["1.1"] = "1.1"
    run_id: str
    task: Literal["analyze"] = "analyze"
    status: Literal[
        "completed", "partial", "failed", "inapplicable",
        "insufficient_history",
    ]
    input_fingerprint: str
    resolved_config: dict[str, Any]
    dependencies: dict[str, str]
    dataset_results: list[DatasetResultV11]
    relationship_results: list[RelationshipResult]
    cases: list[Case]
    limitations: list[str]
    runtime_seconds: float
    stop_reason: str
