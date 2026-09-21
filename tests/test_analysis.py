import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from jsonschema import validate
from anomalyzer import Request, analyze
from anomalyzer.baseline import expected_value
from anomalyzer.contracts import Dataset, Settings, Result
from anomalyzer.evaluation import replay
from anomalyzer.evidence import anomaly_patterns
from anomalyzer.validation import prepare, timestamp


@pytest.mark.parametrize("period,expected", [(1, 8), (2, 4), (4, 1)])
def test_forecast_independent_reference(period, expected):
    assert expected_value([1., 2., 4., 8.], 4, period) == expected


def test_calibration_reference(request_factory):
    # Increments 1, 2, 3 calibrate mean=2, sample stdev=1.
    result = analyze(request_factory([0, 0, 1, 3, 6, 12], training_size=2, calibration_size=3))
    evidence = result.methods[0].evidence[-1]
    assert evidence["signal_maturity"] == "calibrated"
    assert evidence["calibration_samples"] == 3
    assert evidence["expected"] == 6
    assert evidence["standardized_residual"] == 4
    assert evidence["triggers"] == ["point"]


def test_early_evidence_maturity_and_no_provisional_trigger(request_factory):
    request = request_factory([0, 1, 3, 6, 10, 15], training_size=2,
                              calibration_size=5, point_threshold=1)
    result = analyze(request)
    assert result.status == "insufficient_history"
    evidence = result.methods[0].evidence
    assert [e["signal_maturity"] for e in evidence] == [
        "reference_only", "reference_only", "reference_only",
        "reference_only", "provisional"]
    provisional = evidence[-1]
    assert provisional["calibration_samples"] == 3
    assert provisional["standardized_residual"] == 2
    assert provisional["relative_deviation"] == 0.5
    assert provisional["triggers"] == []
    assert not result.observations


def test_short_series_returns_reference_evidence(request_factory):
    result = analyze(request_factory([100, 110, 105, 120]))
    assert result.status == "insufficient_history"
    assert len(result.methods[0].evidence) == 3
    assert all(e["signal_maturity"] == "reference_only" for e in result.methods[0].evidence)
    assert all(e["standardized_residual"] is None for e in result.methods[0].evidence)
    assert all(not e["triggers"] for e in result.methods[0].evidence)


def test_explicit_incomplete_period_is_reported_and_not_scored(request_factory):
    request = request_factory([100.0] * 49 + [20.0])
    request["datasets"][0]["period_statuses"] = ["complete"] * 49 + ["incomplete"]
    result = analyze(request)
    assert result.status == "completed"
    assert result.data_quality["observation_count"] == 49
    assert result.data_quality["incomplete_count"] == 1
    assert result.data_quality["incomplete_periods"][0]["observed"] == 20
    assert result.methods[0].evidence[-1]["index"] == 48
    assert not result.observations


def test_incomplete_periods_must_be_trailing(request_factory):
    request = request_factory([100.0] * 50)
    request["datasets"][0]["period_statuses"] = (
        ["complete"] * 20 + ["incomplete"] + ["complete"] * 29)
    with pytest.raises(ValueError, match="trailing suffix"):
        analyze(request)


def test_multi_resolution_marks_current_period_and_keeps_two_views():
    count = 60 * 24 + 12
    timestamps = [(datetime(2026, 1, 1, tzinfo=timezone.utc)
                   + timedelta(hours=index)).isoformat()
                  for index in range(count)]
    request = {
        "datasets": [{"id": "calls", "timestamps": timestamps,
                      "values": [100.0] * count, "frequency": "1h",
                      "units": "calls"}],
        "config": {"recipe": "multi-resolution-v1",
                   "max_runtime_seconds": 120},
    }
    result = analyze(request)
    assert result.status == "completed"
    assert [method.id for method in result.methods] == [
        "completed_period:seasonal_trend", "intraday:seasonal_trend"]
    assert result.data_quality["latest_period_status"] == "incomplete"
    incomplete = result.data_quality["incomplete_period"]
    assert incomplete["period_status"] == "incomplete"
    assert incomplete["completed_subperiods"] == 12
    assert incomplete["expected_subperiods"] == 24
    assert incomplete["observed_aggregate"] == 1200
    assert incomplete["included_in_completed_period_view"] is False
    assert len(incomplete["intraday_evidence_refs"]) == 12
    assert incomplete["intraday_triggered_samples"] == []
    assert result.data_quality["views"]["completed_period"]["observation_count"] == 60
    assert result.data_quality["views"]["intraday"]["observation_count"] == count
    assert result.resolved_config["derived"]["intraday_season_length"] == 168


