"""Reference-quality checks distinguish noisy baselines from later anomalies."""

import random

from anomalyzer import analyze


def test_repeating_season_and_trend_support_reference():
    rng = random.Random(11)
    seasonal = [0, 10, -5, 8, 2, -12, -8]
    values = [100 + 0.4 * index + seasonal[index % 7] + rng.gauss(0, 0.4)
              for index in range(90)]
    result = analyze(values, {"season_length": 7})
    method = result.methods[0]
    readiness = method.diagnostics["detection_readiness"]
    segment = method.diagnostics["segments"][0]["detection_readiness"]
    assert readiness["status"] == "supported"
    assert segment["training_pattern"]["seasonality"]["status"] == "repeated"
    assert segment["calibration"]["mae_skill_vs_training_level"] > 0.9

    shifted = values.copy()
    shifted[60:] = [value + 3 for value in shifted[60:]]
    later_change = analyze(shifted, {"season_length": 7})
    assert later_change.methods[0].diagnostics["detection_readiness"] == readiness
    assert later_change.methods[0].diagnostics["segments"][0]["detection_readiness"] == segment


def test_unstable_declared_season_warns_without_calling_series_inapplicable():
    rng = random.Random(7)
    values = [100 + rng.gauss(0, 10) for _ in range(90)]
    result = analyze(values, {"season_length": 7})
    method = result.methods[0]
    assert result.status == "completed"
    assert method.diagnostics["detection_readiness"]["status"] == "caution"
    segment = method.diagnostics["segments"][0]["detection_readiness"]
    assert segment["training_pattern"]["trend_selected"] == "none"
    assert segment["training_pattern"]["seasonality"]["status"] == "weak_or_unstable"
    assert any("season did not repeat" in reason for reason in segment["reasons"])


def test_calibration_drift_warns_even_when_training_season_repeats():
    rng = random.Random(11)
    seasonal = [0, 10, -5, 8, 2, -12, -8]
    values = [100 + 0.4 * index + seasonal[index % 7] + rng.gauss(0, 0.4)
              for index in range(90)]
    values[35:42] = [value + 4 for value in values[35:42]]
    result = analyze(values, {"season_length": 7})
    segment = result.methods[0].diagnostics["segments"][0]["detection_readiness"]
    assert segment["status"] == "caution"
    assert segment["training_pattern"]["seasonality"]["status"] == "repeated"
    assert segment["calibration"]["half_center_gap_in_standard_deviations"] >= 1.25
    assert any("calibration residual center moved" in reason
               for reason in segment["reasons"])


def test_readiness_is_not_assessed_without_calibrated_evaluation():
    result = analyze([100] * 10, {"season_length": 1})
    readiness = result.methods[0].diagnostics["detection_readiness"]
    assert readiness["status"] == "not_assessed"
    assert readiness["assessed_segments"] == 0


def test_short_calibration_is_not_assessed_even_when_analysis_completes():
    result = analyze([100] * 20, {"season_length": 1,
                                  "training_size": 8, "calibration_size": 3})
    assert result.status == "completed"
    readiness = result.methods[0].diagnostics["detection_readiness"]
    assert readiness["status"] == "not_assessed"
    assert readiness["assessed_segments"] == 0
    assert any("Fewer than eight" in reason for reason in readiness["reasons"])
