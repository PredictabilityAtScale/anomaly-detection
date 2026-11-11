"""Public forecast migration, causal calibration and bounded level selection."""
import json
import random
import statistics
import time
from pathlib import Path

import jsonschema
import pytest

from anomalyzer import ForecastResult, analyze, forecast_series
from anomalyzer.level import recent_level, select_level


def noisy(n=112):
    rng = random.Random(42)
    return [100 + rng.uniform(-10, 10) for _ in range(n)]


def run(values, **settings):
    result = forecast_series(values, dict(baseline="recent-level-v1", trend="none",
        historical_anomalies={}, **settings))
    assert result.status == "completed", result.model_dump()
    return result


@pytest.mark.parametrize("handling", ["include", "robust"])
def test_frozen_selection_causal_points_and_calibration(handling):
    values = noisy()
    values[80] = 250
    full = run(values, outlier_handling=handling)
    selection = full.model.historical_level_baseline
    assert selection["kind"] == "simple_exponential_smoothing"
    assert selection["selection_window"] == [0, 55]
    assert full.historical_anomalies.resolved_settings.level_baseline == selection
    assert full.historical_anomalies.resolved_settings.forecast_baseline == "recent-level-v1"
    for end in (57, 60, 69, 70, 71, 82, 100):
        prefix = run(values[:end], outlier_handling=handling)
        assert prefix.expected == full.expected[:end]
        assert prefix.historical_anomalies.points == full.historical_anomalies.points[:end]
        assert prefix.model.historical_level_baseline == selection
        assert prefix.historical_anomalies.patterns == [p for p in full.historical_anomalies.patterns if p.detection_index < end]
        changed = run(values[:end] + [300.] * (len(values) - end), outlier_handling=handling)
        assert changed.expected[:end + 1] == full.expected[:end + 1]
        assert changed.historical_anomalies.points[:end] == full.historical_anomalies.points[:end]
        assert changed.historical_anomalies.origin_fingerprint == full.historical_anomalies.origin_fingerprint
    assert full.historical_anomalies.calibration.available_from_index == 70
    assert all(not p.triggers for p in full.historical_anomalies.points[:70])
    # Include calibration is independently replayable against the frozen SES.
    if handling == "include":
        residuals = [values[i] - recent_level(values, i, selection["alpha"], handling) for i in range(56, 70)]
        calibration = full.historical_anomalies.calibration
        assert calibration.center == pytest.approx(statistics.mean(residuals))
        assert calibration.raw_scale == pytest.approx(statistics.stdev(residuals))
        p = full.historical_anomalies.points[75]
        assert p.expected == pytest.approx(recent_level(values, 75, selection["alpha"], handling))
        assert p.standardized_score == pytest.approx((p.residual - calibration.center) / calibration.scale)


def test_legacy_and_standalone_recipes_remain_unchanged():
    values = noisy()
    legacy = forecast_series(values, {"trend": "none", "outlier_handling": "include"})
    explicit = forecast_series(values, {"baseline": "legacy", "trend": "none", "outlier_handling": "include"})
    assert legacy == explicit
    assert legacy.predicted == [values[-1]] * 30
    assert legacy.expected[56:] == values[55:-1]
    analyzer = analyze(values, {"season_length": 1, "trend": "none", "outlier_handling": "include"})
    assert all(p["expected"] == values[p["index"] - 1] for p in analyzer.methods[0].evidence)
    assert "level_baseline" not in analyzer.methods[0].diagnostics


@pytest.mark.parametrize("handling", ["include", "robust"])
@pytest.mark.parametrize("value", [0., 20., -5.])
def test_constant_ties_short_history_and_zero(handling, value):
    for n in (8, 28, 56, 90):
        r = run([value] * n, outlier_handling=handling, seasonality={"period": 1})
        assert r.predicted == [value] * 30
        assert r.model.level_baseline["kind"] == "persistence"
        assert r.model.level_baseline["alpha"] is None
        if n <= 56:
            assert not any(r.eligible)
            assert all(v is None for v in r.expected)
        else:
            assert r.model.historical_training_window == (0, 55)
    short = run([value] * 28)
    assert short.model.level_baseline["status"] == "insufficient_history"


def test_selection_is_chronological_bounded_and_reproducible():
    values = noisy(6000)
    selection = select_level(values, "include", lambda: None)
    assert selection == select_level(values, "include", lambda: None)
    assert selection["selection_window"] == [5944, 5999]
    assert len(selection["folds"]) <= 6
    assert len(selection["scores"]) == 5
    for fold in selection["folds"]:
        left, right = fold["training_window"]
        at, stop = fold["holdout_window"]
        assert right == at - 1 and stop == at + 6
        history = values[left:at]
        for score in selection["scores"]:
            estimate = recent_level(history, len(history), score["alpha"], "include")
            assert score["fold_mae"][selection["folds"].index(fold)] == pytest.approx(
                statistics.mean(abs(v - estimate) for v in values[at:stop + 1]))


