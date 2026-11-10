"""Real-library causal history; anonymous synthetic inputs only."""
import importlib.util
import json
import math
from pathlib import Path

import jsonschema
import pytest

from anomalyzer import (
    ForecastRequest, ForecastResult, HistoricalAnomalies, HistoricalAnomalySettings,
    __version__, forecast_series,
)

ROOT = Path(__file__).resolve().parents[1]


def run(values, **config):
    result = forecast_series(values, {"historical_anomalies": {}, **config})
    assert result.status == "completed", result.model_dump()
    return result


def series(n=120):
    return [100 + .1 * i + [0, 2, -1, 3, -2, 1, -3][i % 7] for i in range(n)]


@pytest.mark.parametrize("handling", ["include", "robust"])
@pytest.mark.parametrize("seasonality", ["auto", {"period": 7}])
def test_frozen_origin_changed_target_suffix_and_appended_suffix(handling, seasonality):
    values = series()
    values[84:89] = [300.] * 5
    cfg = dict(outlier_handling=handling, seasonality=seasonality)
    base = run(values, **cfg).historical_anomalies
    # Includes changes during provisional calibration and its retrospective
    # robust screening; those must not rewrite previously exposed point rows.
    for at in (57, 60, 69, 70, 85, 99):
        changed = run(values[:at] + [500 + i % 5 for i in range(len(values) - at)], **cfg).historical_anomalies
        assert changed.points[:at] == base.points[:at]
        assert changed.points[at].expected == base.points[at].expected
        assert changed.origin_fingerprint == base.origin_fingerprint
        assert [p for p in changed.patterns if p.detection_index < at] == [p for p in base.patterns if p.detection_index < at]
    for end in (60, 70, 71, 86, 90, 100):
        prefix = run(values[:end], **cfg).historical_anomalies
        assert prefix.points == base.points[:end]
        assert prefix.patterns == [p for p in base.patterns if p.detection_index < end]


def test_pattern_snapshots_are_available_at_detection_and_do_not_grow():
    values = [100 + (i % 3 - 1) for i in range(70)] + [130.] * 20 + [50.] * 12 + [100.] * 5
    full = run(values, trend="none").historical_anomalies
    assert {p.rule for p in full.patterns} >= {"cusum", "adjacent_point_anomalies", "nelson_rule_2"}
    for end in range(71, len(values) + 1):
        prefix = run(values[:end], trend="none").historical_anomalies
        assert prefix.patterns == [p for p in full.patterns if p.detection_index < end]
    for pattern in full.patterns:
        assert pattern.available_from_index == pattern.detection_index
        assert pattern.triggering_indices[-1] == pattern.detection_index
        assert all(full.points[i].maturity == "calibrated" for i in pattern.triggering_indices)


@pytest.mark.parametrize("rule,scores,offset", [
    ("adjacent_point_anomalies", [4,4], 1),
    ("cusum", [1.4]*6, 5),
    ("moving_range", [-2,2], 1),
    ("nelson_rule_2", [.5]*9, 8),
    ("nelson_rule_3", [.1,.2,.3,.4,.5,.6], 5),
    ("nelson_rule_4", [.5,-.5]*7, 13),
    ("nelson_rule_5", [2.5,0,2.5], 2),
    ("nelson_rule_6", [1.2]*4+[0], 4),
    ("nelson_rule_8", [1.5,-1.5]*4, 7),
])
def test_every_supported_pattern_uses_native_rule_and_correct_availability(rule, scores, offset):
    # Include/lag-1 makes each difference a native residual. The fourteen
    # calibration differences have mean zero and known sample stdev.
    values = [100.] * 28
    for residual in [-1.,1.] * 7 + [score * math.sqrt(14/13) for score in scores]:
        values.append(values[-1] + residual)
    cfg = dict(trend="none", seasonality={"period": 1}, outlier_handling="include")
    full = run(values, **cfg).historical_anomalies
    event = next(p for p in full.patterns if p.rule == rule)
    assert event.detection_index == event.available_from_index == 42 + offset
    earlier = run(values[:event.detection_index], **cfg).historical_anomalies
    assert not any(p.rule == rule for p in earlier.patterns)
    at_detection = run(values[:event.detection_index+1], **cfg).historical_anomalies
    assert event in at_detection.patterns


