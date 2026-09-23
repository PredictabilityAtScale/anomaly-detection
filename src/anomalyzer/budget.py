"""Request-scoped cooperative runtime budget."""
import time


class RuntimeBudget:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self.started = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed)

    def check(self):
        if self.elapsed >= self.seconds:
            raise TimeoutError("runtime budget exhausted")
