"""Public scenarios, causal evidence, calendar alignment and bridge safety."""
import importlib.util
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import (
    ForecastDataset, ForecastRequest, ForecastResult, ForecastSettings,
    __version__, forecast_series,
)

ROOT = Path(__file__).resolve().parents[1]


def completed(values, **config):
    result = forecast_series(values, config)
    assert result.status == "completed", result.model_dump()
    return result


@pytest.mark.parametrize("level", [0., 12., -8.])
def test_flat_true_zero_and_signed_values(level):
    result = completed([level] * 90)
    assert result.predicted == pytest.approx([level] * 30)
    assert result.model.trend_kind == "none"
    assert result.counts.complete == 90
    assert completed([level] * 90, lower_bound=0).predicted == pytest.approx([max(0, level)] * 30)


@pytest.mark.parametrize("slope", [.5, -.5])
@pytest.mark.parametrize("handling", ["robust", "include"])
def test_linear_projection_and_lower_bound(slope, handling):
    values = [10 + slope * i for i in range(86)]
    result = completed(values, outlier_handling=handling)
    assert result.model.trend_kind == "linear"
    assert result.predicted == pytest.approx([10 + slope * i for i in range(86, 116)])
    bounded = completed(values, outlier_handling=handling, lower_bound=0)
    assert bounded.predicted == pytest.approx([max(0, v) for v in result.predicted])
    assert bounded.trend == result.trend


@pytest.mark.parametrize("kind", ["linear", "exponential"])
@pytest.mark.parametrize("partial_count", [0, 1, 3])
def test_adjustment_partial_tails_and_horizon_prefixes(kind, partial_count):
    values = [10 + .5 * i if kind == "linear" else 10 * math.exp(.012 * i) for i in range(90)]
    data = {"values": values + [999.] * partial_count,
            "period_statuses": ["complete"] * 90 + ["partial"] * partial_count}
    base = completed(data, horizon=20)
    adjusted = completed(data, horizon=20, trend_adjustment_pct=100)
    short = completed(data, horizon=5, trend_adjustment_pct=100)
    assert base.model.trend_kind == kind
    assert adjusted.predicted[:5] == short.predicted
    assert adjusted.trend[:95 + partial_count] == short.trend
    assert adjusted.seasonal_component == base.seasonal_component
    assert base.expected == adjusted.expected
    assert base.trend[:len(data["values"])] == adjusted.trend[:len(data["values"])]
    anchor_level = base.model.trend_parameters["level"]
    for normal, changed in zip(base.predicted, adjusted.predicted):
        assert changed - anchor_level == pytest.approx(2 * (normal - anchor_level), rel=1e-6)
    without_tail = completed(values, horizon=25)
    assert base.predicted == pytest.approx(without_tail.predicted[partial_count:partial_count + 20])
    assert base.expected[90:] == [None] * partial_count
    assert base.eligible[90:] == [False] * partial_count
    assert base.future_origin_index == 90 + partial_count


@pytest.mark.parametrize("period,points,automatic", [(7, 100, True), (24, 192, False), (12, 120, True), (365, 1460, False)])
def test_weekly_daily_and_annual_recurrence(period, points, automatic):
    # Anonymous synthetic values, never customer financial data.
    cycle = [5 * math.sin(2 * math.pi * p / period) + 2 * math.cos(4 * math.pi * p / period) for p in range(period)]
    values = [30 + cycle[i % period] for i in range(points)]
    result = completed(values, max_training_points=points,
        seasonality="auto" if automatic else {"period": period}, trend="none", max_runtime_seconds=15)
    assert result.model.season_length == period
    assert result.predicted == pytest.approx([30 + cycle[i % period] for i in range(points, points + 30)])
    # Annual positional recurrence is not a leap-year calendar model.
    assert any("leap" in note for note in result.limitations)


def test_sharp_daily_cycle_can_be_inferred_but_smooth_cycle_is_conservative():
    values = [20 + (i % 24) for i in range(240)]
    result = completed(values, max_training_points=192)
    assert result.model.season_length == 24
    smooth = completed([20 + 5 * math.sin(2 * math.pi * i / 24) for i in range(240)], max_training_points=192)
    assert smooth.model.season_length == 1