def test_warmup_reference_provisional_calibrated_support_and_cutoff():
    result = run([10.] * 100)
    evidence = result.historical_anomalies
    assert all(p.expected is None and p.availability == "unavailable" for p in evidence.points[:56])
    assert [p.maturity for p in evidence.points[56:71]] == ["reference_only"] * 3 + ["provisional"] * 11 + ["calibrated"]
    assert evidence.points[56].standardized_score is None
    assert evidence.points[59].calibration_samples == 3
    assert evidence.points[59].calibration_cutoff_index == 58
    assert evidence.points[70].calibration_cutoff_index == 69
    assert evidence.points[70].reference_cutoff_index == 69
    assert evidence.calibration.samples == 14
    assert evidence.calibration.available_from_index == 70
    assert evidence.readiness_available_from_index == 70
    assert evidence.readiness["status"] == "caution"
    assert evidence.calibration.raw_scale == 0
    assert evidence.calibration.scale == 1e-8
    assert all(not p.triggers for p in evidence.points)
    for n in (8, 55, 56):
        warmup = run([10.] * n).historical_anomalies
        assert warmup.availability == "unavailable" and warmup.unavailable_reason == "warmup"
        assert warmup.calibration is None and not warmup.patterns


@pytest.mark.parametrize("level", [0., 100.])
@pytest.mark.parametrize("handling", ["robust", "include"])
def test_quiet_true_zero_spike_drop_native_scores_and_exclusions(level, handling):
    values = [level] * 100
    values[80], values[90] = level + 100, level - 100
    result = run(values, trend="none", outlier_handling=handling)
    evidence = result.historical_anomalies
    assert evidence.points[79].observed == level
    assert evidence.points[80].triggers == evidence.points[90].triggers == ["point"]
    assert evidence.points[80].direction == "increase" and evidence.points[90].direction == "decrease"
    for point in evidence.points[70:]:
        assert point.residual == point.observed - point.expected
        assert point.standardized_score == pytest.approx((point.residual - evidence.calibration.center) / evidence.calibration.scale)
        assert math.isfinite(point.standardized_score)
    if handling == "include":
        assert evidence.reference_adjustments == []
    else:
        assert {a.index for a in evidence.reference_adjustments} >= {80, 90}
    assert values[80] == level + 100


def test_signed_reference_is_distinct_from_clamped_display_expected():
    result = run([-10.] * 90, lower_bound=0)
    point = result.historical_anomalies.points[80]
    assert result.expected[80] == 0
    assert point.expected == -10 and point.residual == point.standardized_score == 0
    assert point.observed - result.expected[80] != point.residual
    assert result.trend[80] == -10


def test_retrospective_screening_is_not_a_point_incident():
    values = [100 + .2 * i for i in range(110)]
    values[20], values[63] = 1000, 900
    evidence = run(values, trend="linear").historical_anomalies
    training = next(a for a in evidence.reference_adjustments if a.index == 20)
    calibration = next(a for a in evidence.reference_adjustments if a.index == 63)
    assert training.available_from_index == 56
    assert calibration.available_from_index == 70
    assert evidence.points[20].triggers == evidence.points[63].triggers == []
    assert evidence.points[20].availability == "unavailable"
    assert evidence.points[63].maturity == "provisional"


def test_partial_tail_missing_and_gaps_preserve_original_positions():
    values = [100.] * 90 + [120., None]
    result = run({"values": values, "period_statuses": ["complete"] * 90 + ["partial"] * 2})
    assert [p.index for p in result.historical_anomalies.points] == list(range(92))
    assert [p.observed for p in result.historical_anomalies.points[-2:]] == [120., None]
    assert all(p.unavailable_reason == "partial" and p.expected is None and p.triggers == [] for p in result.historical_anomalies.points[-2:])
    for index in (0, 70, 91):
        missing = values.copy()
        statuses = ["complete"] * 90 + ["partial"] * 2
        missing[index], statuses[index] = None, "missing"
        failed = forecast_series({"values": missing, "period_statuses": statuses}, {"historical_anomalies": {}})
        assert failed.reason == "missing_history" and failed.historical_anomalies is None


