"""Regenerate the public forecast and historical-anomalies JSON schemas."""
import json
from pathlib import Path

from anomalyzer import ForecastRequest, ForecastResult, HistoricalAnomalySettings, HistoricalAnomalies

ROOT = Path(__file__).resolve().parents[1]

for name, model in [
    ("forecast-request", ForecastRequest), ("forecast-result", ForecastResult),
    ("historical-anomalies-request", HistoricalAnomalySettings),
    ("historical-anomalies-result", HistoricalAnomalies),
]:
    (ROOT / "schemas" / f"{name}.schema.json").write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema", **model.model_json_schema(),
    }, indent=2) + "\n", encoding="utf-8")
