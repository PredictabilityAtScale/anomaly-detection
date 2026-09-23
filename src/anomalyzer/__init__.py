"""Public, local-only analysis API."""
from .contracts import Request, RequestV11, Result, ResultV11
from .agent import analyze_series, get_case, replay_policy
from .orchestrator import analyze_relationships
from .recipes import analyze, analyze_dataset

__all__ = [
    "Request", "RequestV11", "Result", "ResultV11", "analyze",
    "analyze_dataset", "analyze_series", "analyze_relationships", "get_case",
    "replay_policy",
]
__version__ = "0.1.0"
