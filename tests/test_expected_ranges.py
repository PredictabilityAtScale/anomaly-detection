from anomalyzer.expected_ranges import EmpiricalRange


def test_range_uses_unscreened_errors_and_rejects_unsupported_quantile():
    state = EmpiricalRange(0.95, 1, 1)
    for i in range(18):
        state.admit(0 if i == 0 else i, 1, 1, i, str(i), 3)
    assert state.bounds(10)["status"] == "insufficient_history"
    state.admit(1000, 1, 1, 18, "18", 3)
    assert state.frozen["rank"] == 19
    assert state.bounds(10)["upper"] == 1010
    assert state.frozen["effective_from_index"] == 19
    state.admit(2000, 1, 1, 19, "19", 3)
    assert state.frozen["sample_count"] == 19