def test_multi_resolution_marks_partial_source_sample_after_full_days():
    count = 50 * 24 + 1
    timestamps = [(datetime(2026, 1, 1, tzinfo=timezone.utc)
                   + timedelta(hours=index)).isoformat()
                  for index in range(count)]
    request = {
        "datasets": [{"timestamps": timestamps, "values": [100.0] * count,
                      "period_statuses": ["complete"] * (count - 1) + ["incomplete"],
                      "frequency": "1h"}],
        "config": {"recipe": "multi-resolution-v1",
                   "max_runtime_seconds": 120},
    }
    result = analyze(request)
    incomplete = result.data_quality["incomplete_period"]
    assert incomplete["completed_subperiods"] == 0
    assert incomplete["observed_aggregate"] is None
    assert incomplete["incomplete_source_samples"][0]["observed"] == 100
    assert result.data_quality["views"]["completed_period"]["observation_count"] == 50
    assert result.data_quality["views"]["intraday"]["observation_count"] == count - 1


def test_multi_resolution_rejects_non_dividing_frequency():
    timestamps = [(datetime(2026, 1, 1, tzinfo=timezone.utc)
                   + timedelta(hours=5 * index)).isoformat()
                  for index in range(20)]
    request = {
        "datasets": [{"timestamps": timestamps, "values": [1.0] * 20,
                      "frequency": "5h"}],
        "config": {"recipe": "multi-resolution-v1"},
    }
    with pytest.raises(ValueError, match="evenly divides"):
        analyze(request)


def test_bare_values_with_separate_settings():
    values = [0, 0, 1, 3, 6, 12]
    result = analyze(values, {"season_length": 1, "training_size": 2,
                              "calibration_size": 3})
    method = result.methods[0]
    assert result.data_quality["coordinate"] == "position"
    assert result.resolved_config["datasets"][0]["timestamps"] is None
    assert method.parameters["season_length_source"] == "explicit"
    assert method.evidence[-1]["timestamp"] is None
    assert method.evidence[-1]["training_cutoff"] == 4
    assert method.evidence[-1]["standardized_residual"] == 4


def test_positional_season_inference_and_fallback():
    periodic = [10, 20, 5, 15, 8, 30, 12] * 12
    inferred = analyze(periodic)
    method = inferred.methods[0]
    assert method.parameters["season_length"] == 7
    assert method.parameters["season_length_source"] == "inferred"
    assert method.diagnostics["season_inference"]["status"] == "detected"
    assert method.diagnostics["season_inference"]["selection_window"] == [0, 27]

    trend = analyze([float(index * index) for index in range(80)])
    method = trend.methods[0]
    assert method.parameters["season_length"] == 1
    assert method.parameters["season_length_source"] == "fallback"
    assert method.diagnostics["season_inference"]["status"] == "not_detected"


def test_positional_episode_uses_integer_interval():
    values = [100.0] * 12
    values[9] = 150
    result = analyze(values, {"season_length": 1, "training_size": 2,
                              "calibration_size": 3})
    assert result.observations[0]["interval"] == [9, 10]


def test_anomaly_stream_detects_consecutive_run(request_factory):
    values = [100.0] * 70
    values[67:70] = [140, 145, 150]
    result = analyze(request_factory(values, season_length=7))
    assert {67, 68, 69} == {e["index"] for e in result.methods[0].evidence if e["triggers"]}
    runs = [pattern for pattern in result.anomaly_patterns
            if pattern["kind"] == "consecutive_run"]
    assert len(runs) == 1
    pattern = runs[0]
    assert pattern["kind"] == "consecutive_run"
    assert pattern["rule"] == "adjacent_point_anomalies"
    assert pattern["sample_count"] == 3
    assert pattern["triggering_samples"] == [67, 68, 69]
    assert pattern["detection_index"] == 68
    assert pattern["direction"] == "increase"
    assert "not a Nelson location-shift rule" in pattern["description"]