@pytest.mark.parametrize("handling", ["include", "robust"])
def test_horizon_prefix_partial_missing_and_serialization(handling):
    values = noisy()
    a = run(values, horizon=1, outlier_handling=handling)
    b = run(values, horizon=90, outlier_handling=handling)
    assert a.predicted == b.predicted[:1]
    assert a.expected == b.expected
    assert a.model == b.model
    assert a.historical_anomalies == b.historical_anomalies
    tail = forecast_series({"values": values + [999., None],
        "period_statuses": ["complete"] * len(values) + ["partial"] * 2},
        {"baseline": "recent-level-v1", "trend": "none", "historical_anomalies": {}, "outlier_handling": handling})
    assert tail.status == "completed"
    assert tail.predicted == b.predicted[:30]
    assert tail.expected == b.expected + [None, None]
    assert tail.historical_anomalies.points[-1].unavailable_reason == "partial"
    assert tail.future_origin_index == len(values) + 2
    missing = forecast_series({"values": values + [None], "period_statuses": ["complete"] * len(values) + ["missing"]}, {"baseline": "recent-level-v1"})
    assert missing.reason == "missing_history" and missing.predicted is None
    assert ForecastResult.model_validate_json(b.model_dump_json()) == b
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/forecast-result.schema.json").read_text())
    jsonschema.validate(b.model_dump(mode="json"), schema)


@pytest.mark.parametrize("settings", [
    {"seasonality": {"period": 7}, "trend": "none"},
    {"seasonality": {"period": 1}, "trend": "linear"},
    {"seasonality": {"period": 1}, "trend": "exponential"},
])
def test_explicit_season_and_trend_forward_models_preserved(settings):
    values = [100 + .5 * i + [0, 3, -1, 4, 1, -2, -3][i % 7] for i in range(112)]
    legacy = forecast_series(values, settings)
    current = forecast_series(values, {**settings, "baseline": "recent-level-v1"})
    assert current.predicted == legacy.predicted
    assert current.expected == legacy.expected
    assert current.model.level_baseline["status"] == "not_applicable"


def test_spike_protection_is_smoothing_not_an_outlier_label_and_shift_can_lag():
    history = noisy(56)
    selection = select_level(history, "include", lambda: None)
    assert selection["kind"] == "simple_exponential_smoothing"
    alpha = selection["alpha"]
    end_spike = history + [300.]
    smoothed = recent_level(end_spike, len(end_spike), alpha, "include")
    assert abs(smoothed - 100) < abs(end_spike[-1] - 100)
    changed = history + [200.] * 3
    # A real step penalizes smoothing relative to immediately following it.
    assert abs(recent_level(changed, len(changed), alpha, "include") - 200) > 0
    assert recent_level(changed, len(changed), None, "include") == 200
    actual = run(history + [300.] + noisy(55), outlier_handling="include")
    assert actual.outlier_indices == []
    assert actual.historical_anomalies.reference_adjustments == []
    shifted = select_level([100.] * 35 + [200.] * 21, "include", lambda: None)
    assert shifted["kind"] == "persistence"


def test_runtime_size_budgets_and_failure_atomicity():
    start = time.perf_counter()
    r = run(noisy(6000), max_runtime_seconds=10, outlier_handling="include")
    assert time.perf_counter() - start < 10
    assert len(r.model_dump_json()) < 6_000_000
    assert len(json.dumps(r.model.level_baseline)) < 6000
    failure = forecast_series(noisy(), {"baseline": "recent-level-v1", "max_runtime_seconds": 1e-9})
    assert failure.reason == "budget_exceeded" and failure.model is None and failure.expected is None
    assert forecast_series(noisy(6001), {"baseline": "recent-level-v1"}).reason == "invalid_input"
    assert forecast_series(noisy(), {"baseline": "ses"}).reason == "invalid_input"


def test_bridge_opt_in_discloses_selected_baselines_and_rejects_unknown_versions():
    import importlib.util
    from anomalyzer import __version__
    path = Path(__file__).resolve().parents[1] / "examples/library/usagetap_forecast.py"
    spec = importlib.util.spec_from_file_location("recent_level_bridge", path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    assert bridge.VERSION == __version__ == "0.9.1"
    event = dict(contract="usage-forecast-v1", values=noisy(), interval="day", horizon=7,
                 excludeExtremeOutliers=False, historicalAnomalies={"schema_version": "historical-anomalies-v1"})
    legacy = bridge.forecast_usage(event)
    selected = bridge.forecast_usage({**event, "levelBaseline": "recent-level-v1"})
    assert selected["status"] == "completed"
    assert "levelBaseline" not in legacy["model"]
    assert selected["model"]["levelBaseline"]["kind"] == "simple_exponential_smoothing"
    assert selected["model"]["historicalLevelBaseline"] == selected["historicalAnomalies"]["resolved_settings"]["level_baseline"]
    assert bridge.forecast_usage({**event, "levelBaseline": "future-v9"})["reason"] == "unsupported_contract"


@pytest.mark.parametrize("handling", ["include", "robust"])
def test_bounded_reference_optimization_matches_existing_policy_exactly(handling):
    from anomalyzer.baseline import robust_expected_value
    from anomalyzer.level import _reference
    from anomalyzer.trend import Trend
    values = noisy(100) + [0., 0., 3., 3., 3., -5., -5.]
    for start in (0, 10, 52):
        for index in range(start + 1, len(values) + 1):
            expected = (values[index - 1] if handling == "include" else
                        robust_expected_value(values, index, 1, start, Trend(), 4))
            assert _reference(values, index, start, handling) == expected
