"""Causal seasonal expectations used only for anomaly scoring."""

import statistics

from .trend import Trend


def expected_value(values: list[float], index: int, season_length: int) -> float:
    """Use the last observed value at this seasonal position, never future data."""
    if season_length < 1 or index < season_length or index > len(values):
        raise ValueError("prediction requires at least one full season of earlier values")
    return values[index - season_length]


def robust_expected_value(values: list[float], index: int, season_length: int,
                          segment_start: int, trend: Trend,
                          reference_seasons: int) -> float:
    """Trim matching seasonal references before a modest recency-weighted mean.

    Each candidate is brought to the prediction date using the frozen trend.
    Before four complete seasonal cycles, use the previous matching reference
    to preserve short-history behavior.
    """
    if reference_seasons < 1 or segment_start < 0 or index - segment_start < season_length:
        raise ValueError("prediction requires at least one full season in the segment")
    if reference_seasons == 1 or index - segment_start < 4 * season_length:
        source = index - season_length
        return values[source] + trend.change(source - segment_start,
                                              index - segment_start)
    candidates = []
    for age in range(min(reference_seasons, (index - segment_start) // season_length), 0, -1):
        source = index - age * season_length
        value = values[source] + trend.change(source - segment_start,
                                               index - segment_start)
        # The newest sample has only 1.5 times the oldest sample's weight.
        weight = 1.0 if reference_seasons == 1 else 1.0 + 0.5 * (
            reference_seasons - age) / (reference_seasons - 1)
        candidates.append((value, weight))
    ordered = sorted(candidates)
    retained = ordered[1:-1]
    return sum(value * weight for value, weight in retained) / sum(
        weight for _, weight in retained)


def adaptive_expected_value(values: list[float], index: int, season_length: int,
                            segment_start: int, window: int,
                            slope_lookback: int, season_weight: float,
                            min_seasonal_matches: int) -> float:
    """Forecast one step from a bounded, causal, robust rolling reference.

    The trend is the median of pairwise slopes from recent observations whose
    separation is bounded by ``slope_lookback``. Each recent observation is
    projected to ``index`` and their median supplies the general reference.
    When enough matching seasonal phases exist, their projected median is
    blended with the general reference. No sample at or after ``index`` is read.
    """
    if (segment_start < 0 or index > len(values) or index <= segment_start
            or season_length < 1 or window < 3 or slope_lookback < 1
            or not 0 <= season_weight <= 1 or min_seasonal_matches < 1):
        raise ValueError("invalid adaptive prediction request")
    history_start = max(segment_start, index - window)
    positions = list(range(history_start, index))
    slopes = [
        (values[right] - values[left]) / (right - left)
        for right in positions
        for left in range(max(history_start, right - slope_lookback), right)
    ]
    slope = statistics.median(slopes) if slopes else 0.0
    projected = [values[source] + slope * (index - source)
                 for source in positions]
    general = statistics.median(projected)
    seasonal = [
        values[source] + slope * (index - source)
        for source in positions
        if (index - source) % season_length == 0
    ]
    if len(seasonal) < min_seasonal_matches:
        return general
    seasonal_reference = statistics.median(seasonal)
    return (season_weight * seasonal_reference
            + (1 - season_weight) * general)
