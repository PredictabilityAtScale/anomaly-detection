"""Causal seasonal expectations used only for anomaly scoring."""

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
