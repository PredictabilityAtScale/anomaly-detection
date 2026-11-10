"""Offline installed artifact check using only the supported public API."""
import json
import time

from anomalyzer import HistoricalAnomalySettings, __version__, forecast_series


def main():
    started = time.perf_counter()
    for interval, window, horizon, k in [("hour",1344,168,768), ("day",56,90,56),
                                        ("week",52,26,52), ("month",36,24,36)]:
        values = [100 + i % 7 for i in range(6000)]
        values[k + 20] = 10000
        config = dict(max_training_points=window, max_inference_points=768, horizon=horizon,
                      historical_anomalies=HistoricalAnomalySettings().model_dump())
        before = time.perf_counter()
        result = forecast_series({"values": values, "interval": interval}, config)
        assert result.status == "completed", result.reason
        evidence = result.historical_anomalies
        assert evidence.points[k + 20].triggers == ["point"]
        assert evidence.points[k + 14].maturity == "calibrated"
        assert evidence.points[k - 1].expected is None
        assert len(evidence.points) == 6000 and len(result.predicted) == horizon
        payload = result.model_dump_json()
        assert len(payload.encode()) < 6 * 1024 * 1024  # synchronous Lambda response limit
        assert time.perf_counter() - before < 4  # includes public result serialization
    values = [100.] * 80 + [300.] * 12
    base = forecast_series(values, {"historical_anomalies": {}}).historical_anomalies
    prefix = forecast_series(values[:85], {"historical_anomalies": {}}).historical_anomalies
    assert prefix.points == base.points[:85]
    assert prefix.patterns == [p for p in base.patterns if p.detection_index < 85]
    assert any(p.rule == "adjacent_point_anomalies" for p in base.patterns)
    assert forecast_series(values, {"historical_anomalies": {}, "max_runtime_seconds": 1e-12}).reason == "budget_exceeded"
    print(json.dumps(dict(historical_anomalies="passed", engine_version=__version__,
                          seconds=time.perf_counter() - started)))


if __name__ == "__main__":
    main()
