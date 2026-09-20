"""Conservative positional season-length inference using only a training prefix."""
import math
import statistics

MAX_INFERENCE_VALUES = 4096
MAX_INFERRED_LAG = 512


def _detrend(values: list[float]) -> list[float]:
    """Remove a fitted straight line so trend is not mistaken for seasonality."""
    count = len(values)
    center_x = (count - 1) / 2
    center_y = statistics.mean(values)
    denominator = math.fsum((index - center_x) ** 2 for index in range(count))
    slope = (math.fsum((index - center_x) * (value - center_y)
                       for index, value in enumerate(values)) / denominator
             if denominator else 0.0)
    return [value - (center_y + slope * (index - center_x))
            for index, value in enumerate(values)]


def _candidates(values: list[float], scale_floor: float) -> list[dict]:
    residuals = _detrend(values)
    variance = math.fsum(value * value for value in residuals) / len(residuals)
    if variance <= scale_floor * scale_floor:
        return []
    output = []
    for lag in range(1, min(len(values) // 3, MAX_INFERRED_LAG) + 1):
        left, right = residuals[lag:], residuals[:-lag]
        left_mean, right_mean = statistics.mean(left), statistics.mean(right)
        left_ss = math.fsum((value - left_mean) ** 2 for value in left)
        right_ss = math.fsum((value - right_mean) ** 2 for value in right)
        denominator = math.sqrt(left_ss * right_ss)
        if denominator <= scale_floor * scale_floor:
            continue
        correlation = math.fsum((a - left_mean) * (b - right_mean)
                                for a, b in zip(left, right)) / denominator
        error_ratio = (math.fsum((a - b) ** 2 for a, b in zip(left, right)) /
                       len(left) / variance)
        if math.isfinite(correlation) and math.isfinite(error_ratio):
            output.append({"lag": lag, "correlation": correlation,
                           "error_ratio": error_ratio})
    return sorted(output, key=lambda item: (-item["correlation"],
                                             item["error_ratio"], item["lag"]))


def _choose(values: list[float], scale_floor: float):
    ranked = _candidates(values, scale_floor)
    lag_one = next((item for item in ranked if item["lag"] == 1), None)
    seasonal = [item for item in ranked if item["lag"] >= 2]
    eligible = [item for item in seasonal
                if item["correlation"] >= 0.6 and item["error_ratio"] <= 0.8
                and lag_one is not None
                and item["correlation"] >= lag_one["correlation"] + 0.1
                and item["error_ratio"] <= lag_one["error_ratio"] * 0.8]
    if not eligible:
        return None, seasonal[:5]
    best = eligible[0]
    # Prefer the shortest plausible fundamental lag over a near-equal multiple.
    near_best = [item for item in eligible
                 if item["correlation"] >= best["correlation"] - 0.05
                 and item["error_ratio"] <= best["error_ratio"] + 0.1]
    return min(near_best, key=lambda item: item["lag"]), seasonal[:5]


def infer_season_length(values: list[float], training_size: int,
                        calibration_size: int, scale_floor: float):
    """Return a stable inferred lag, the causal training size, and diagnostics."""
    available = min(len(values) - calibration_size - 1, MAX_INFERENCE_VALUES)
    diagnostics = {
        "status": "not_detected", "selected_lag": 1,
        "selection_window": None, "ranked_candidates": [],
        "criteria": {"minimum_cycles": 3, "minimum_correlation": 0.6,
                     "maximum_error_ratio": 0.8,
                     "minimum_correlation_gain_over_lag_1": 0.1,
                     "minimum_error_reduction_vs_lag_1": 0.2,
                     "maximum_candidate_lag": MAX_INFERRED_LAG,
                     "maximum_selection_values": MAX_INFERENCE_VALUES}}
    if available < 6:
        diagnostics["reason"] = "not enough values for three cycles plus calibration and evaluation"
        return 1, training_size, diagnostics
    initial, initial_ranked = _choose(values[:available], scale_floor)
    diagnostics["ranked_candidates"] = initial_ranked
    if initial is None:
        diagnostics["reason"] = "no candidate met the strength criteria"
        return 1, training_size, diagnostics
    confirmation_size = max(training_size, 3 * initial["lag"])
    if confirmation_size > available:
        diagnostics["reason"] = "candidate lacks a separate calibration and evaluation tail"
        return 1, training_size, diagnostics
    confirmed, confirmed_ranked = _choose(values[:confirmation_size], scale_floor)
    diagnostics["confirmation_candidates"] = confirmed_ranked
    if confirmed is None or confirmed["lag"] != initial["lag"]:
        diagnostics["reason"] = "candidate was not stable in its earliest three-cycle training window"
        return 1, training_size, diagnostics
    diagnostics.update(
        status="detected", selected_lag=initial["lag"],
        selection_window=[0, confirmation_size - 1],
        selected_correlation=confirmed["correlation"],
        selected_error_ratio=confirmed["error_ratio"])
    return initial["lag"], confirmation_size, diagnostics