@pytest.mark.parametrize("shift,direction", [(2, "increase"), (-2, "decrease")])
def test_nelson_patterns_describe_location_shift_without_point_anomaly(shift, direction):
    values = [round(100 + 8 * math.sin(2 * math.pi * i / 30), 4)
              for i in range(30)]
    calibration = [-1, 1, -.5, .5, -1.2, 1.2, -.8, .8,
                   -.3, .3, -1.1, 1.1, -.6, .6]
    ordinary_tail = [.4, -.4] * 8 if shift > 0 else [-.4, .4] * 8
    residuals = calibration + ordinary_tail
    values += [round(values[i] + residuals[i], 4) for i in range(30)]
    values += [round(values[i] + shift, 4) for i in range(30, 60)]

    result = analyze(values, {"season_length": 30, "trend": "none",
                              "training_size": 30, "calibration_size": 14})
    assert not result.observations
    assert not [item for item in result.methods[0].evidence if item["triggers"]]
    patterns = [pattern for pattern in result.anomaly_patterns
                if pattern["kind"] == "location_shift"]
    assert {(pattern["rule"], pattern["direction"], pattern["detection_index"])
            for pattern in patterns} == {
                ("cusum", direction, 62),
                ("nelson_rule_2", direction, 68),
                ("nelson_rule_5", direction, 61),
                ("nelson_rule_6", direction, 63),
            }
    assert all("location shift" in pattern["description"] for pattern in patterns)
    assert all("full distribution changed" in pattern["description"]
               for pattern in patterns)
    assert all(pattern["peak_standardized_residual"] < 3 for pattern in patterns)


def patterns_for_scores(scores, **settings):
    evidence = [dict(id=f"method:{index}", method="method", index=index,
                     timestamp=None, residual=score,
                     standardized_residual=score, signal_maturity="calibrated",
                     triggers=[])
                for index, score in enumerate(scores)]
    method = SimpleNamespace(id="method", evidence=evidence)
    return anomaly_patterns([method], "series", **settings)


@pytest.mark.parametrize(
    "rule,kind,scores,detection,direction",
    [
        ("nelson_rule_3", "residual_trend", [0, 1, 2, 3, 4, 5], 5, "increase"),
        ("nelson_rule_4", "systematic_oscillation", [0, 1] * 7, 13, "mixed"),
        ("nelson_rule_8", "mixture_pattern", [1.2, -1.2] * 4, 7, "mixed"),
    ],
)
def test_nelson_diagnostics_have_specific_semantics(rule, kind, scores,
                                                     detection, direction):
    patterns = patterns_for_scores(scores)
    pattern = next(pattern for pattern in patterns if pattern["rule"] == rule)
    assert pattern["kind"] == kind
    assert pattern["detection_index"] == detection
    assert pattern["direction"] == direction
    assert "location-shift" in pattern["description"]


def test_cusum_detects_accumulated_moderate_location_shift():
    patterns = patterns_for_scores([.8] * 20)
    pattern = next(pattern for pattern in patterns if pattern["rule"] == "cusum")
    assert pattern["direction"] == "increase"
    assert pattern["detection_index"] == 16
    assert pattern["peak_cusum"] == pytest.approx(6)
    assert pattern["detector_threshold"] == 5
    assert "location shift" in pattern["description"]


def test_moving_range_detects_short_term_variation_increase():
    patterns = patterns_for_scores([0, 4])
    pattern = next(pattern for pattern in patterns if pattern["rule"] == "moving_range")
    assert pattern["kind"] == "variation_shift"
    assert pattern["detection_index"] == 1
    assert pattern["peak_moving_range"] == 4
    assert "not process location" in pattern["description"]


