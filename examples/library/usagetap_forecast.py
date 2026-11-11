"""Proposed usage-forecast-v1 bridge for the separately released 0.9.1 wheel.

Copy only after releasing and reviewing the pinned upstream artifact. No AWS
client, credentials, customer identity or Guard profile is needed here.
"""
import math

from anomalyzer import __version__, forecast_series

VERSION = "0.9.1"
CONTRACT = "usage-forecast-v1"
WINDOWS = {"hour": 1344, "day": 56, "week": 52, "month": 36}
MAX_HORIZONS = {"hour": 168, "day": 90, "week": 26, "month": 24}


def forecast_usage(event, context=None):
    def unavailable(reason):
        return {"contract": CONTRACT, "status": "unavailable", "reason": reason}

    if not isinstance(event, dict):
        return unavailable("invalid_input")
    if __version__ != VERSION or event.get("contract") != CONTRACT:
        return unavailable("unsupported_contract")
    baseline = event.get("levelBaseline", "legacy")
    if baseline not in ("legacy", "recent-level-v1"):
        return unavailable("unsupported_contract")
    evidence = event.get("historicalAnomalies")
    if "historicalAnomalies" in event:
        if not isinstance(evidence, dict):
            return unavailable("invalid_input")
        if evidence.get("schema_version") != "historical-anomalies-v1":
            return unavailable("unsupported_contract")
    values, interval, horizon = event.get("values"), event.get("interval"), event.get("horizon")
    adjustment = event.get("trendAdjustmentPct", 0)
    try:
        valid = (isinstance(interval, str) and interval in WINDOWS
            and type(horizon) is int and 1 <= horizon <= MAX_HORIZONS[interval]
            and isinstance(values, list) and 1 <= len(values) <= 6000
            and all(v is None or type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values)
            and type(adjustment) in (int, float) and math.isfinite(adjustment) and -50 <= adjustment <= 200
            and type(event.get("excludeExtremeOutliers")) is bool)
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        return unavailable("invalid_input")
    end = len(values)
    while end and values[end - 1] is None:
        end -= 1
    if end < 8:
        return unavailable("insufficient_history")
    if any(v is None for v in values[:end]):
        return unavailable("missing_history")
    # Legacy null tails are assumed partial ONLY to retain the existing bridge
    # semantics. The public API never makes this inference for its own callers.
    statuses = ["complete"] * end + ["partial"] * (len(values) - end)
    seconds = 2.5
    if context is not None:
        seconds = min(seconds, context.get_remaining_time_in_millis() / 1000 - 1)
    if seconds <= 0:
        return unavailable("budget_exceeded")
    result = forecast_series({"values": values, "period_statuses": statuses, "interval": interval}, {
        "horizon": horizon, "trend": "auto", "seasonality": "auto", "baseline": baseline,
        "outlier_handling": "robust" if event["excludeExtremeOutliers"] else "include",
        "trend_adjustment_pct": adjustment, "lower_bound": 0,
        "max_training_points": WINDOWS[interval], "max_inference_points": 768,
        "max_points": 6000, "max_runtime_seconds": seconds,
        **({"historical_anomalies": evidence} if evidence is not None else {}),
    })
    if result.status != "completed":
        return unavailable(result.reason)
    model = result.model
    response = {"contract": CONTRACT, "status": "completed", "expected": result.expected,
        "eligible": result.eligible, "predicted": result.predicted,
        # The legacy TS validator requires nonnegative trend; the public
        # additive trend component is signed even for bounded predictions.
        "trend": [max(0.0, value) for value in result.trend],
        "outlierIndices": result.outlier_indices,
        "model": {"method": "anomalyzer", "label": "Anomalyzer", "engineVersion": __version__,
            "trendKind": model.trend_kind, "seasonLength": model.season_length,
            "seasonalityStatus": model.season_inference["status"],
            "notes": [*result.limitations,
                f"Forecast request fingerprint: {result.request_fingerprint}",
                f"Forecast fit window (original positions): {model.fit_window}",
                f"Historical training window: {model.historical_training_window}",
                "Legacy null tail assumed partial; transport cannot distinguish missing from partial."]}}
    if baseline != "legacy":
        response["model"]["levelBaseline"] = model.level_baseline
        response["model"]["historicalLevelBaseline"] = model.historical_level_baseline
    if evidence is not None:
        response["historicalAnomalies"] = result.historical_anomalies.model_dump(mode="json")
    return response
