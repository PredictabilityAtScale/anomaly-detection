"""Independent forecast-v1 contracts; no changes to analysis request semantics."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from .contracts import Contract

Finite = float
PeriodStatus = Literal["complete", "partial", "missing"]
Maturity = Literal["unavailable", "reference_only", "provisional", "calibrated"]
Reason = Literal["invalid_input", "unsupported_contract", "insufficient_history",
                 "missing_history", "analysis_incomplete", "budget_exceeded",
                 "nonfinite_result", "analysis_failed"]


def advance_bucket(value: datetime, interval: str) -> datetime:
    """Hours follow UTC; larger buckets follow the declared local calendar."""
    if interval == "hour":
        return (value.astimezone(timezone.utc) + timedelta(hours=1)).astimezone(value.tzinfo)
    if interval in ("day", "week"):
        return value + timedelta(days=1 if interval == "day" else 7)
    if interval == "month":
        return value.replace(year=value.year + (value.month == 12), month=value.month % 12 + 1)
    return value.replace(year=value.year + 1)


class ForecastDataset(Contract):
    id: str = Field(default="series", min_length=1, strict=True)
    units: str | None = None
    values: list[Finite | None] = Field(min_length=1, max_length=6000)
    period_statuses: list[PeriodStatus] | None = None
    interval: Literal["hour", "day", "week", "month", "year"] = "day"
    timezone: str = "UTC"
    timestamps: list[str] | None = None

    @field_validator("values", mode="before")
    @classmethod
    def numeric_values(cls, values):
        if not isinstance(values, list):
            raise ValueError("values must be an ordered list")
        for value in values:
            if value is not None:
                if type(value) not in (int, float):
                    raise ValueError("observations must be finite numbers or null")
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("observations must be finite")
        return values

    @model_validator(mode="after")
    def calendar_and_statuses(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must be an IANA timezone") from error
        if self.period_statuses is None:
            if any(value is None for value in self.values):
                raise ValueError("null requires an explicit partial or missing status")
            self.period_statuses = ["complete"] * len(self.values)
        if len(self.period_statuses) != len(self.values):
            raise ValueError("period_statuses must align with values")
        for value, status in zip(self.values, self.period_statuses):
            if status == "complete" and value is None:
                raise ValueError("complete periods require a measured value (zero is valid)")
            if status == "missing" and value is not None:
                raise ValueError("missing periods require null")
        if self.timestamps is not None:
            if len(self.timestamps) != len(self.values):
                raise ValueError("timestamps must align with all supplied buckets")
            previous = None
            for raw in self.timestamps:
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError as error:
                    raise ValueError("timestamps must be ISO 8601 bucket starts") from error
                if parsed.utcoffset() is None:
                    raise ValueError("timestamps require explicit UTC offsets")
                local = parsed.astimezone(zone)
                if local.minute or local.second or local.microsecond:
                    raise ValueError("timestamps must be bucket starts")
                if self.interval != "hour" and local.hour:
                    raise ValueError("calendar buckets must start at local midnight")
                if self.interval in ("month", "year") and local.day != 1:
                    raise ValueError("month/year buckets start on day one")
                if self.interval == "year" and local.month != 1:
                    raise ValueError("year buckets start on January one")
                if previous is not None and (
                    advance_bucket(previous, self.interval).astimezone(timezone.utc)
                    != local.astimezone(timezone.utc)
                ):
                    raise ValueError("timestamps must be unique, ordered and contiguous at declared cadence")
                previous = local
        return self


class ForecastSeasonality(Contract):
    period: int = Field(ge=1, le=1500, strict=True)


class ForecastSettings(Contract):
    horizon: int = Field(default=30, ge=1, le=6000, strict=True)
    trend: Literal["auto", "none", "linear", "exponential"] = "auto"
    seasonality: Literal["auto"] | ForecastSeasonality = "auto"
    outlier_handling: Literal["robust", "include"] = "robust"
    trend_adjustment_pct: float = Field(default=0.0, ge=-50, le=200)
    lower_bound: float | None = None
    max_training_points: int = Field(default=56, ge=8, le=6000, strict=True)
    max_inference_points: int = Field(default=768, ge=8, le=4096, strict=True)
    max_points: int = Field(default=6000, ge=1, le=6000, strict=True)
    max_runtime_seconds: float = Field(default=2.5, gt=0, le=3600)

    @field_validator("trend_adjustment_pct", "lower_bound", "max_runtime_seconds", mode="before")
    @classmethod
    def numeric_settings(cls, value):
        if value is not None and type(value) not in (int, float):
            raise ValueError("setting must be a finite number")
        return value


class ForecastRequest(Contract):
    schema_version: Literal["forecast-v1"] = "forecast-v1"
    task: Literal["forecast"] = "forecast"
    dataset: ForecastDataset
    config: ForecastSettings = Field(default_factory=ForecastSettings)

    @model_validator(mode="after")
    def point_limit(self):
        if len(self.dataset.values) > self.config.max_points:
            raise ValueError("dataset exceeds max_points")
        return self


class ForecastCounts(Contract):
    complete: int = Field(ge=0)
    partial: int = Field(ge=0)
    missing: int = Field(ge=0)


class ForecastModel(Contract):
    method: Literal["anomalyzer"] = "anomalyzer"
    engine_version: str
    trend_kind: Literal["none", "linear", "exponential"]
    trend_parameters: dict[str, Any]
    season_length: int = Field(ge=1)
    season_inference: dict[str, Any]
    fit_window: tuple[int, int]
    effective_trend_window: tuple[int, int] | None
    historical_selection_window: tuple[int, int] | None
    historical_training_window: tuple[int, int] | None
    historical_inference: dict[str, Any] | None
    historical_readiness: dict[str, Any]
    outlier_policy: dict[str, Any]


class ForecastResult(Contract):
    schema_version: Literal["forecast-v1"] = "forecast-v1"
    task: Literal["forecast"] = "forecast"
    engine_version: str
    status: Literal["completed", "unavailable"]
    reason: Reason | None = None
    request_fingerprint: str | None = None
    resolved_config: ForecastSettings | None = None
    counts: ForecastCounts | None = None
    forecast_applicability: Literal["scenario_available", "unavailable"] = "unavailable"
    expected: list[Finite | None] | None = None
    eligible: list[bool] | None = None
    predicted: list[Finite] | None = None
    trend: list[Finite] | None = None
    seasonal_component: list[Finite] | None = None
    outlier_indices: list[int] | None = None
    historical_evidence_maturity: list[Maturity] | None = None
    future_origin_index: int | None = None
    predicted_timestamps: list[str] | None = None
    model: ForecastModel | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_result(self):
        series = (self.expected, self.eligible, self.predicted, self.trend,
                  self.seasonal_component, self.outlier_indices, self.historical_evidence_maturity)
        if self.status == "unavailable":
            if self.reason is None or any(item is not None for item in series) or self.model is not None:
                raise ValueError("unavailable results require a reason and no partial series/model")
            if self.forecast_applicability != "unavailable":
                raise ValueError("unavailable forecast cannot be applicable")
            return self
        if (self.reason is not None or any(item is None for item in series)
                or self.model is None or self.counts is None or self.resolved_config is None
                or self.request_fingerprint is None or self.forecast_applicability != "scenario_available"):
            raise ValueError("completed results require complete series and provenance")
        n, h = sum(self.counts.model_dump().values()), self.resolved_config.horizon
        if (len(self.expected) != n or len(self.eligible) != n or len(self.predicted) != h
                or len(self.trend) != n + h or len(self.seasonal_component) != n + h
                or len(self.historical_evidence_maturity) != n or self.future_origin_index != n
                or self.predicted_timestamps is not None and len(self.predicted_timestamps) != h):
            raise ValueError("forecast series must align with original buckets and horizon")
        if self.outlier_indices != sorted(set(self.outlier_indices)) or any(i < 0 or i >= n for i in self.outlier_indices):
            raise ValueError("outlier indices must be unique original positions")
        if any(flag != (maturity == "calibrated") or flag and expected is None
               for flag, maturity, expected in zip(self.eligible, self.historical_evidence_maturity, self.expected)):
            raise ValueError("eligibility requires calibrated available expectations")
        return self
