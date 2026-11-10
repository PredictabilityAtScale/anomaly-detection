"""Offline installed-wheel smoke check; only uses the public forecast API."""
import json
import math
import random

from anomalyzer import ForecastDataset, ForecastRequest, forecast_series, forecast_with_model, select_forecast


def main():
    values = [10 + .5 * i for i in range(86)]
    request = ForecastRequest(dataset=ForecastDataset(values=values))
    result = forecast_series(request.model_dump_json())
    assert result.status == "completed", result.reason
    assert result.model.trend_kind == "linear"
    assert all(math.isclose(v, 53 + .5 * i) for i, v in enumerate(result.predicted))
    assert result.predicted[:7] == forecast_series(values, {"horizon": 7}).predicted
    assert len(result.expected) == 86 and len(result.trend) == 116
    assert forecast_series([0.] * 8).predicted == [0.] * 30
    assert forecast_series([10.] * 7).reason == "insufficient_history"
    rng = random.Random(42)
    stationary = [100 + rng.uniform(-10, 10) for _ in range(112)]
    config = {"baseline": "recent-level-v1", "trend": "none", "outlier_handling": "include", "historical_anomalies": {}}
    level = forecast_series(stationary, config)
    assert level.status == "completed", level.reason
    assert level.model.level_baseline["kind"] == "simple_exponential_smoothing"
    assert level.model.historical_level_baseline["kind"] == "simple_exponential_smoothing"
    assert level.expected == forecast_series(stationary + [500.], config).expected[:-1]
    assert level.historical_anomalies.resolved_settings.forecast_baseline == "recent-level-v1"
    local = forecast_with_model(values, {"id": "local", "method": "local_trend"}, {"horizon": 14})
    assert local.status == "completed", local.reason
    assert all(math.isclose(v, 53 + .5*i) for i,v in enumerate(local.predicted))
    selected = select_forecast(values, {"horizon": 14, "max_runtime_seconds": 2.5})
    assert selected.status == "completed", selected.reason
    assert len(selected.scores) == 15 and len(selected.forecast.predicted) == 14
    assert all(math.isclose(v, 53 + .5*i) for i,v in enumerate(selected.forecast.predicted))
    assert "expected" not in selected.forecast.model_dump()
    print(json.dumps({"forecast": "passed", "engine_version": result.engine_version,
                      "model_selection": "passed", "selected_candidate": selected.selected_candidate.id,
                      "request_fingerprint": result.request_fingerprint}))


if __name__ == "__main__":
    main()
