"""Fixed-fit scenarios and separately frozen, causal historical expectations."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ._version import __version__
from .baseline import robust_expected_value
from .budget import RuntimeBudget
from .contracts import Dataset, Request, Settings
from .forecast_contracts import (
    ForecastCounts, ForecastDataset, ForecastModel, ForecastRequest,
    ForecastResult, ForecastSettings, advance_bucket,
)
from .forecast_evidence import historical_anomalies
from .recipes import analyze_dataset
from .seasonality import infer_season_length
from .trend import fit_trend


LIMITATIONS = [
    "Forecasts are fixed-fit scenarios, without calibrated uncertainty intervals or accuracy guarantees.",
    "Trend and seasonal_component are current-model decompositions, including over history; they are not causal historical expectations.",
    "Expected uses a separately frozen historical prefix model and earlier references only; eligible means calibrated residual evidence, not healthy or accurate.",
    "Auto seasonality represents one positional cycle, not multiple calendar effects; annual daily cycles across leap years need an explicit calendar model.",
    "Robust screening can mistake a sustained regime change for contamination; compare include and robust policies and chronological hold-outs.",
    "Runtime limits are cooperative checks, not a hard process deadline; callers must enforce transport deadlines.",
]


def _season(values, config):
    if config.seasonality != "auto":
        period = config.seasonality.period
        return period, {"status": "explicit", "selected_lag": period, "selection_window": None}
    # The existing inference primitive reserves a tail. Zero calibration here
    # reserves one point; every candidate and confirmation remains inside this
    # explicitly bounded selection. Historical callers freeze its whole prefix.
    selection = values[:config.max_inference_points]
    period, _, diagnostics = infer_season_length(selection, 8, 0, 1e-8)
    diagnostics["discovery_window"] = [0, len(selection) - 2] if len(selection) >= 7 else None
    return period, diagnostics


def _historical(values, config, budget):
    n = len(values)
    expected, eligible, maturity = [None] * n, [False] * n, ["unavailable"] * n
    selection_size = min(config.max_training_points, config.max_inference_points)
    selection_window, inference = None, None
    if config.seasonality == "auto":
        training = selection_size
        if n < training:
            return expected, eligible, maturity, None, None, None, {"status": "not_assessed", "reason": "frozen selection prefix incomplete"}, {}, None
        period, inference = _season(values[:selection_size], config)
        selection_window = (0, selection_size - 1)
    else:
        period = config.seasonality.period
        training = max(28, period)
        inference = {"status": "explicit", "selected_lag": period, "selection_window": None}
    if n <= training:
        return expected, eligible, maturity, selection_window, (0, training - 1) if n == training else None, inference, {"status": "not_assessed", "reason": "no post-training observations"}, {}, None
    budget.check()
    request = Request(datasets=[Dataset(values=values)], config=Settings(
        season_length=period, training_size=training, calibration_size=14,
        trend=config.trend, outlier_handling=config.outlier_handling,
        **(config.historical_anomalies.model_dump(exclude={"schema_version"}) if config.historical_anomalies else {}),
        max_points=config.max_points, max_runtime_seconds=max(1e-9, budget.remaining)))
    result = analyze_dataset(request.datasets[0], request.config, request.context, budget)
    method = result.methods[0]
    if method.status not in ("completed", "insufficient_history"):
        # analyze catches its own timeout; restore the stable budget reason.
        budget.check()
        raise RuntimeError("historical analysis incomplete")
    for item in method.evidence:
        index = item["index"]
        # Early reference evidence may use a lag learned later in the prefix.
        # It is deliberately unavailable, rather than described as causal.
        if index < training:
            continue
        value = item["expected"]
        expected[index] = max(config.lower_bound, value) if config.lower_bound is not None else value
        maturity[index] = item["signal_maturity"]
        eligible[index] = maturity[index] == "calibrated"
    return (expected, eligible, maturity, selection_window, (0, training - 1),
            inference, method.diagnostics.get("detection_readiness", {"status": "not_assessed"}),
            method.diagnostics.get("outlier_handling", {}), result)


def forecast_series(
    dataset: ForecastDataset | ForecastRequest | dict | list[float | None] | str,
    settings: ForecastSettings | dict | None = None,
) -> ForecastResult:
    """Forecast a dataset/values list, or a forecast-v1 request/dict/JSON string.

    Invalid requests return unavailable/invalid_input. Direct Pydantic model
    construction raises ValidationError, as do the repository's other models.
    Separate settings are accepted only with datasets and bare values.
    """
    budget_start = RuntimeBudget(3600)
    if isinstance(dataset, str):
        try:
            dataset = json.loads(dataset)
        except (ValueError, TypeError):
            return ForecastResult(engine_version=__version__, status="unavailable", reason="invalid_input")
    canonical = isinstance(dataset, ForecastRequest) or isinstance(dataset, dict) and (
        "schema_version" in dataset or "task" in dataset or "dataset" in dataset)
    if isinstance(dataset, dict) and canonical and (
        dataset.get("schema_version", "forecast-v1") != "forecast-v1"
        or dataset.get("task", "forecast") != "forecast"
    ):
        return ForecastResult(engine_version=__version__, status="unavailable", reason="unsupported_contract")
    try:
        if canonical:
            if settings is not None:
                raise ValueError("canonical settings belong in config")
            raw = dataset.model_dump(mode="json") if isinstance(dataset, ForecastRequest) else dataset
        else:
            if isinstance(dataset, list):
                dataset = {"values": dataset}
            if isinstance(dataset, ForecastDataset):
                dataset = dataset.model_dump(mode="json")
            if isinstance(settings, ForecastSettings):
                settings = settings.model_dump(mode="json")
            raw = {"dataset": dataset, "config": {} if settings is None else settings}
        request = ForecastRequest.model_validate(raw)
    except (ValidationError, ValueError, TypeError, OverflowError):
        return ForecastResult(engine_version=__version__, status="unavailable", reason="invalid_input")
    config, data = request.config, request.dataset
    budget = budget_start
    budget.seconds = config.max_runtime_seconds
    fingerprint = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    counts = ForecastCounts(**{status: data.period_statuses.count(status)
                              for status in ("complete", "partial", "missing")})
    provenance = dict(engine_version=__version__, request_fingerprint=fingerprint,
                      resolved_config=config, counts=counts)

    def unavailable(reason):
        return ForecastResult(**provenance, status="unavailable", reason=reason)

    # Missing, including at the tail, is not a known unfinished bucket. Partial
    # buckets are supported only as a contiguous tail, whether numeric or null.
    if counts.missing:
        return unavailable("missing_history")
    observed = counts.complete
    if any(status != "complete" for status in data.period_statuses[:observed]):
        return unavailable("missing_history")
    if observed < 8:
        return unavailable("insufficient_history")
    values = data.values[:observed]
    start = max(0, observed - config.max_training_points)
    fitted = values[start:]
    try:
        budget.check()
        period, inference = _season(fitted, config)
        # All inference coordinates, including confirmations, are original.
        for key in ("selection_window", "discovery_window"):
            if inference.get(key) is not None:
                inference[key] = [start + i for i in inference[key]]
        if len(fitted) < period:
            return unavailable("insufficient_history")
        trend, diagnostics = fit_trend(fitted, period, config.trend, 1e-8,
                                       budget.check, config.outlier_handling)
        m, anchor = len(fitted), len(fitted) - 1
        # Screening changes the trend fit internally. Reference values stay
        # measured values: robust references trim the outer matching values;
        # include references take the last matching observation. No historical
        # replacements are fed into the forward fit.
        cycle = []
        for phase in range(period):
            budget.check()
            target = m + phase
            cycle.append(robust_expected_value(fitted, target, period, 0, trend, 4)
                         if config.outlier_handling == "robust" else
                         fitted[target - period] + trend.change(target - period, target))
        level = math.fsum(cycle[p] - trend.change(anchor, m + p) for p in range(period)) / period
        offsets = [cycle[p] - level - trend.change(anchor, m + p) for p in range(period)]
        n, h = len(data.values), config.horizon
        components, seasonal, predicted = [], [], []
        for index in range(n + h):
            budget.check()
            factor = 1 + config.trend_adjustment_pct / 100 if index >= n else 1
            component = level + factor * trend.change(anchor, index - start)
            offset = offsets[(index - start - m) % period]
            # Components stay unbounded for an exact additive decomposition.
            # The lower bound applies to predictions and historical expected.
            components.append(component)
            seasonal.append(offset)
            if index >= n:
                value = component + offset
                predicted.append(max(config.lower_bound, value) if config.lower_bound is not None else value)
        expected, eligible, maturity, selection, training, hist_inference, readiness, history_policy, analysis = _historical(values, config, budget)
        evidence = (historical_anomalies(data, config, selection, training, hist_inference, analysis, budget)
                    if config.historical_anomalies is not None else None)
        tail = n - observed
        expected.extend([None] * tail)
        eligible.extend([False] * tail)
        maturity.extend(["unavailable"] * tail)
        numeric = [*components, *seasonal, *predicted, *[v for v in expected if v is not None]]
        if not all(math.isfinite(value) for value in numeric):
            return unavailable("nonfinite_result")
        timestamps = None
        if data.timestamps:
            at = datetime.fromisoformat(data.timestamps[-1].replace("Z", "+00:00")).astimezone(ZoneInfo(data.timezone))
            timestamps = []
            for _ in range(h):
                budget.check()
                at = advance_bucket(at, data.interval)
                timestamps.append(at.isoformat())
        effective = diagnostics.get("fit_window")
        excluded = [start + i for i in diagnostics.get("excluded_positions", [])]
        historical_excluded = sorted(set(
            history_policy.get("training_excluded_positions", [])
            + history_policy.get("calibration_excluded_positions", [])
            + history_policy.get("evaluation_reference_replacements", [])))
        budget.check()
        return ForecastResult(**provenance, status="completed", forecast_applicability="scenario_available",
            expected=expected, eligible=eligible, predicted=predicted, trend=components,
            seasonal_component=seasonal, outlier_indices=sorted(set(excluded + historical_excluded)),
            historical_evidence_maturity=maturity, future_origin_index=n, predicted_timestamps=timestamps,
            historical_anomalies=evidence,
            model=ForecastModel(engine_version=__version__, trend_kind=trend.kind,
                trend_parameters={"coefficient": trend.coefficient, "rate": trend.rate,
                                  "origin": start + trend.origin, "anchor": start + anchor, "level": level},
                season_length=period, season_inference=inference, fit_window=(start, observed - 1),
                effective_trend_window=tuple(start + i for i in effective) if effective else None,
                historical_selection_window=selection, historical_training_window=training,
                historical_inference=hist_inference, historical_readiness=readiness,
                outlier_policy={"handling": config.outlier_handling,
                    "fit_objective": diagnostics.get("fit_objective"),
                    "screened_original_indices": excluded,
                    "historical_reference_adjustments": history_policy,
                    "downweighted_count": diagnostics.get("downweighted_count", 0),
                    "reference_policy": "trim_outer_two_of_four_recency_weighted" if config.outlier_handling == "robust" else "previous_matching_observation",
                    "actuals_modified": False, "historical_replacements_used_for_forecast": False}),
            limitations=list(LIMITATIONS))
    except TimeoutError:
        return unavailable("budget_exceeded")
    except (OverflowError, ArithmeticError):
        return unavailable("nonfinite_result")
    except RuntimeError:
        return unavailable("analysis_incomplete")
    except (ValueError, TypeError, KeyError, IndexError):
        return unavailable("analysis_failed")