def test_short_history_and_no_stable_season():
    short = completed([10.] * 8)
    assert short.forecast_applicability == "scenario_available"
    assert short.expected == [None] * 8
    assert not any(short.eligible)
    assert short.model.historical_readiness["status"] == "not_assessed"
    assert forecast_series([10.] * 7).reason == "insufficient_history"
    assert completed([i * i for i in range(40)]).model.season_inference["status"] == "not_detected"


@pytest.mark.parametrize("statuses,values,reason", [
    (["complete"] * 10 + ["missing"], [10.] * 10 + [None], "missing_history"),
    (["complete"] * 4 + ["missing"] + ["complete"] * 5, [10.] * 4 + [None] + [10.] * 5, "missing_history"),
    (["partial"] + ["complete"] * 9, [None] + [10.] * 9, "missing_history"),
    (["complete"] * 10, [10.] * 9 + [None], "invalid_input"),
    (["missing"] * 10, [1.] * 10, "invalid_input"),
])
def test_missing_and_internal_partial_are_never_compressed(statuses, values, reason):
    result = forecast_series({"values": values, "period_statuses": statuses})
    assert result.reason == reason
    assert result.predicted is None


def test_known_null_partial_tail_is_distinct_from_unknown_null():
    assert forecast_series([10.] * 10 + [None]).reason == "invalid_input"
    result = completed({"values": [10.] * 10 + [None], "period_statuses": ["complete"] * 10 + ["partial"]})
    assert result.counts.partial == 1
    assert result.predicted == [10.] * 30


@pytest.mark.parametrize("bad", [True, "2", float("nan"), float("inf"), -float("inf"), 10**400])
def test_invalid_nonfinite_inputs(bad):
    assert forecast_series([bad] * 8).reason == "invalid_input"
    with pytest.raises(ValidationError):
        ForecastDataset(values=[bad] * 8)


@pytest.mark.parametrize("config", [{"horizon": True}, {"horizon": 0}, {"max_points": 7},
    {"trend_adjustment_pct": True}, {"trend_adjustment_pct": 201}, {"lower_bound": float("nan")},
    {"max_runtime_seconds": float("inf")}, {"seasonality": {"period": 0}}, {"unknown": 3}])
def test_settings_are_validated(config):
    assert forecast_series([10.] * 8, config).reason == "invalid_input"


def test_json_models_schemas_and_fingerprint():
    request = ForecastRequest(dataset=ForecastDataset(values=[10.] * 90))
    typed = forecast_series(request)
    string = forecast_series(request.model_dump_json())
    bare = forecast_series([10.] * 90, ForecastSettings())
    assert typed == string == bare
    for name, model, value in [("forecast-request", ForecastRequest, request.model_dump(mode="json")),
                               ("forecast-result", ForecastResult, typed.model_dump(mode="json"))]:
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert {k: v for k, v in schema.items() if k != "$schema"} == model.model_json_schema()
        jsonschema.validate(value, schema)
    assert forecast_series({**request.model_dump(), "schema_version": "forecast-v9"}).reason == "unsupported_contract"
    assert forecast_series(request, {}).reason == "invalid_input"
    assert forecast_series("{bad").reason == "invalid_input"
    assert completed([11.] * 90).request_fingerprint != typed.request_fingerprint
    assert completed([10.] * 90, trend_adjustment_pct=0).request_fingerprint == typed.request_fingerprint
    invalid = typed.model_dump()
    invalid["predicted"] = invalid["predicted"][:-1]
    with pytest.raises(ValidationError):
        ForecastResult.model_validate(invalid)


@pytest.mark.parametrize("invalid_settings", [False, 0, [], ""])
def test_falsey_settings_are_rejected(invalid_settings):
    assert forecast_series([10.] * 8, invalid_settings).reason == "invalid_input"


def test_budget_and_numerical_failures_never_expose_partial_forecasts(monkeypatch):
    import anomalyzer.forecast as module
    assert forecast_series([10.] * 90, {"max_runtime_seconds": 1e-12}).reason == "budget_exceeded"
    for failure, reason in [(TimeoutError(), "budget_exceeded"), (OverflowError(), "nonfinite_result"),
                            (RuntimeError(), "analysis_incomplete"), (ValueError(), "analysis_failed")]:
        def fail(*args, **kwargs):
            raise failure
        with monkeypatch.context() as patch:
            patch.setattr(module, "fit_trend", fail)
            result = forecast_series([10.] * 90)
        assert result.reason == reason
        assert result.predicted is result.expected is result.trend is None
        jsonschema.validate(result.model_dump(mode="json"), ForecastResult.model_json_schema())
    assert forecast_series([1e308] * 90).status == "unavailable"


