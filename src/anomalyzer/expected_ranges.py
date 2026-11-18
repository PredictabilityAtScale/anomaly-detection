"""Finite-sample empirical ranges over a separate chronological error window."""

from dataclasses import dataclass, field
from math import ceil


@dataclass
class EmpiricalRange:
    coverage: float
    minimum_dates: int
    minimum_weeks: int
    errors: list[float] = field(default_factory=list)
    dates: set = field(default_factory=set)
    weeks: set = field(default_factory=set)
    frozen: dict | None = None

    def admit(self, residual, day, week, index, timestamp, minimum_samples):
        if self.frozen is not None:
            return
        self.errors.append(abs(residual))
        self.dates.add(day)
        self.weeks.add(week)
        rank = ceil((len(self.errors) + 1) * self.coverage)
        if (rank > len(self.errors) or len(self.errors) < minimum_samples
                or len(self.dates) < self.minimum_dates or len(self.weeks) < self.minimum_weeks):
            return
        self.frozen = dict(coverage_target=self.coverage, radius=sorted(self.errors)[rank-1],
                           rank=rank, sample_count=len(self.errors), target_date_count=len(self.dates),
                           target_week_count=len(self.weeks), cutoff=timestamp, effective_from_index=index+1,
                           method="empirical_absolute_prediction_error", screened_errors=False)

    def bounds(self, expected):
        if self.frozen is None:
            return dict(status="insufficient_history", coverage_target=self.coverage, sample_count=len(self.errors))
        radius = self.frozen["radius"]
        return dict(status="available", coverage_target=self.coverage,
                    lower=expected-radius, upper=expected+radius, sample_count=self.frozen["sample_count"],
                    cutoff=self.frozen["cutoff"], effective_from_index=self.frozen["effective_from_index"])
