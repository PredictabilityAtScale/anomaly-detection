import math

import pytest

from anomalyzer import analyze
from anomalyzer.trend import fit_trend


@pytest.mark.parametrize("kind,rate", [("linear", 0.6), ("linear", -0.6),
                                      ("exponential", 0.012), ("exponential", -0.012)])
def test_trend_and_anomalies(kind, rate):
    seasonal = [0, 10, -5, 8, 2, -12, -8]
    values = [(100 + rate*i if kind == "linear" else 100*math.exp(rate*i))
              + seasonal[i%7] for i in range(90)]
    settings = {"season_length": 7}
    clean = analyze(values, settings)
    assert clean.status == "completed"
    assert clean.methods[0].diagnostics["trend"]["selected"] == kind
    assert not clean.observations
    for e in clean.methods[0].evidence:
        if e["index"] >= 28:
            assert e["expected"] == pytest.approx(e["observed"], abs=1e-6)
    for departure in (-40, 40):
        changed = values.copy()
        changed[65] += departure
        result = analyze(changed, settings)
        evidence = result.methods[0].evidence
        assert [e for e in evidence if e["index"]<65] == [e for e in clean.methods[0].evidence if e["index"]<65]
        assert {65} == {e["index"] for e in evidence if e["triggers"]}
        signal = next(e for e in evidence if e["index"] == 65)
        echo = next(e for e in evidence if e["index"] == 72)
        assert signal["excluded_from_model"] is True
        assert echo["expected"] == pytest.approx(echo["observed"], abs=1e-6)


def test_frozen_fit_and_legacy_mode():
    values = [100*1.012**i for i in range(90)]
    before = analyze(values, {"season_length": 1})
    after = analyze(values[:50]+[1000]*40, {"season_length": 1})
    assert before.methods[0].diagnostics["trend"] == after.methods[0].diagnostics["trend"]
    assert before.methods[0].evidence[:49] == after.methods[0].evidence[:49]
    legacy = analyze(values, {"season_length": 1, "trend": "none",
                              "outlier_handling": "include"})
    assert legacy.methods[0].id == "seasonal_naive"
    assert all(e["expected"] == values[e["index"]-1] for e in legacy.methods[0].evidence)
    assert legacy.observations


def test_short_history_constant_and_signed_linear():
    model, diagnostic = fit_trend([1,2,3], 1)
    assert model.kind == "none"
    assert "insufficient" in diagnostic["reason"]
    assert fit_trend([0]*28, 1)[0].kind == "none"
    assert fit_trend([-50+i for i in range(28)],1)[0].kind == "linear"


def test_explicit_modes_and_validation():
    values = [100*1.012**i for i in range(90)]
    assert analyze(values, {"trend":"linear"}).methods[0].diagnostics["trend"]["selected"] == "linear"
    assert analyze(values, {"trend":"exponential"}).methods[0].diagnostics["trend"]["selected"] == "exponential"
    with pytest.raises(ValueError):
        analyze(values, {"trend":"quadratic"})


def test_robust_training_fit_and_calibration_exclusions():
    seasonal = [0, 10, -5, 8, 2, -12, -8]
    values = [100 + .5 * index + seasonal[index % 7]
              for index in range(90)]
    contaminated = values.copy()
    contaminated[20] += 200
    robust = analyze(contaminated, {"season_length": 7})
    included = analyze(contaminated, {"season_length": 7,
                                      "outlier_handling": "include"})
    assert robust.methods[0].diagnostics["trend"]["excluded_positions"] == [20]
    assert robust.methods[0].diagnostics["trend"]["selected"] == "linear"
    assert robust.methods[0].diagnostics["trend"]["coefficient"] == pytest.approx(.5, abs=.01)
    assert included.methods[0].diagnostics["trend"]["selected"] == "none"

    calibration_spike = values.copy()
    calibration_spike[35] += 50
    protected = analyze(calibration_spike, {"season_length": 7})
    unprotected = analyze(calibration_spike, {"season_length": 7,
                                              "outlier_handling": "include"})
    diagnostics = protected.methods[0].diagnostics
    assert diagnostics["outlier_handling"]["calibration_excluded_positions"] == [35]
    assert diagnostics["calibration_scale"] < unprotected.methods[0].diagnostics[
        "calibration_scale"]
    echo = next(e for e in protected.methods[0].evidence if e["index"] == 42)
    assert echo["residual"] == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("handling", ["robust", "include"])
def test_auto_exponential_requires_chronological_support(handling):
    # A late ramp fits an exponential in-sample, without sustained compound
    # growth. This anonymous example also caused runaway historical references.
    values = [100 + 7 * (i % 5) + 60 * max(0, i - 35) for i in range(56)]
    explicit, _ = fit_trend(values, 1, "exponential", outlier_handling=handling)
    assert explicit.kind == "exponential"
    automatic, diagnostics = fit_trend(values, 1, outlier_handling=handling)
    assert automatic.kind != "exponential"
    validation = diagnostics["exponential_validation"]
    assert validation["status"] == "unsupported"
    assert validation["fold_win_fraction"] < 2 / 3
    assert [fold["holdout_window"] for fold in validation["folds"]] == [
        [35, 41], [42, 48], [49, 55]]
    assert all(fold["training_window"][1] < fold["holdout_window"][0]
               for fold in validation["folds"])


@pytest.mark.parametrize("handling", ["robust", "include"])
@pytest.mark.parametrize("rate", [-.012, .012])
def test_chronological_confirmation_preserves_compound_seasonal_growth(handling, rate):
    seasonal = [0, 10, -5, 8, 2, -12, -8]
    values = [100 * math.exp(rate * i) + seasonal[i % 7] for i in range(28)]
    model, diagnostics = fit_trend(values, 7, outlier_handling=handling)
    assert model.kind == "exponential"
    assert model.rate == pytest.approx(rate, abs=1e-8)
    validation = diagnostics["exponential_validation"]
    assert validation["status"] == "supported"
    assert [fold["holdout_window"] for fold in validation["folds"]] == [
        [14, 20], [21, 27]]


def test_auto_exponential_without_training_holdouts_retains_simpler_trend():
    values = [100 * math.exp(.05 * i) for i in range(14)]
    model, diagnostics = fit_trend(values, 1)
    assert model.kind == "linear"
    assert diagnostics["exponential_validation"]["folds"] == []
    assert "insufficient chronological" in diagnostics["reason"]
    explicit, diagnostics = fit_trend(values, 1, "exponential")
    assert explicit.kind == "exponential"
    assert "exponential_validation" not in diagnostics


def test_exponential_confirmation_uses_bounded_training_suffix():
    values = [100 * math.exp(.012 * i) for i in range(300)]
    model, diagnostics = fit_trend(values, 1)
    assert model.kind == "exponential"
    assert diagnostics["fit_window"] == [44, 299]
    validation = diagnostics["exponential_validation"]
    assert validation["status"] == "supported"
    assert all(fold["training_window"][0] == 44 for fold in validation["folds"])
    assert validation["folds"][-1]["holdout_window"][1] == 299
