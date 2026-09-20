"""One-step seasonal-naive expectation used only for anomaly scoring."""


def expected_value(values: list[float], index: int, season_length: int) -> float:
    """Use the last observed value at this seasonal position, never future data."""
    if season_length < 1 or index < season_length or index > len(values):
        raise ValueError("prediction requires at least one full season of earlier values")
    return values[index - season_length]
