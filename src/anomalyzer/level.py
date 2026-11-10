"""Versioned, bounded recent-level selection; no anomaly classification here."""
import math

ALPHAS = (0.1, 0.25, 0.5, 0.75)
WINDOW = 56
HORIZON = 7
MIN_FOLDS = 3


def _reference(values, target, start, handling):
    """The existing lag-one reference policy, specialized to a zero trend.

    Avoid constructing trend objects and general seasonal loops for every SES
    update. Sorting (value, weight) pairs preserves the original tie behavior.
    """
    if handling == "include" or target - start < 4:
        return values[target - 1]
    ordered = sorted((values[target - age], 1.0 + 0.5 * (4 - age) / 3)
                     for age in (4, 3, 2, 1))
    left, right = ordered[1:3]
    return (left[0] * left[1] + right[0] * right[1]) / (left[1] + right[1])


def recent_level(values, index, alpha, handling, segment_start=0):
    """Read only the preceding <=56 observations; reset at the window's first.

    Include feeds measured observations to SES. Robust feeds the existing
    trimmed four-reference policy to SES. Neither operation labels outliers.
    """
    start = max(segment_start, index - WINDOW)
    if not start < index <= len(values):
        raise ValueError("recent level requires prior observations")
    if alpha is None:
        return _reference(values, index, start, handling)
    level = values[start]
    for target in range(start + 1, index + 1):
        reference = _reference(values, target, start, handling)
        level = alpha * reference + (1 - alpha) * level
    return level


def select_level(values, handling, check, *, start=0, applicable=True):
    """Select from prior data only, independently of requested output horizon.

    At most six disjoint seven-target folds, four fixed alphas, and 56 fit
    observations per fold. Five percent aggregate MAE improvement, >=2/3 fold
    wins, and no >5% one-step MAE regression are required. Persistence wins
    ties, including all-zero errors. Candidate ties prefer the smaller alpha.
    """
    selection = dict(version="recent-level-v1", kind="persistence", alpha=None,
        status="insufficient_history", reason="At least three seven-step folds after eight observations are required.",
        window=WINDOW, validation_horizon=HORIZON, minimum_folds=MIN_FOLDS,
        minimum_relative_improvement=0.05, minimum_fold_win_fraction=2 / 3,
        maximum_one_step_regression=0.05, selection_window=None, folds=[], scores=[])
    if not applicable:
        selection.update(status="not_applicable", kind="seasonal_reference",
            reason="Recent-level selection applies only when trend is none and season_length is 1.")
        return selection
    data = values[-WINDOW:]
    offset = start + len(values) - len(data)
    selection["selection_window"] = [offset, offset + len(data) - 1]
    origins = list(range(len(data) - HORIZON, 7, -HORIZON))[:6][::-1]
    selection["folds"] = [dict(training_window=[offset, offset + origin - 1],
        holdout_window=[offset + origin, offset + origin + HORIZON - 1]) for origin in origins]
    if len(origins) < MIN_FOLDS:
        return selection
    for alpha in (None, *ALPHAS):
        losses, first = [], []
        for origin in origins:
            check()
            estimate = recent_level(data, origin, alpha, handling)
            errors = [abs(actual - estimate) for actual in data[origin:origin + HORIZON]]
            losses.append(math.fsum(errors) / HORIZON)
            first.append(errors[0])
        selection["scores"].append(dict(alpha=alpha, mae=math.fsum(losses) / len(losses),
            one_step_mae=math.fsum(first) / len(first), fold_mae=losses))
    base = selection["scores"][0]
    tolerance = 1e-12 * max(1.0, base["mae"])
    supported = [score for score in selection["scores"][1:]
        if score["mae"] < base["mae"] * 0.95 - tolerance
        and score["one_step_mae"] <= base["one_step_mae"] * 1.05 + tolerance
        and sum(a < b - tolerance for a, b in zip(score["fold_mae"], base["fold_mae"])) * 3 >= 2 * len(origins)]
    selection.update(status="retained", reason="Smoothing lacks supported improvement; persistence retained.")
    if supported:
        best = min(supported, key=lambda score: (score["mae"], score["alpha"]))
        selection.update(status="selected", kind="simple_exponential_smoothing", alpha=best["alpha"],
            reason="No stable cycle or trend selected; forecast uses a smoothed recent level.")
    return selection