def test_robust_screening_trimming_and_original_indices():
    values = [20 + .2 * i for i in range(120)]
    values[110] = 1000
    values[119] = 500
    original = values.copy()
    robust = completed(values, outlier_handling="robust")
    include = completed(values, outlier_handling="include")
    assert values == original
    assert {110, 119}.issubset(robust.outlier_indices)
    assert include.outlier_indices == []
    assert robust.predicted != include.predicted
    assert robust.model.outlier_policy["downweighted_count"] > 0
    assert robust.model.fit_window == (64, 119)
    assert robust.predicted[0] == pytest.approx(44., abs=.5)


@pytest.mark.parametrize("handling", ["include", "robust"])
@pytest.mark.parametrize("seasonality", ["auto", {"period": 7}])
def test_later_changes_and_appends_do_not_contaminate_qualified_history(handling, seasonality):
    cycle = [-3, -1, 1, 2, 4, -1, -2]
    values = [20 + .2 * i + cycle[i % 7] for i in range(120)]
    cfg = dict(outlier_handling=handling, seasonality=seasonality)
    base = completed(values, **cfg)
    for at in (56, 70, 90, 119):
        changed = completed(values[:at] + [10000 + i % 3 for i in range(120 - at)], **cfg)
        assert changed.expected[:at + 1] == base.expected[:at + 1]
        assert changed.eligible[:at + 1] == base.eligible[:at + 1]
    for end in (71, 85, 100):
        prefix = completed(values[:end], **cfg)
        assert prefix.expected == base.expected[:end]
        assert prefix.eligible == base.eligible[:end]
        assert prefix.historical_evidence_maturity == base.historical_evidence_maturity[:end]
    assert any(base.eligible)
    assert all(value is None for value in base.expected[:28 if seasonality != "auto" else 56])


def test_sustained_regime_change_is_observed_and_limitation_is_explicit():
    values = [10.] * 60 + [30.] * 60
    robust, include = completed(values), completed(values, outlier_handling="include")
    assert robust.predicted == pytest.approx([30.] * 30)
    assert include.predicted == pytest.approx([30.] * 30)
    assert robust.model.fit_window == (64, 119)
    assert any("regime" in note for note in robust.limitations)


def test_historical_reference_adjustments_keep_original_chart_coordinates():
    values = [10.] * 200
    values[100] = 500
    result = completed(values)
    assert result.model.fit_window == (144, 199)
    assert 100 in result.outlier_indices
    assert 100 in result.model.outlier_policy["historical_reference_adjustments"]["evaluation_reference_replacements"]
    assert result.expected[100] == 10
    assert result.eligible[100] is True
    assert result.predicted == [10.] * 30


def calendar_data(stamps, interval="day", zone="UTC"):
    return {"values": [10.] * len(stamps), "timestamps": stamps, "interval": interval, "timezone": zone}


def test_local_daily_dst_and_hourly_fold_are_calendar_buckets():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/Los_Angeles")
    days = [(datetime(2026, 10, 30, tzinfo=zone) + timedelta(days=i)).isoformat() for i in range(12)]
    result = completed(calendar_data(days, zone=str(zone)), horizon=3)
    assert result.predicted_timestamps[0] == "2026-11-11T00:00:00-08:00"
    # Two local 01:00s are distinct buckets with different offsets.
    hours = [(datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(hours=i)).isoformat() for i in range(12)]
    result = completed(calendar_data(hours, "hour", str(zone)), horizon=2)
    assert result.predicted_timestamps[0] == "2026-11-01T04:00:00-08:00"


