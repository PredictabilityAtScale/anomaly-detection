"""Evaluation must use chronological observations and disclose weak cases."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "examples/forecasting"
spec = importlib.util.spec_from_file_location("fixtures", DIRECTORY / "fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
sys.modules["fixtures"] = fixtures
spec = importlib.util.spec_from_file_location("forecast_evaluate", DIRECTORY / "evaluate.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_evaluation_passes_only_observed_prefixes_to_forecast(monkeypatch):
    seen = []

    def forecast(history, config):
        seen.append(history.copy())
        return SimpleNamespace(status="completed", predicted=[history[-1]] * config["horizon"],
                               model=SimpleNamespace(trend_kind="none", season_length=1))

    monkeypatch.setattr(evaluation, "forecast_series", forecast)
    values = [float(i) for i in range(30)]
    result = evaluation.evaluate_case({"name": "synthetic", "values": values,
        "origins": [10, 20], "horizon": 5, "baseline_period": 1, "config": {}})
    assert seen == [values[:10], values[:20]] * 4
    for row in result:
        assert row["mae"] == row["baseline_mae"] == 3
        assert all(fold["training_window"][1] < fold["holdout_window"][0] for fold in row["folds"])


def test_committed_anonymous_errors_reproduce_and_disclose_regime_weakness():
    report = json.loads((ROOT / "docs/forecast-evaluation.json").read_text())
    assert report["source"] == "anonymous deterministic synthetic fixtures"
    assert report["fixture_hash_encoding"] == "UTF-8 with LF line endings"
    assert report["fixture_sha256"] == hashlib.sha256((DIRECTORY / "fixtures.py").read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    actual = [row for case in fixtures.synthetic_cases() for row in evaluation.evaluate_case(case)]
    assert len(actual) == len(report["results"]) == len(list(fixtures.synthetic_cases())) * 4
    for row, saved in zip(actual, report["results"]):
        assert row["case"] == saved["case"]
        assert row["outlier_handling"] == saved["outlier_handling"]
        assert row["baseline_policy"] == saved["baseline_policy"]
        assert row["one_step_mae"] == pytest.approx(saved["one_step_mae"])
        assert row["evaluated_points"] == saved["evaluated_points"]
        assert all(fold["status"] == "completed" for fold in row["folds"])
        assert row["mae"] == pytest.approx(saved["mae"], abs=1e-7)
        assert row["wape"] == pytest.approx(saved["wape"], abs=1e-7) if saved["wape"] is not None else row["wape"] is None
    shifted = [row for row in actual if row["case"] == "sustained_shift"]
    assert all(row["mae"] > row["baseline_mae"] for row in shifted)


def test_private_evaluation_refuses_public_output_before_reading_data():
    result = subprocess.run([sys.executable, str(DIRECTORY / "evaluate.py"),
        "--private-evidence", "does-not-exist.json", "--output", "docs/must-not-exist-private.json"],
        cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 2
    assert "ignored .tmp directory" in result.stderr
    assert not (ROOT / "docs/must-not-exist-private.json").exists()


def test_nested_evaluation_retains_losses_and_declared_model_regressions():
    results = json.loads((ROOT / "docs/forecast-evaluation.json").read_text())["results"]
    def row(case, policy, handling="include"):
        return next(r for r in results if r["case"] == case and r["baseline_policy"] == policy and r["outlier_handling"] == handling)
    for name in ("stationary_seed_42", "noisy_endpoint_spikes"):
        assert row(name, "recent-level-v1")["mae"] < row(name, "legacy")["mae"]
    for name in ("stationary_seed_123", "noisy_recent_step"):
        assert row(name, "recent-level-v1")["mae"] > row(name, "legacy")["mae"]
    for name in ("flat", "zero", "linear_up", "linear_down_signed", "exponential", "weekly", "hourly_daily", "monthly_annual", "daily_annual_positional", "random_walk"):
        for handling in ("include", "robust"):
            assert row(name, "recent-level-v1", handling)["mae"] == row(name, "legacy", handling)["mae"]
