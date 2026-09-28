"""Conservative diagnostics for interpreting a calibrated anomaly reference."""

import math
import statistics


SCOPE = (
    "Training and calibration diagnostics only; this does not estimate detection "
    "precision, false-alarm rate, or business usefulness."
)
MAX_TRAINING_CHECK = 4096


def _correlation(left, right):
    if len(left) < 6:
        return None
    left_center = statistics.mean(left)
    right_center = statistics.mean(right)
    left_ss = math.fsum((value - left_center) ** 2 for value in left)
    right_ss = math.fsum((value - right_center) ** 2 for value in right)
    if left_ss == 0 or right_ss == 0:
        return None
    return math.fsum((a - left_center) * (b - right_center)
                     for a, b in zip(left, right)) / math.sqrt(left_ss * right_ss)


def _detrend(values):
    center_x = (len(values) - 1) / 2
    center_y = statistics.mean(values)
    denominator = math.fsum((index - center_x) ** 2
                            for index in range(len(values)))
    slope = (math.fsum((index - center_x) * (value - center_y)
                       for index, value in enumerate(values)) / denominator
             if denominator else 0.0)
    return [value - center_y - slope * (index - center_x)
            for index, value in enumerate(values)]


def _seasonal_repeatability(training_values, season_length):
    if season_length == 1:
        return {"status": "not_applicable", "reason": "lag 1 does not assert a repeating season"}
    if len(training_values) < max(4 * season_length, season_length + 12):
        return {"status": "insufficient_cycles",
                "reason": "fewer than four training cycles or twelve lag pairs"}
    residuals = _detrend(training_values)
    left = residuals[:-season_length]
    right = residuals[season_length:]
    split = len(left) // 2
    first = _correlation(left[:split], right[:split])
    second = _correlation(left[split:], right[split:])
    if first is None or second is None:
        status = "not_assessed"
    elif min(first, second) >= 0.5:
        status = "repeated"
    else:
        status = "weak_or_unstable"
    return {"status": status, "first_half_lag_correlation": first,
            "second_half_lag_correlation": second,
            "minimum_correlation": 0.5,
            "method": "lag correlation in each half of linearly detrended training pairs"}


def assess_segment(training_values, calibration, excluded_positions,
                   season_length, trend_selected, scale_floor):
    """Judge the reference using training and calibration, never evaluation data."""
    training_values = training_values[-MAX_TRAINING_CHECK:]
    excluded = set(excluded_positions)
    retained = [item for item in calibration if item["index"] not in excluded]
    repeatability = _seasonal_repeatability(training_values, season_length)
    result = {
        "status": "not_assessed", "reasons": [], "scope": SCOPE,
        "training_pattern": {"samples_checked": len(training_values),
                             "trend_selected": trend_selected,
                             "seasonality": repeatability},
        "calibration": {"samples": len(retained)},
    }
    if len(retained) < 8:
        result["reasons"].append(
            "Fewer than eight retained calibration residuals; reference quality cannot be assessed reliably.")
        return result

    training_level = statistics.median(training_values)
    model_mae = statistics.mean(abs(item["residual"]) for item in retained)
    level_mae = statistics.mean(abs(item["expected"] + item["residual"] - training_level)
                                for item in retained)
    skill = (1 - model_mae / level_mae if level_mae > scale_floor else None)
    retained_by_index = {item["index"]: item["residual"] for item in retained}
    lag_pairs = [(retained_by_index[index - 1], residual)
                 for index, residual in retained_by_index.items()
                 if index - 1 in retained_by_index]
    autocorrelation = (_correlation([a for a, _ in lag_pairs],
                                    [b for _, b in lag_pairs])
                       if lag_pairs else None)
    residuals = [item["residual"] for item in retained]
    half = len(residuals) // 2
    residual_scale = statistics.stdev(residuals)
    center_drift = (abs(statistics.mean(residuals[:half])
                        - statistics.mean(residuals[half:]))
                    / max(residual_scale, scale_floor))
    result["calibration"].update(
        model_mae=model_mae, training_level_mae=level_mae,
        mae_skill_vs_training_level=skill,
        lag_1_residual_correlation=autocorrelation,
        half_center_gap_in_standard_deviations=center_drift,
        comparison="same calibration samples; constant training median as reference")

    if skill is None:
        result["reasons"].append(
            "The training-level comparison has too little variation to measure baseline skill.")
    elif skill < 0.1:
        result["reasons"].append(
            "The modeled reference improves calibration MAE by less than 10% over the training median; point flags may be noisy or hard to interpret.")
    if repeatability["status"] == "weak_or_unstable":
        result["reasons"].append(
            "The declared season did not repeat consistently in both halves of training.")
    elif repeatability["status"] in ("insufficient_cycles", "not_assessed"):
        result["reasons"].append(
            "The declared season could not be checked for stable repetition in training.")
    if autocorrelation is not None and abs(autocorrelation) >= 0.65:
        result["reasons"].append(
            "Calibration residuals have strong lag-1 correlation; rule alert rates may differ from a stable independent-residual reference.")
    if center_drift >= 1.25:
        result["reasons"].append(
            "The calibration residual center moved between halves; the frozen trend or reference may be unstable.")
    if model_mae <= scale_floor:
        result["reasons"].append(
            "Calibration residuals are near the scale floor; small future changes can produce large scores.")
    if not result["reasons"]:
        result["reasons"].append(
            "The modeled reference improved calibration MAE and no checked instability was detected.")
        result["status"] = "supported"
    else:
        result["status"] = "caution"
    return result


def summarize_segments(segments, method_status):
    checks = [segment["detection_readiness"] for segment in segments
              if "detection_readiness" in segment]
    assessed = [item for item in checks if item["status"] != "not_assessed"]
    unassessed = len(segments) - len(assessed)
    if not assessed:
        reasons = list(dict.fromkeys(reason for item in checks
                                     for reason in item["reasons"]))
        if not reasons:
            reasons = [f"No segment reached calibrated evaluation (method status: {method_status})."]
        return {"status": "not_assessed", "reasons": reasons,
            "assessed_segments": 0, "unassessed_segments": unassessed,
            "scope": SCOPE}
    reasons = list(dict.fromkeys(reason for item in assessed
                                 if item["status"] != "supported"
                                 for reason in item["reasons"]))
    reasons.extend(reason for item in checks if item["status"] == "not_assessed"
                   for reason in item["reasons"] if reason not in reasons)
    if unassessed:
        reasons.append(f"{unassessed} segment(s) lacked calibrated evaluation.")
    if method_status != "completed":
        reasons.append(f"Method status is {method_status}.")
    status = "caution" if reasons else "supported"
    if not reasons:
        reasons.append("Checked training and calibration diagnostics support the modeled reference.")
    return {"status": status, "reasons": reasons,
            "assessed_segments": len(assessed),
            "unassessed_segments": unassessed, "scope": SCOPE}
