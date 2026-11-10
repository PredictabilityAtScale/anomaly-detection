"""Explicit forward models and bounded, horizon-matched model comparison.

This module never chooses a historical anomaly reference or detector threshold.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ._version import __version__
from .budget import RuntimeBudget
from .forecast import forecast_series
from .forecast_contracts import ForecastCounts, ForecastDataset, advance_bucket
from .forecast_selection_contracts import (
    ForecastCandidateScore, ForecastFoldScore, ForecastSelectionRequest,
    ForecastSelectionResult, ModelForecastInfo, ModelForecastRequest,
    ModelForecastResult, ModelForecastSettings,
)

MODEL_LIMITATIONS = [
    "Forward scenarios have no calibrated uncertainty intervals or accuracy guarantee.",
    "Trend and seasonal components describe the current fit across history; they are not causal historical anomaly references.",
    "Local trend reproduces UsageTap Current with outlier exclusion disabled; fixed interval periods are assumptions, not discovered cycles.",
    "No separate irregular-cycle component is estimated; unexplained cycles and structural changes may remain in residuals.",
    "Runtime budgets are cooperative; callers must enforce hard transport deadlines.",
]
SELECTION_LIMITATIONS = [
    "Selection loss is validation evidence used to choose settings, not an unbiased estimate of the winner's future accuracy; use separate outer holdouts.",
    "The winner minimizes the declared objective among the supplied viable candidates on these folds only; future optimality is not guaranteed.",
    "All ranked candidates use identical full-horizon holdouts; settings and model may change when the requested horizon changes.",
    "Forecast selection does not change or calibrate anomaly references, thresholds, incidents or existing forecast defaults.",
]


class _UnsupportedContract(ValueError):
    pass


def _dump(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _dataset(value):
    return {"values": value} if isinstance(value, list) else _dump(value)


def _request(dataset, settings, cls, **extra):
    if isinstance(dataset, str):
        dataset = json.loads(dataset)
    canonical = isinstance(dataset, cls) or isinstance(dataset, dict) and any(
        key in dataset for key in ("dataset", "schema_version", "task"))
    if canonical:
        if settings is not None or any(v is not None for v in extra.values()):
            raise ValueError("canonical requests contain their own settings and candidates")
        raw = _dump(dataset)
    else:
        raw = {"dataset": _dataset(dataset), "config": _dump(settings) if settings is not None else {},
               **{k: _dump(v) if not isinstance(v, list) else [_dump(i) for i in v]
                  for k, v in extra.items() if v is not None}}
    if isinstance(raw, dict) and any(raw.get(key, cls.model_fields[key].default) != cls.model_fields[key].default
                                    for key in ("schema_version", "task")):
        raise _UnsupportedContract("unsupported forecast contract")
    return cls.model_validate(raw)


def _fingerprint(request):
    return hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _counts(data):
    return ForecastCounts(**{status: data.period_statuses.count(status)
                            for status in ("complete", "partial", "missing")})


def _history_reason(data, counts):
    if counts.missing or any(s != "complete" for s in data.period_statuses[:counts.complete]):
        return "missing_history"
    return "insufficient_history" if counts.complete < 8 else None


def _future_timestamps(data, horizon, budget):
    if data.timestamps is None:
        return None
    at = datetime.fromisoformat(data.timestamps[-1].replace("Z", "+00:00")).astimezone(ZoneInfo(data.timezone))
    timestamps = []
    for _ in range(horizon):
        budget.check()
        at = advance_bucket(at, data.interval)
        timestamps.append(at.isoformat())
    return timestamps


def _local_parameters(history, start, period, check):
    """UsageTap fitLocalTrend/fitLocalModel, with original positional phases."""
    anchor = start + len(history) - 1
    recent = list(enumerate(history, start))[-2 * period:]
    by_index = dict(recent)
    slopes = [(value - by_index[index - period]) / period
              for index, value in recent if index - period in by_index]
    if len(slopes) < 3:
        slopes = []
        stride = max(1, len(recent) // 48)
        for end in range(len(recent) - 1, 0, -stride):
            check()
            for begin in range(end - 1, -1, -1):
                distance = recent[end][0] - recent[begin][0]
                if distance > 24:
                    break
                slopes.append((recent[end][1] - recent[begin][1]) / distance)
    slope = median(slopes) if slopes else 0.
    level = median(value + slope * (anchor - index) for index, value in recent)
    groups = [[] for _ in range(period)]
    for index, value in list(enumerate(history, start))[-3 * period:]:
        check()
        groups[index % period].append(value - (level + slope * (index - anchor)))
    seasonal = [median(group) if len(group) >= 3 else None for group in groups]
    supported = [value for value in seasonal if value is not None]
    # Follow the original arithmetic order for numerical parity.
    center = sum(supported) / len(supported) if supported else 0.
    offsets = [0. if value is None else .8 * (value - center) for value in seasonal]
    return level, slope, offsets, (recent[0][0], anchor)


def _project(data, candidate, config, budget):
    """One fixed fit; neither holdout targets nor synthetic points enter it."""
    budget.check()
    counts = _counts(data)
    reason = _history_reason(data, counts)
    if reason:
        return None, reason
    observed, n, h = counts.complete, len(data.values), config.horizon
    start = max(0, observed - candidate.training_window)
    history = data.values[start:observed]
    anchor = observed - 1
    period = candidate.period or {"hour": 168, "day": 7, "week": 4, "month": 12, "year": 1}[data.interval]
    method = candidate.method
    if method == "anomalyzer":
        result = forecast_series(data, dict(horizon=h, trend=candidate.trend,
            seasonality={"period": candidate.period} if candidate.period is not None else "auto",
            baseline=candidate.baseline, outlier_handling=candidate.outlier_handling,
            max_training_points=candidate.training_window, lower_bound=config.lower_bound,
            trend_adjustment_pct=config.trend_adjustment_pct, max_points=config.max_points,
            max_runtime_seconds=max(1e-9, budget.remaining)))
        budget.check()
        if result.status != "completed":
            return None, result.reason
        payload = dict(predicted=result.predicted, trend=result.trend,
            seasonal_component=result.seasonal_component,
            model=ModelForecastInfo(candidate=candidate, fit_window=result.model.fit_window,
                anchor_index=anchor, period=result.model.season_length,
                parameters={"native_model": result.model.model_dump(mode="json"),
                            "native_request_fingerprint": result.request_fingerprint}))
        return payload, None
    slope, offsets = 0., [0.]
    parameters = {}
    if method in ("local_trend", "damped_local_trend"):
        level, slope, offsets, slope_window = _local_parameters(history, start, period, budget.check)
        parameters = {"slope_window": slope_window, "seasonal_window": (max(start, observed - 3 * period), anchor),
                      "seasonal_weight": .8, "damping": candidate.damping}
    elif method == "seasonal_naive":
        if len(history) < period:
            return None, "insufficient_history"
        # Center the last cycle. Index offsets by original positional phase.
        level = math.fsum(history[-period:]) / period
        offsets = [0.] * period
        for index in range(observed - period, observed):
            offsets[index % period] = data.values[index] - level
    else:
        period = 1
        if method == "mean":
            level = math.fsum(history) / len(history)
        elif method == "median":
            level = median(history)
        elif method == "ses":
            level = history[0]
            for value in history[1:]:
                budget.check()
                level = candidate.alpha * value + (1 - candidate.alpha) * level
        else:
            level = history[-1]
    parameters.update(level=level, slope=slope)
    components, seasonal, predicted = [], [], []
    for index in range(n + h):
        budget.check()
        elapsed = index - anchor
        if method == "damped_local_trend" and elapsed > 0 and candidate.damping != 1:
            damping = candidate.damping
            elapsed = damping * -math.expm1(elapsed * math.log(damping)) / (1 - damping)
        factor = 1 + config.trend_adjustment_pct / 100 if index >= n else 1
        component = level + slope * elapsed * factor
        offset = offsets[index % period]
        components.append(component)
        seasonal.append(offset)
        if index >= n:
            raw = component + offset
            predicted.append(max(config.lower_bound, raw) if config.lower_bound is not None else raw)
    if not all(math.isfinite(value) for value in (*components, *seasonal, *predicted)):
        return None, "nonfinite_result"
    return dict(predicted=predicted, trend=components, seasonal_component=seasonal,
        model=ModelForecastInfo(candidate=candidate, fit_window=(start, anchor),
            anchor_index=anchor, period=period, parameters=parameters)), None


def _forecast_result(request, budget):
    provenance = dict(engine_version=__version__, request_fingerprint=_fingerprint(request),
                      resolved_config=request.config, counts=_counts(request.dataset))
    payload, reason = _project(request.dataset, request.candidate, request.config, budget)
    if reason:
        return ModelForecastResult(**provenance, status="unavailable", reason=reason)
    timestamps = _future_timestamps(request.dataset, request.config.horizon, budget)
    budget.check()
    return ModelForecastResult(**provenance, status="completed", **payload,
        predicted_timestamps=timestamps, limitations=list(MODEL_LIMITATIONS))


def forecast_with_model(dataset, candidate=None, settings=None) -> ModelForecastResult:
    """Project an explicitly chosen candidate without changing anomaly evidence.

    Accept a ForecastDataset/dict/list plus candidate and settings, or one
    ModelForecastRequest/dict/JSON string containing all fields.
    """
    budget = RuntimeBudget(3600)
    provenance = dict(engine_version=__version__)
    try:
        request = _request(dataset, settings, ModelForecastRequest, candidate=candidate)
    except _UnsupportedContract:
        return ModelForecastResult(**provenance, status="unavailable", reason="unsupported_contract")
    except (ValidationError, ValueError, TypeError, OverflowError):
        return ModelForecastResult(**provenance, status="unavailable", reason="invalid_input")
    budget.seconds = request.config.max_runtime_seconds
    provenance.update(request_fingerprint=_fingerprint(request), resolved_config=request.config,
                      counts=_counts(request.dataset))
    try:
        return _forecast_result(request, budget)
    except TimeoutError:
        reason = "budget_exceeded"
    except (OverflowError, ArithmeticError):
        reason = "nonfinite_result"
    except RuntimeError:
        reason = "analysis_incomplete"
    except (ValidationError, ValueError, TypeError, KeyError, IndexError):
        reason = "analysis_failed"
    return ModelForecastResult(**provenance, status="unavailable", reason=reason)


def _metrics(errors, actual):
    absolute = math.fsum(abs(e) for e in errors)
    denominator = math.fsum(abs(v) for v in actual)
    # hypot avoids overflow in sum(error**2) when the resulting RMSE is finite.
    return dict(mae=absolute / len(errors), rmse=math.hypot(*errors) / math.sqrt(len(errors)),
                wape=absolute / denominator if denominator else None,
                bias=math.fsum(errors) / len(errors), total_absolute_error=abs(math.fsum(errors)))


def select_forecast(dataset, settings=None, candidates=None) -> ForecastSelectionResult:
    """Auto-select and refit a forward model on identical full-horizon folds.

    The validation result is deliberately separate from forecast-v1 historical
    expectations and native anomaly calibration. Ties retain candidate order.
    """
    budget = RuntimeBudget(3600)
    provenance = dict(engine_version=__version__)
    try:
        request = _request(dataset, settings, ForecastSelectionRequest, candidates=candidates)
    except _UnsupportedContract:
        return ForecastSelectionResult(**provenance, status="unavailable", reason="unsupported_contract")
    except (ValidationError, ValueError, TypeError, OverflowError):
        return ForecastSelectionResult(**provenance, status="unavailable", reason="invalid_input")
    config, data = request.config, request.dataset
    budget.seconds = config.max_runtime_seconds
    provenance.update(request_fingerprint=_fingerprint(request), resolved_config=config)
    try:
        budget.check()
        counts = _counts(data)
        reason = _history_reason(data, counts)
        if reason:
            return ForecastSelectionResult(**provenance, status="unavailable", reason=reason)
        n, h = counts.complete, config.horizon
        if n - config.folds * h < config.min_training_points:
            return ForecastSelectionResult(**provenance, status="unavailable", reason="insufficient_history")
        origins = list(range(n - config.folds * h, n, h))
        projection_config = ModelForecastSettings.model_validate(
            config.model_dump(exclude={"objective", "folds", "min_training_points"}))
        scores = []
        for candidate in request.candidates:
            errors, actuals, folds = [], [], []
            failed = None
            for origin in origins:
                budget.check()
                # Construct a genuine prefix, including its original calendar.
                prefix = data.model_dump()
                prefix["values"] = data.values[:origin]
                prefix["period_statuses"] = data.period_statuses[:origin]
                prefix["timestamps"] = data.timestamps[:origin] if data.timestamps is not None else None
                payload, failed = _project(ForecastDataset.model_validate(prefix), candidate, projection_config, budget)
                if failed == "budget_exceeded":
                    raise TimeoutError("candidate exceeded request budget")
                if failed:
                    break
                actual = data.values[origin:origin + h]
                residual = [p - a for p, a in zip(payload["predicted"], actual)]
                folds.append(ForecastFoldScore(training_window=payload["model"].fit_window,
                    holdout_window=(origin, origin + h - 1), **_metrics(residual, actual)))
                errors.extend(residual)
                actuals.extend(actual)
            if failed:
                scores.append(ForecastCandidateScore(candidate=candidate, status="unavailable", reason=failed, folds=folds))
                continue
            metrics = _metrics(errors, actuals)
            loss = (math.fsum(f.total_absolute_error for f in folds) / len(folds)
                    if config.objective == "total_absolute_error" else metrics[config.objective])
            scores.append(ForecastCandidateScore(candidate=candidate, status="completed", loss=loss,
                **{k: metrics[k] for k in ("mae", "rmse", "wape", "bias")}, folds=folds,
                by_lead_mae=[math.fsum(abs(errors[i]) for i in range(lead, len(errors), h)) / len(folds)
                             for lead in range(h)]))
        viable = [score for score in scores if score.status == "completed"]
        budget.check()
        if not viable:
            return ForecastSelectionResult(**provenance, status="unavailable", reason="no_viable_candidate", scores=scores)
        # Tolerance keeps numerical noise in otherwise tied simple fits from
        # defeating deterministic caller order; it is not a significance test.
        best = viable[0]
        for score in viable[1:]:
            if score.loss < best.loss - 1e-12 * max(1., best.loss):
                best = score
        model_request = ModelForecastRequest(dataset=data, candidate=best.candidate, config=projection_config)
        forecast = _forecast_result(model_request, budget)
        if forecast.status != "completed":
            return ForecastSelectionResult(**provenance, status="unavailable", reason=forecast.reason, scores=scores)
        budget.check()
        return ForecastSelectionResult(**provenance, status="completed", scores=scores,
            selected_candidate=best.candidate, forecast=forecast, limitations=list(SELECTION_LIMITATIONS))
    except TimeoutError:
        reason = "budget_exceeded"
    except (OverflowError, ArithmeticError, ValidationError):
        reason = "nonfinite_result"
    except RuntimeError:
        reason = "analysis_incomplete"
    except (ValueError, TypeError, KeyError, IndexError):
        reason = "analysis_failed"
    return ForecastSelectionResult(**provenance, status="unavailable", reason=reason)
