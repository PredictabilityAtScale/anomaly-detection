"""Forward-model parity, honest holdouts, validation and compatibility."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import (
    ForecastCandidate, ForecastDataset, ForecastSelectionRequest, ForecastSelectionResult,
    ForecastSelectionSettings, ModelForecastRequest, ModelForecastResult, ModelForecastSettings,
    default_forecast_candidates, forecast_series, forecast_with_model, select_forecast,
)

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "tests/fixtures/usagetap_current.json").read_text())


def candidate(method, **settings):
    return ForecastCandidate(id=method, method=method, **settings)


def project(values, method="local_trend", **settings):
    result = forecast_with_model(values, candidate(method), settings)
    assert result.status == "completed", result.model_dump()
    return result


@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda c: f'{c["interval"]}-{c["kind"]}')
def test_local_trend_matches_unmodified_usagetap_current(case):
    windows = {"hour": 1344, "day": 56, "week": 52, "month": 36}
    data = ForecastDataset(interval=case["interval"], values=case["values"])
    for scenario in case["scenarios"]:
        result = forecast_with_model(data, candidate("local_trend", training_window=windows[data.interval]),
            dict(horizon=case["horizon"], lower_bound=0, trend_adjustment_pct=scenario["adjustment"]))
        assert result.status == "completed"
        assert result.predicted == pytest.approx(scenario["predicted"], abs=1e-9)
        default = forecast_with_model(data, candidate("local_trend"),
            dict(horizon=case["horizon"], lower_bound=0, trend_adjustment_pct=scenario["adjustment"]))
        assert default.predicted == result.predicted
        for index, expected in scenario["trend"]:
            # UsageTap clamps its chart's trend. Library components stay signed.
            assert max(0, result.trend[index]) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("method", ["naive", "mean", "median", "ses", "seasonal_naive",
                                   "local_trend", "damped_local_trend", "anomalyzer"])
@pytest.mark.parametrize("level", [0., -12., 10.])
def test_all_methods_preserve_flat_signed_measurements_and_fixed_prefixes(method, level):
    values = [level] * 90
    original = values.copy()
    short = project(values, method, horizon=3)
    long = project(values, method, horizon=35)
    assert short.predicted == pytest.approx([level] * 3)
    assert long.predicted[:3] == short.predicted
    assert short.trend == long.trend[:93]
    assert values == original
    bounded = project(values, method, horizon=3, lower_bound=0)
    assert bounded.predicted == pytest.approx([max(0, level)] * 3)
    assert bounded.trend == short.trend


def test_local_components_adjustment_and_seasonal_naive_are_explicit():
    cycle = [-4, -1, 1, 4, 2, 0, -2]
    values = [20 + .4 * i + cycle[i % 7] for i in range(90)]
    baseline = project(values, horizon=30)
    changed = project(values, horizon=30, trend_adjustment_pct=100)
    assert changed.trend[:90] == baseline.trend[:90]
    assert changed.seasonal_component == baseline.seasonal_component
    anchor = baseline.model.parameters["level"]
    for normal, adjusted in zip(baseline.trend[90:], changed.trend[90:]):
        assert adjusted - anchor == pytest.approx(2 * (normal - anchor))
    assert sum(baseline.seasonal_component[90:97]) == pytest.approx(0, abs=1e-10)
    assert baseline.predicted == pytest.approx([
        t+s for t, s in zip(baseline.trend[90:], baseline.seasonal_component[90:])])
    seasonal = project(values, "seasonal_naive", horizon=14)
    assert seasonal.predicted == values[-7:] * 2
    damped = project([10 + .4 * i for i in range(90)], "damped_local_trend", horizon=30)
    assert damped.predicted[-1] < project([10 + .4 * i for i in range(90)], horizon=30).predicted[-1]
    assert damped.predicted[-1] > damped.predicted[0]


def test_native_family_preserves_its_existing_forward_model():
    values = [10 * math.exp(.012 * i) for i in range(90)]
    legacy = forecast_series(values, dict(horizon=14, outlier_handling="include"))
    new = project(values, "anomalyzer")
    assert new.predicted == legacy.predicted
    assert new.trend == legacy.trend
    assert new.seasonal_component == legacy.seasonal_component
    assert new.model.parameters["native_model"] == legacy.model.model_dump(mode="json")
    assert "expected" not in new.model_dump()
    assert "historical_anomalies" not in new.model_dump()


def test_partial_values_are_never_fitted_or_scored_and_missing_is_unavailable():
    values = [10 + .4*i for i in range(86)]
    partial = {"values": values + [1e9, None], "period_statuses": ["complete"]*86 + ["partial"]*2}
    a = project(partial, horizon=14)
    b = project(values, horizon=16)
    assert a.predicted == pytest.approx(b.predicted[2:])
    assert a.model.anchor_index == 85
    assert a.counts.partial == 2
    selected = select_forecast(values, candidates=[candidate("mean"), candidate("naive")])
    tail = select_forecast(partial, candidates=[candidate("mean"), candidate("naive")])
    assert selected.status == tail.status == "completed"
    assert tail.scores == selected.scores
    assert tail.selected_candidate == selected.selected_candidate
    for data in [
        {"values": values + [None], "period_statuses": ["complete"]*86 + ["missing"]},
        {"values": values, "period_statuses": ["partial"] + ["complete"]*85},
    ]:
        assert forecast_with_model(data, candidate("naive")).reason == "missing_history"
        assert select_forecast(data).reason == "missing_history"


def test_identical_holdouts_prior_only_prefixes_and_reproducible_scores(monkeypatch):
    import anomalyzer.forecast_selection as module
    original = module._project
    seen = []

    def record(data, selected, config, budget):
        seen.append((selected.id, data.values.copy(), config.horizon))
        return original(data, selected, config, budget)

    monkeypatch.setattr(module, "_project", record)
    values = [10 + (i*17 % 19) for i in range(86)]
    settings = dict(horizon=14)
    candidates = [candidate("naive"), candidate("mean")]
    result = select_forecast(values, settings, candidates)
    assert result.status == "completed"
    assert len(seen) == 7  # Two candidates x three folds, then one refit.
    for j, (_, prefix, horizon) in enumerate(seen[:-1]):
        assert horizon == 14
        assert prefix == values[:[44, 58, 72][j % 3]]
    assert seen[-1][1] == values
    assert result == select_forecast(values, settings, candidates)
    for row in result.scores:
        assert [f.holdout_window for f in row.folds] == [(44, 57), (58, 71), (72, 85)]
        for fold in row.folds:
            assert fold.training_window[1] < fold.holdout_window[0]
        assert row.loss == row.mae
        assert sum(row.by_lead_mae) / 14 == pytest.approx(row.mae)
    assert result.selected_candidate == min(result.scores, key=lambda row: row.loss).candidate


def test_requested_horizon_changes_objective_without_a_hidden_one_step_veto():
    values = [0.] * 86
    for index in (43, 57, 71):
        values[index] = 100.
    values[-4:] = [5.] * 4
    candidates = [candidate("naive"), candidate("mean", training_window=14)]
    short = select_forecast(values, dict(horizon=1), candidates)
    long = select_forecast(values, dict(horizon=14), candidates)
    assert short.selected_candidate.method == "naive"
    assert long.selected_candidate.method == "mean"
    assert len(long.scores[0].by_lead_mae) == 14
    assert all(f.holdout_window[1] - f.holdout_window[0] + 1 == 14 for f in long.scores[0].folds)


@pytest.mark.parametrize("objective", ["mae", "rmse", "total_absolute_error"])
def test_declared_losses_are_calculated_from_original_holdouts(objective):
    values = [float(i % 11) for i in range(86)]
    result = select_forecast(values, dict(objective=objective), [candidate("naive")])
    score = result.scores[0]
    residuals = [values[origin - 1] - value for origin in (44, 58, 72) for value in values[origin:origin+14]]
    if objective == "mae":
        expected = sum(abs(e) for e in residuals) / 42
    elif objective == "rmse":
        expected = math.sqrt(sum(e*e for e in residuals) / 42)
    else:
        expected = sum(abs(sum(residuals[i:i+14])) for i in (0, 14, 28)) / 3
    assert score.loss == pytest.approx(expected)
    assert score.bias == pytest.approx(sum(residuals)/42)
    assert score.wape == pytest.approx(sum(abs(e) for e in residuals) / sum(values[44:]))


def test_insufficient_history_ties_zero_denominators_and_failed_candidates():
    assert select_forecast([10.]*69).reason == "insufficient_history"
    assert select_forecast([10.]*70).status == "completed"
    result = select_forecast([0.]*86)
    assert result.selected_candidate.id == "naive"
    assert all(row.loss == 0 and row.wape is None for row in result.scores if row.status == "completed")
    bad = candidate("seasonal_naive", period=100)
    partly = select_forecast([10.]*86, candidates=[bad, candidate("naive")])
    assert partly.status == "completed"
    assert partly.selected_candidate.method == "naive"
    assert partly.scores[0].status == "unavailable"
    assert partly.scores[0].reason == "insufficient_history"
    assert partly.scores[0].loss is None
    failed = select_forecast([10.]*86, candidates=[bad])
    assert failed.reason == "no_viable_candidate"
    assert failed.forecast is failed.selected_candidate is None


def test_selection_does_not_rewrite_earlier_forecasts_or_default_detector_evidence():
    values = [20 + (i*17 % 19) for i in range(86)]
    reference = forecast_series(values, dict(historical_anomalies={}))
    result = select_forecast(values)
    assert result.status == "completed"
    assert reference == forecast_series(values, dict(historical_anomalies={}))
    frozen = forecast_with_model(values, result.selected_candidate)
    longer = forecast_with_model(values, result.selected_candidate, dict(horizon=30))
    assert frozen.predicted == longer.predicted[:14]


def test_outer_holdout_targets_never_enter_selection():
    # Selection error and independent outer error are deliberately different.
    values = [10.]*86 + [100.]*14
    result = select_forecast(values[:86])
    assert result.status == "completed"
    assert result.scores[0].loss == 0
    outer_mae = sum(abs(p-a) for p,a in zip(result.forecast.predicted, values[86:])) / 14
    assert outer_mae == 90
    assert any("outer holdouts" in note for note in result.limitations)


def test_calendar_timestamps_are_propagated_after_partial_tail():
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [(origin + timedelta(days=i)).isoformat() for i in range(87)]
    data = ForecastDataset(values=[10.]*86 + [None], timestamps=timestamps,
        period_statuses=["complete"]*86 + ["partial"])
    result = select_forecast(data)
    assert result.status == "completed"
    assert datetime.fromisoformat(result.forecast.predicted_timestamps[0]) == origin + timedelta(days=87)
    assert result.forecast.counts.partial == 1


@pytest.mark.parametrize("bad", [True, "2", float("nan"), float("inf"), 10**400])
def test_nonfinite_inputs_and_parameters_are_rejected(bad):
    assert forecast_with_model([bad]*86, candidate("naive")).reason == "invalid_input"
    assert select_forecast([bad]*86).reason == "invalid_input"
    assert forecast_with_model([10.]*86, dict(id="ses", method="ses", alpha=bad)).reason == "invalid_input"
    assert select_forecast([10.]*86, dict(lower_bound=bad)).reason == "invalid_input"


@pytest.mark.parametrize("bad", [False, [], "", {"horizon": True}, {"horizon": 0},
    {"folds": 2}, {"folds": 9}, {"objective": "mape"}, {"trend_adjustment_pct": 10}, {"unknown": 1}])
def test_invalid_selection_settings_do_not_fall_back(bad):
    assert select_forecast([10.]*86, bad).reason == "invalid_input"


def test_candidate_parameters_and_catalog_are_validated():
    for kwargs in [dict(alpha=.5), dict(damping=.9), dict(period=7), dict(outlier_handling="robust"), dict(trend="auto")]:
        with pytest.raises(ValidationError):
            candidate("naive", **kwargs)
    for candidates in [[], [candidate("naive")]*2, [dict(id=str(i), method="naive") for i in range(33)]]:
        assert select_forecast([10.]*86, candidates=candidates).reason == "invalid_input"
    assert {c.method for c in default_forecast_candidates()} == {
        "naive", "seasonal_naive", "mean", "median", "ses", "local_trend", "damped_local_trend", "anomalyzer"}


def test_budget_and_numerical_failures_are_atomic(monkeypatch):
    for call in [lambda: select_forecast([10.]*86, dict(max_runtime_seconds=1e-12)),
                 lambda: forecast_with_model([10.]*86, candidate("naive"), dict(max_runtime_seconds=1e-12))]:
        result = call()
        assert result.reason == "budget_exceeded"
    result = select_forecast([1e308]*86, candidates=[candidate("mean")])
    assert result.reason == "nonfinite_result"
    assert result.forecast is result.selected_candidate is result.scores is None
    import anomalyzer.forecast_selection as module
    original = module._project
    calls = 0

    def fail_during_comparison(*args):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise TimeoutError()
        return original(*args)

    monkeypatch.setattr(module, "_project", fail_during_comparison)
    result = select_forecast([10.]*86)
    assert result.reason == "budget_exceeded"
    assert result.scores is result.selected_candidate is result.forecast is None


def test_public_requests_schemas_and_round_trips():
    data = ForecastDataset(values=[10.]*86)
    request = ModelForecastRequest(dataset=data, candidate=candidate("local_trend"))
    model = forecast_with_model(request)
    assert model == forecast_with_model(request.model_dump_json())
    assert model == forecast_with_model(data, request.candidate, ModelForecastSettings())
    selection_request = ForecastSelectionRequest(dataset=data)
    selection = select_forecast(selection_request)
    assert selection == select_forecast(selection_request.model_dump_json()) == select_forecast(data)
    assert forecast_with_model(request, candidate("naive")).reason == "invalid_input"
    assert select_forecast(selection_request, {}).reason == "invalid_input"
    assert select_forecast({**selection_request.model_dump(), "schema_version": "unknown"}).reason == "unsupported_contract"
    assert forecast_with_model({**request.model_dump(), "task": "unknown"}).reason == "unsupported_contract"
    for name, cls, value in [
        ("forecast-model-request", ModelForecastRequest, request),
        ("forecast-model-result", ModelForecastResult, model),
        ("forecast-selection-request", ForecastSelectionRequest, selection_request),
        ("forecast-selection-result", ForecastSelectionResult, selection),
    ]:
        schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
        assert {k:v for k,v in schema.items() if k != "$schema"} == cls.model_json_schema()
        jsonschema.validate(value.model_dump(mode="json"), schema)
    broken = model.model_dump()
    broken["predicted"] = []
    with pytest.raises(ValidationError):
        ModelForecastResult.model_validate(broken)
    other = select_forecast(data, candidates=[candidate("mean")])
    assert other.request_fingerprint != selection.request_fingerprint
