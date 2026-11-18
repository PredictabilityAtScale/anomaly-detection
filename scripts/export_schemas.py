"""Regenerate public schemas from the validated Python contracts."""
import json
from pathlib import Path
from anomalyzer.contracts import Request, RequestV11, Result, ResultV11
from anomalyzer.distribution_contracts import (
    DistributionRequest, DistributionResult, DistributionMonitorRequest, DistributionMonitorResult,
)
from anomalyzer.seasonal_distributions import SeasonalDistributionRequest, SeasonalDistributionResult
from anomalyzer.forecast_contracts import ForecastRequest, ForecastResult
from anomalyzer.forecast_selection_contracts import (
    ModelForecastRequest, ModelForecastResult, ForecastSelectionRequest, ForecastSelectionResult,
)

directory = Path(__file__).resolve().parents[1] / "schemas"
directory.mkdir(exist_ok=True)


def write_schema(name, schema):
    path = directory / f"{name}.schema.json"
    content = json.dumps(schema, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")


for name, contract in (("request", Request), ("result", Result)):
    schema = contract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    write_schema(name, schema)
for name, contract in (("request-1.1", RequestV11), ("result-1.1", ResultV11)):
    schema = contract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    write_schema(name, schema)
for name, contract in (("distribution-request", DistributionRequest),
                       ("forecast-request", ForecastRequest),
                       ("forecast-result", ForecastResult),
                       ("forecast-model-request", ModelForecastRequest),
                       ("forecast-model-result", ModelForecastResult),
                       ("forecast-selection-request", ForecastSelectionRequest),
                       ("forecast-selection-result", ForecastSelectionResult),
                       ("distribution-result", DistributionResult),
                       ("distribution-monitor-request", DistributionMonitorRequest),
                       ("distribution-monitor-result", DistributionMonitorResult),
                       ("seasonal-distribution-request", SeasonalDistributionRequest),
                       ("seasonal-distribution-result", SeasonalDistributionResult)):
    schema = contract.model_json_schema()
    dialect = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    schema = {**dialect, **schema} if name in ("forecast-request", "forecast-result") else {**schema, **dialect}
    write_schema(name, schema)
