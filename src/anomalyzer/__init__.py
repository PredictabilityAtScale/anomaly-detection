"""Public, local-only analysis API."""
from .contracts import Request, Result
from .recipes import analyze

__all__ = ["Request", "Result", "analyze"]
__version__ = "0.1.0"