@pytest.mark.parametrize("interval,window,horizon,k", [("hour",1344,168,768), ("day",56,90,56), ("week",52,26,52), ("month",36,24,36)])
def test_bridge_caps_budget_alignment_and_horizon_independence(interval, window, horizon, k):
    data = {"values": [100 + i % 7 for i in range(6000)], "interval": interval}
    cfg = dict(max_training_points=window, max_inference_points=768)
    long = run(data, horizon=horizon, **cfg)
    short = run(data, horizon=3, trend_adjustment_pct=100, **cfg)
    evidence = long.historical_anomalies
    assert evidence.training_window == (0, k-1)
    assert evidence.points[k-1].expected is None
    assert evidence.points[k+14].maturity == "calibrated"
    assert evidence == short.historical_anomalies
    assert len(long.predicted) == horizon
    failed = forecast_series(data, {**cfg, "historical_anomalies": {}, "max_runtime_seconds": 1e-12})
    assert failed.reason == "budget_exceeded" and failed.historical_anomalies is None


def test_opt_in_reuses_one_analysis_and_preserves_all_forecast_values(monkeypatch):
    import anomalyzer.forecast as module
    original = module.analyze_dataset
    calls = []
    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "analyze_dataset", count)
    data = series()
    data[95] = 800
    plain = forecast_series(data)
    native = run(data)
    assert len(calls) == 2  # once for each forecast call
    for field in ("expected", "eligible", "predicted", "trend", "seasonal_component", "outlier_indices", "model", "historical_evidence_maturity"):
        assert getattr(plain, field) == getattr(native, field)
    assert native == run(data)  # deterministic; no run IDs or runtime measurements
    assert plain.historical_anomalies is None
    custom = run(data, historical_anomalies={"point_threshold": 1e20})
    assert custom.predicted == plain.predicted
    assert not any(p.triggers for p in custom.historical_anomalies.points)
    assert custom.historical_anomalies.origin_fingerprint != native.historical_anomalies.origin_fingerprint


def test_evidence_projection_budget_failure_returns_no_partial_result(monkeypatch):
    import anomalyzer.forecast_evidence as module
    original = module.HistoricalAnomalyPoint
    def expired(**kwargs):
        if kwargs["index"] == 80:
            raise TimeoutError("budget exhausted while projecting evidence")
        return original(**kwargs)
    monkeypatch.setattr(module, "HistoricalAnomalyPoint", expired)
    result = forecast_series(series(), {"historical_anomalies": {}})
    assert result.reason == "budget_exceeded"
    assert result.historical_anomalies is result.predicted is result.expected is None


@pytest.mark.parametrize("bad", [{"point_threshold": True}, {"point_threshold": "3"}, {"scale_floor": 0}, {"cusum_h": float("inf")}, {"schema_version": "v99"}, {"severity": "critical"}])
def test_invalid_detector_configuration(bad):
    assert forecast_series([10.] * 90, {"historical_anomalies": bad}).reason == "invalid_input"


def test_public_models_and_schemas():
    result = run(series())
    request = ForecastRequest.model_validate({"dataset": {"values": series()}, "config": {"historical_anomalies": {}}})
    assert forecast_series(request.model_dump_json()) == result
    for name, model, value in [
        ("forecast-request", ForecastRequest, request), ("forecast-result", ForecastResult, result),
        ("historical-anomalies-request", HistoricalAnomalySettings, request.config.historical_anomalies),
        ("historical-anomalies-result", HistoricalAnomalies, result.historical_anomalies),
    ]:
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert {k:v for k,v in schema.items() if k != "$schema"} == model.model_json_schema()
        jsonschema.validate(value.model_dump(mode="json"), schema)


def test_compatibility_adapter_keeps_old_shape_and_negotiates_evidence(monkeypatch):
    spec = importlib.util.spec_from_file_location("bridge", ROOT / "examples/library/usagetap_forecast.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    event = dict(contract="usage-forecast-v1", operation="forecast", values=series(), interval="day", horizon=30, excludeExtremeOutliers=True)
    monkeypatch.setattr(bridge, "VERSION", "0.0.0")
    assert bridge.forecast_usage(event)["reason"] == "unsupported_contract"
    monkeypatch.setattr(bridge, "VERSION", __version__)
    legacy = bridge.forecast_usage(event)
    native = bridge.forecast_usage({**event, "historicalAnomalies": {"schema_version": "historical-anomalies-v1"}})
    assert native.pop("historicalAnomalies")["points"][70]["maturity"] == "calibrated"
    # Fingerprints in legacy notes identify the distinct requested contract.
    assert native["expected"] == legacy["expected"] and native["predicted"] == legacy["predicted"]
    assert set(native) == set(legacy)
    assert bridge.forecast_usage({**event, "historicalAnomalies": {"schema_version": "v99"}})["reason"] == "unsupported_contract"
