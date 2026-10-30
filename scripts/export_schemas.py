"""Regenerate public schemas from the validated Python contracts."""
import json
from pathlib import Path
from anomalyzer.contracts import Request, RequestV11, Result, ResultV11
from anomalyzer.distribution_contracts import (
    DistributionRequest, DistributionResult, DistributionMonitorRequest, DistributionMonitorResult,
)
from anomalyzer.seasonal_distributions import SeasonalDistributionRequest, SeasonalDistributionResult

directory = Path(__file__).resolve().parents[1] / "schemas"
directory.mkdir(exist_ok=True)
for name, contract in (("request", Request), ("result", Result)):
    schema = contract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (directory / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
for name, contract in (("request-1.1", RequestV11), ("result-1.1", ResultV11)):
    schema = contract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (directory / f"{name}.schema.json").write_text(
        json.dumps(schema, indent=2) + "\n", encoding="utf-8")
for name, contract in (("distribution-request", DistributionRequest),
                       ("distribution-result", DistributionResult),
                       ("distribution-monitor-request", DistributionMonitorRequest),
                       ("distribution-monitor-result", DistributionMonitorResult),
                       ("seasonal-distribution-request", SeasonalDistributionRequest),
                       ("seasonal-distribution-result", SeasonalDistributionResult)):
    schema = contract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (directory / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