@pytest.mark.parametrize("interval,stamps,next_time", [
    ("month", [f"2026-{m:02d}-01T00:00:00Z" for m in range(1, 9)], "2026-09-01T00:00:00+00:00"),
    ("year", [f"{y}-01-01T00:00:00Z" for y in range(2019, 2027)], "2027-01-01T00:00:00+00:00"),
    ("week", [(datetime(2026, 1, 5, tzinfo=timezone.utc) + timedelta(weeks=i)).isoformat() for i in range(8)], "2026-03-02T00:00:00+00:00"),
])
def test_unequal_months_leap_years_and_weeks(interval, stamps, next_time):
    assert completed(calendar_data(stamps, interval), horizon=1).predicted_timestamps == [next_time]


@pytest.mark.parametrize("mutation", ["duplicate", "gap", "reverse", "naive", "off_boundary", "length", "zone"])
def test_bad_calendar_inputs(mutation):
    stamps = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat() for i in range(8)]
    data = calendar_data(stamps)
    if mutation == "duplicate": stamps[3] = stamps[2]
    if mutation == "gap": stamps[3] = "2026-01-05T00:00:00Z"
    if mutation == "reverse": stamps.reverse()
    if mutation == "naive": stamps[3] = "2026-01-04T00:00:00"
    if mutation == "off_boundary": stamps[3] = "2026-01-04T01:00:00Z"
    if mutation == "length": stamps.pop()
    if mutation == "zone": data["timezone"] = "Not/AZone"
    assert forecast_series(data).reason == "invalid_input"


def test_usage_tap_bridge_contract_and_pin(monkeypatch):
    spec = importlib.util.spec_from_file_location("bridge", ROOT / "examples/library/usagetap_forecast.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    event = {"operation": "forecast", "contract": "usage-forecast-v1", "values": [20 + .5 * i for i in range(90)] + [None],
        "interval": "day", "horizon": 30, "trendAdjustmentPct": 0, "excludeExtremeOutliers": True}
    monkeypatch.setattr(bridge, "VERSION", "0.0.0")
    assert bridge.forecast_usage(event)["reason"] == "unsupported_contract"
    monkeypatch.setattr(bridge, "VERSION", __version__)
    result = bridge.forecast_usage(event)
    assert set(result) == {"contract", "status", "expected", "eligible", "predicted", "trend", "outlierIndices", "model"}
    assert result["status"] == "completed"
    assert len(result["expected"]) == len(result["eligible"]) == 91
    assert len(result["predicted"]) == 30 and len(result["trend"]) == 121
    assert result["expected"][-1] is None and result["eligible"][-1] is False
    assert set(result["model"]) == {"method", "label", "engineVersion", "trendKind", "seasonLength", "seasonalityStatus", "notes"}
    assert all(math.isfinite(v) and v >= 0 for key in ("predicted", "trend") for v in result[key])
    bad = {**event, "values": [10.] * 5 + [None] + [10.] * 5}
    assert bridge.forecast_usage(bad) == {"contract": bridge.CONTRACT, "status": "unavailable", "reason": "missing_history"}
    assert bridge.forecast_usage({**event, "excludeExtremeOutliers": 1})["reason"] == "invalid_input"


@pytest.mark.parametrize("interval,window,horizon", [("hour", 1344, 168), ("day", 56, 90), ("week", 52, 26), ("month", 36, 24)])
def test_usage_tap_maximum_history_and_horizons(interval, window, horizon):
    values = [20 + i % 7 for i in range(6000)]
    result = completed({"values": values, "interval": interval},
        max_training_points=window, max_inference_points=768, horizon=horizon)
    assert len(result.expected) == 6000
    assert len(result.predicted) == horizon
    assert result.model.fit_window == (6000 - window, 5999)


def test_public_horizon_limit_and_seasonal_adjustment_shape():
    cycle = [-3, -1, 1, 2, 4, -1, -2]
    values = [20 + .2 * i + cycle[i % 7] for i in range(90)]
    base = completed(values, horizon=6000, seasonality={"period": 7}, trend="linear")
    adjusted = completed(values, horizon=10, seasonality={"period": 7}, trend="linear", trend_adjustment_pct=100)
    assert len(base.predicted) == 6000
    assert adjusted.expected == base.expected
    assert adjusted.seasonal_component == base.seasonal_component[:100]
    assert sum(base.seasonal_component[90:97]) == pytest.approx(0, abs=1e-10)
    for i in range(10):
        assert adjusted.predicted[i] - base.predicted[i] == pytest.approx(.2 * (i + 1))
