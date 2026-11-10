"""Public, local-only analysis API."""
from ._version import __version__
from .forecast_contracts import (
    ForecastDataset, ForecastSeasonality, ForecastSettings, ForecastRequest,
    ForecastCounts, ForecastModel, ForecastResult,
)
from .forecast import forecast_series
from .contracts import DataPolicy, DatasetV11, SampleRevision, Request, RequestV11, Result, ResultV11
from .agent import analyze_relationships, analyze_series, get_case, replay_policy
from .recipes import analyze, analyze_dataset
from .distribution_contracts import (
    DistributionSample, DistributionPopulation, DistributionSettings,
    DistributionRequest, DistributionResult, DistributionMonitorRequest,
    DistributionMonitorResult,
)
from .distributions import compare_distributions, monitor_distributions
from .seasonal_distributions import (
    SeasonalReferencePolicy, SeasonalDistributionRequest, SeasonalDistributionResult,
    compare_seasonal_distributions,
)

__all__ = [
    "ForecastDataset", "ForecastSeasonality", "ForecastSettings", "ForecastRequest",
    "ForecastCounts", "ForecastModel", "ForecastResult", "forecast_series",
    "DataPolicy", "DatasetV11", "SampleRevision",
    "Request", "RequestV11", "Result", "ResultV11", "analyze",
    "analyze_dataset", "analyze_series", "analyze_relationships", "get_case",
    "replay_policy",
    "DistributionSample", "DistributionPopulation", "DistributionSettings",
    "DistributionRequest", "DistributionResult", "DistributionMonitorRequest",
    "DistributionMonitorResult", "compare_distributions", "monitor_distributions",
    "SeasonalReferencePolicy", "SeasonalDistributionRequest", "SeasonalDistributionResult",
    "compare_seasonal_distributions",
]