def test_isolated_anomalies_do_not_form_second_order_pattern(request_factory):
    values = [100.0] * 70
    values[55] = values[60] = 150
    result = analyze(request_factory(values, season_length=7))
    assert len(result.observations) == 4
    assert not [pattern for pattern in result.anomaly_patterns
                if pattern["kind"] == "consecutive_run"]


def test_manual_resets_retrain_without_crossing_boundaries(request_factory):
    weekly = [0, 10, -5, 8, 2, -12, -8]
    variation = [.2, -.4, .6, -.3, .1]
    values = []
    for i in range(150):
        level = (100 + .3*i if i < 50 else
                 150 - .4*(i-50) if i < 100 else
                 105 * 1.01**(i-100))
        values.append(round(level + weekly[i % 7] + variation[i % 5], 4))
    unmarked = analyze(request_factory(values, season_length=7))
    assert len([e for e in unmarked.methods[0].evidence if e["triggers"]]) == 100
    assert unmarked.anomaly_patterns[0]["sample_count"] == 100

    marked_request = request_factory(values, season_length=7,
                                     reset_points=[50, "2026-04-11"])
    marked = analyze(marked_request)
    assert not marked.observations
    assert not marked.anomaly_patterns
    assert marked.methods[0].parameters["resolved_reset_positions"] == [50, 100]
    assert len(marked.methods[0].diagnostics["segments"]) == 3
    evidence_indices = {e["index"] for e in marked.methods[0].evidence}
    assert not evidence_indices.intersection(range(50, 57))
    assert not evidence_indices.intersection(range(100, 107))
    assert all(segment["status"] == "calibrated"
               for segment in marked.methods[0].diagnostics["segments"])


@pytest.mark.parametrize("points", [[0], [70], [-1], ["2026-09-01"], [10, "2026-01-11"]])
def test_invalid_manual_resets(request_factory, points):
    with pytest.raises(ValueError, match="reset"):
        analyze(request_factory(reset_points=points))


def test_timestamp_metadata_is_all_or_nothing():
    with pytest.raises(ValueError, match="timestamps require frequency"):
        Dataset(values=[1], timestamps=["2026-01-01T00:00:00Z"])
    with pytest.raises(ValueError, match="require timestamps"):
        Dataset(values=[1], frequency="1d")
    request = {"datasets": [{"values": [1, 2, 3]}],
               "context": {"as_of": "2026-01-01T00:00:00Z"}}
    with pytest.raises(ValueError, match="as_of requires timestamps"):
        analyze(request)


def test_constant_and_schema(request_factory):
    request = request_factory()
    result = analyze(request)
    assert result.status == "completed"
    assert not result.observations
    assert result.methods[0].diagnostics["held_out_mae"] == 0
    assert any("variance" in x for x in result.methods[0].limitations)
    validate(request, Request.model_json_schema())
    validate(result.model_dump(mode="json"), Result.model_json_schema())
    assert json.loads(result.model_dump_json())["status"] == "completed"


def test_spike_and_no_lookahead(request_factory):
    ordinary = request_factory()
    changed = copy.deepcopy(ordinary)
    changed["datasets"][0]["values"][55] = 150
    before, after = analyze(ordinary), analyze(changed)
    assert before.methods[0].evidence[:13] == after.methods[0].evidence[:13]
    signal = next(e for e in after.methods[0].evidence if e["index"] == 55)
    assert signal["expected"] == 100
    assert "point" in signal["triggers"]
    assert after.observations
    assert analyze(changed).methods[0].evidence == after.methods[0].evidence


def test_seasonality_shift_and_context(request_factory):
    y = [100 + [0, 10, -5, 8, 2, -12, -8][i % 7] + [0.2, -0.4, 0.6, -0.3, 0.1][i % 5] for i in range(90)]
    ordinary = analyze(request_factory(y, season_length=7))
    assert not ordinary.observations
    shifted = [v + (4 if i >= 60 else 0) for i, v in enumerate(y)]
    request = request_factory(shifted, season_length=7)
    result = analyze(request)
    assert any("point" in e["triggers"] for e in result.methods[0].evidence if 60 <= e["index"] < 67)
    request["context"] = {"known_events": ["Expected promotion at sample 60"]}
    contextual = analyze(request)
    assert contextual.methods[0].evidence == result.methods[0].evidence
    assert contextual.resolved_config["context"]["known_events"]


