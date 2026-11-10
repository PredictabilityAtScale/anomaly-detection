"""Public, local-only analysis API."""
from ._version import __version__
from .forecast_contracts import (
    ForecastDataset, ForecastSeasonality, ForecastSettings, ForecastRequest,
    ForecastCounts, ForecastModel, ForecastResult,
    HistoricalAnomalySettings, HistoricalAnomalyPoint, HistoricalPattern,
    HistoricalReferenceAdjustment, HistoricalCalibration, HistoricalAnomalies,
    HistoricalDetectorSettings,
)
from .forecast import forecast_series
from .forecast_selection_contracts import (
    ForecastCandidate, ModelForecastSettings, ForecastSelectionSettings,
    ModelForecastRequest, ModelForecastResult, ModelForecastInfo,
    ForecastSelectionRequest, ForecastSelectionResult, ForecastCandidateScore,
    ForecastFoldScore, default_forecast_candidates,
)
from .forecast_selection import forecast_with_model, select_forecast
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
    "HistoricalAnomalySettings", "HistoricalAnomalyPoint", "HistoricalPattern",
    "HistoricalReferenceAdjustment", "HistoricalCalibration", "HistoricalAnomalies",
    "HistoricalDetectorSettings",
    "ForecastDataset", "ForecastSeasonality", "ForecastSettings", "ForecastRequest",
    "ForecastCounts", "ForecastModel", "ForecastResult", "forecast_series",
    "ForecastCandidate", "ModelForecastSettings", "ForecastSelectionSettings",
    "ModelForecastRequest", "ModelForecastResult", "ModelForecastInfo",
    "ForecastSelectionRequest", "ForecastSelectionResult", "ForecastCandidateScore",
    "ForecastFoldScore", "default_forecast_candidates", "forecast_with_model", "select_forecast",
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
