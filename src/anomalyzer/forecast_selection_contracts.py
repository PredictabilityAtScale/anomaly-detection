"""Opt-in forward-model and selection contracts, separate from forecast-v1."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Contract
from .forecast_contracts import ForecastCounts, ForecastDataset, Reason

ForecastMethod = Literal["naive", "seasonal_naive", "mean", "median", "ses",
                         "local_trend", "damped_local_trend", "anomalyzer"]


class ForecastCandidate(Contract):
    id: str = Field(min_length=1, max_length=80, strict=True)
    method: ForecastMethod
    training_window: int | None = Field(default=None, ge=8, le=6000, strict=True)
    period: int | None = Field(default=None, ge=1, le=1500, strict=True)
    alpha: float | None = Field(default=None, gt=0, le=1)
    damping: float | None = Field(default=None, gt=0, le=1)
    # These settings belong only to the existing Anomalyzer family. Other
    # methods use measured observations, without an implicit robust transform.
    outlier_handling: Literal["include", "robust"] = "include"
    trend: Literal["auto", "none", "linear", "exponential"] | None = None
    baseline: Literal["legacy", "recent-level-v1"] | None = None

    @field_validator("alpha", "damping", mode="before")
    @classmethod
    def numeric_parameters(cls, value):
        if value is not None and type(value) not in (int, float):
            raise ValueError("model parameters must be finite numbers")
        return value

    @model_validator(mode="after")
    def method_parameters(self):
        if self.method == "ses":
            self.alpha = .25 if self.alpha is None else self.alpha
        elif self.alpha is not None:
            raise ValueError("alpha belongs to ses")
        if self.method == "damped_local_trend":
            self.damping = .9 if self.damping is None else self.damping
        elif self.damping is not None:
            raise ValueError("damping belongs to damped_local_trend")
        if self.method == "anomalyzer":
            self.trend = self.trend or "auto"
            self.baseline = self.baseline or "legacy"
        elif self.trend is not None or self.baseline is not None or self.outlier_handling != "include":
            raise ValueError("trend, baseline and robust handling belong to anomalyzer")
        if self.period is not None and self.method not in (
                "seasonal_naive", "local_trend", "damped_local_trend", "anomalyzer"):
            raise ValueError("period is not used by this method")
        return self


class ModelForecastSettings(Contract):
    horizon: int = Field(default=14, ge=1, le=6000, strict=True)
    lower_bound: float | None = None
    trend_adjustment_pct: float = Field(default=0, ge=-50, le=200)
    max_points: int = Field(default=6000, ge=1, le=6000, strict=True)
    max_runtime_seconds: float = Field(default=10, gt=0, le=3600)

    @field_validator("lower_bound", "trend_adjustment_pct", "max_runtime_seconds", mode="before")
    @classmethod
    def numeric_parameters(cls, value):
        if value is not None and type(value) not in (int, float):
            raise ValueError("settings must be finite numbers")
        return value


class ForecastSelectionSettings(ModelForecastSettings):
    objective: Literal["mae", "rmse", "total_absolute_error"] = "mae"
    folds: int = Field(default=3, ge=3, le=8, strict=True)
    min_training_points: int = Field(default=28, ge=8, le=6000, strict=True)

    @model_validator(mode="after")
    def unadjusted_selection(self):
        if self.trend_adjustment_pct != 0:
            raise ValueError("select unadjusted models; apply scenario adjustments in forecast_with_model")
        return self


def default_forecast_candidates(interval: str = "day") -> list[ForecastCandidate]:
    """Small deterministic grid; never infer a period from held-out values."""
    period = {"hour": 168, "day": 7, "week": 4, "month": 12, "year": 1}[interval]
    window = {"hour": 1344, "day": 56, "week": 52, "month": 36, "year": 36}[interval]
    entries = [
        dict(id="naive", method="naive"),
        dict(id="seasonal-naive", method="seasonal_naive", period=period),
        dict(id="mean-recent", method="mean", training_window=max(8, 2 * period)),
        dict(id="median-recent", method="median", training_window=max(8, 2 * period)),
        *[dict(id=f"ses-{alpha}", method="ses", alpha=alpha) for alpha in (.1, .25, .5, .75)],
        dict(id="local-trend", method="local_trend", period=period),
        *[dict(id=f"damped-local-{damping}", method="damped_local_trend", period=period,
               damping=damping) for damping in (.8, .95)],
        *[dict(id=f"anomalyzer-{baseline}-{policy}", method="anomalyzer",
               baseline=baseline, outlier_handling=policy)
          for baseline in ("legacy", "recent-level-v1") for policy in ("include", "robust")],
    ]
    return [ForecastCandidate.model_validate({"training_window": window, **entry}) for entry in entries]


class ModelForecastRequest(Contract):
    schema_version: Literal["forecast-model-v1"] = "forecast-model-v1"
    task: Literal["forecast_model"] = "forecast_model"
    dataset: ForecastDataset
    candidate: ForecastCandidate
    config: ModelForecastSettings = Field(default_factory=ModelForecastSettings)

    @model_validator(mode="after")
    def point_limit(self):
        if len(self.dataset.values) > self.config.max_points:
            raise ValueError("dataset exceeds max_points")
        self.candidate = _resolve_window(self.candidate, self.dataset.interval)
        return self


class ForecastSelectionRequest(Contract):
    schema_version: Literal["forecast-selection-v1"] = "forecast-selection-v1"
    task: Literal["select_forecast"] = "select_forecast"
    dataset: ForecastDataset
    config: ForecastSelectionSettings = Field(default_factory=ForecastSelectionSettings)
    candidates: list[ForecastCandidate] | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def resolve_candidates(self):
        if len(self.dataset.values) > self.config.max_points:
            raise ValueError("dataset exceeds max_points")
        if self.candidates is None:
            self.candidates = default_forecast_candidates(self.dataset.interval)
        self.candidates = [_resolve_window(c, self.dataset.interval) for c in self.candidates]
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        return self


def _resolve_window(candidate, interval):
    if candidate.training_window is not None:
        return candidate
    window = {"hour": 1344, "day": 56, "week": 52, "month": 36, "year": 36}[interval]
    return candidate.model_copy(update={"training_window": window})


class ModelForecastInfo(Contract):
    candidate: ForecastCandidate
    fit_window: tuple[int, int]
    anchor_index: int
    period: int = Field(ge=1)
    parameters: dict[str, Any]


class ModelForecastResult(Contract):
    schema_version: Literal["forecast-model-v1"] = "forecast-model-v1"
    task: Literal["forecast_model"] = "forecast_model"
    engine_version: str
    status: Literal["completed", "unavailable"]
    reason: Reason | None = None
    request_fingerprint: str | None = None
    resolved_config: ModelForecastSettings | None = None
    counts: ForecastCounts | None = None
    predicted: list[float] | None = None
    trend: list[float] | None = None
    seasonal_component: list[float] | None = None
    predicted_timestamps: list[str] | None = None
    model: ModelForecastInfo | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_result(self):
        parts = (self.predicted, self.trend, self.seasonal_component, self.model)
        if self.status == "unavailable":
            if self.reason is None or any(p is not None for p in (*parts, self.predicted_timestamps)):
                raise ValueError("unavailable results cannot contain a partial projection")
        else:
            if (self.reason is not None or any(p is None for p in parts) or self.counts is None
                    or self.resolved_config is None or self.request_fingerprint is None):
                raise ValueError("completed projections require provenance and all components")
            n = sum(self.counts.model_dump().values())
            h = self.resolved_config.horizon
            if (len(self.predicted) != h or len(self.trend) != n + h or len(self.seasonal_component) != n + h
                    or self.predicted_timestamps is not None and len(self.predicted_timestamps) != h):
                raise ValueError("projection must align with supplied buckets and horizon")
            left, right = self.model.fit_window
            if not 0 <= left <= right == self.model.anchor_index == self.counts.complete - 1:
                raise ValueError("fit window must end at the final complete observation")
        return self


class ForecastFoldScore(Contract):
    training_window: tuple[int, int]
    holdout_window: tuple[int, int]
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    wape: float | None = Field(default=None, ge=0)
    bias: float
    total_absolute_error: float = Field(ge=0)

    @model_validator(mode="after")
    def chronological_fold(self):
        a, b = self.training_window
        c, d = self.holdout_window
        if not 0 <= a <= b < c <= d:
            raise ValueError("training must precede the full holdout")
        return self


class ForecastCandidateScore(Contract):
    candidate: ForecastCandidate
    status: Literal["completed", "unavailable"]
    reason: Reason | None = None
    loss: float | None = Field(default=None, ge=0)
    mae: float | None = Field(default=None, ge=0)
    rmse: float | None = Field(default=None, ge=0)
    wape: float | None = Field(default=None, ge=0)
    bias: float | None = None
    by_lead_mae: list[float] | None = None
    folds: list[ForecastFoldScore] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_score(self):
        metrics = (self.loss, self.mae, self.rmse, self.bias, self.by_lead_mae)
        if self.status == "completed":
            if self.reason is not None or any(m is None for m in metrics) or len(self.folds) < 3:
                raise ValueError("ranked candidates need complete holdout scores")
        elif self.reason is None or any(m is not None for m in (*metrics, self.wape)):
            raise ValueError("failed candidates cannot be ranked from partial scores")
        return self


class ForecastSelectionResult(Contract):
    schema_version: Literal["forecast-selection-v1"] = "forecast-selection-v1"
    task: Literal["select_forecast"] = "select_forecast"
    engine_version: str
    status: Literal["completed", "unavailable"]
    reason: Reason | Literal["no_viable_candidate"] | None = None
    request_fingerprint: str | None = None
    resolved_config: ForecastSelectionSettings | None = None
    scores: list[ForecastCandidateScore] | None = None
    selected_candidate: ForecastCandidate | None = None
    forecast: ModelForecastResult | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_selection(self):
        if self.status == "unavailable":
            if self.reason is None or self.selected_candidate is not None or self.forecast is not None:
                raise ValueError("unavailable selection cannot claim a winner")
        elif (self.reason is not None or self.scores is None or self.selected_candidate is None
              or self.forecast is None or self.forecast.status != "completed"
              or self.resolved_config is None or self.request_fingerprint is None):
            raise ValueError("completed selection requires scores, winner and forecast")
        if self.status == "completed":
            ids = [s.candidate.id for s in self.scores]
            viable = [s for s in self.scores if s.status == "completed"]
            selected = [s for s in viable if s.candidate == self.selected_candidate]
            h, count = self.resolved_config.horizon, self.resolved_config.folds
            if (len(ids) != len(set(ids)) or len(selected) != 1
                    or self.forecast.model.candidate != self.selected_candidate
                    or self.forecast.resolved_config.horizon != h):
                raise ValueError("winner must identify a ranked candidate and its matching projection")
            windows = [f.holdout_window for f in selected[0].folds]
            if any(len(s.folds) != count or len(s.by_lead_mae) != h
                   or [f.holdout_window for f in s.folds] != windows for s in viable):
                raise ValueError("ranked candidates must share all full-horizon holdouts")
            if any(right - left + 1 != h or right >= self.forecast.counts.complete
                   for left, right in windows):
                raise ValueError("holdouts must contain only complete observed targets")
        return self