@pytest.mark.parametrize("kind,status", [("short", "insufficient_history"), ("missing", "inapplicable"), ("irregular", "inapplicable")])
def test_inapplicable(request_factory, kind, status):
    request = request_factory([1.] * 4 if kind == "short" else None)
    if kind == "missing":
        request["datasets"][0]["values"][2] = None
    if kind == "irregular":
        request["datasets"][0]["timestamps"][2] = "2026-01-03T01:00:00Z"
    assert analyze(request).status == status


def test_duplicate_sort_and_cutoff(request_factory):
    request = request_factory([1, 3, 5])
    ds = request["datasets"][0]
    ds["timestamps"][1] = ds["timestamps"][0]
    with pytest.raises(ValueError, match="duplicate"):
        analyze(request)
    request["config"]["duplicate_policy"] = "mean"
    request["context"] = {"as_of": ds["timestamps"][0]}
    times, values, quality = prepare(Request.model_validate(request))
    assert values == [2]
    assert quality["duplicate_count"] == 1


def test_weekly_cadence(request_factory):
    request = request_factory([1, 2, 3])
    request["datasets"][0]["frequency"] = "1w"
    request["datasets"][0]["timestamps"] = [
        "2026-01-01T00:00:00Z", "2026-01-08T00:00:00Z", "2026-01-15T00:00:00Z"]
    _, _, quality = prepare(Request.model_validate(request))
    assert quality["regular"] is True


def test_local_time():
    with pytest.raises(ValueError, match="timezone"):
        timestamp("2026-01-01T12:00:00")
    for value in ("2026-11-01T01:30:00", "2026-03-08T02:30:00"):
        with pytest.raises(ValueError, match="ambiguous"):
            timestamp(value, "America/Los_Angeles")
    assert timestamp("2026-01-01T12:00:00", "America/Los_Angeles").hour == 20


def test_failure_and_budget(request_factory, monkeypatch):
    import anomalyzer.recipes as recipes
    original = recipes.expected_value
    def failing(values, index, season_length):
        if index == 45:
            raise RuntimeError("reference failure")
        return original(values, index, season_length)
    monkeypatch.setattr(recipes, "expected_value", failing)
    result = analyze(request_factory())
    assert result.status == "partial"
    assert "reference failure" in result.methods[0].error
    assert result.methods[0].evidence[-1]["index"] == 44
    assert analyze(request_factory(max_runtime_seconds=1e-12)).stop_reason == "runtime_budget"


@pytest.mark.parametrize("change", [{"unknown": 1}, {"methods": ["ses"]}, {"cusum_k": 0}, {"cusum_h": 0}, {"moving_range_threshold": 0}, {"alpha": 0.2}, {"seed": 0}, {"recipe": "baseline-v1"}, {"season_length": 0}, {"training_size": True}])
def test_invalid_config(request_factory, change):
    with pytest.raises(ValueError):
        analyze(request_factory(**change))


def test_invalid_values(request_factory):
    for value in (float("nan"), float("inf"), True, "10"):
        with pytest.raises(ValueError):
            analyze(request_factory([value]))


def test_internal_evaluation(request_factory):
    values = [100.0] * 70
    values[60:] = [102.0] * 10
    result = replay(request_factory(values, season_length=30, trend="none"))
    assert len(result["methods"]) == 1
    assert result["detection_precision"] is None
    assert "pattern_counts" in result
    assert "first_detection_by_rule" in result


def test_checked_in_schemas():
    for name, contract in (("request", Request), ("result", Result)):
        schema = json.loads((Path(__file__).parents[1] / "schemas" / f"{name}.schema.json").read_text())
        schema.pop("$schema")
        assert schema == contract.model_json_schema()
