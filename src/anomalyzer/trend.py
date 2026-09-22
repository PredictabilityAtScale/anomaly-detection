"""Training-only trend fitting with additive seasonal offsets; no dependencies."""
import math
from dataclasses import dataclass

from .robust import extreme_indices, huber_weights


@dataclass
class Trend:
    kind: str = "none"
    coefficient: float = 0.0
    rate: float = 0.0
    origin: int = 0

    def change(self, start: int, end: int) -> float:
        if self.kind == "linear":
            return self.coefficient * (end - start)
        if self.kind == "exponential":
            return (self.coefficient * math.exp(self.rate * (start - self.origin))
                    * math.expm1(self.rate * (end - start)))
        return 0.0


def _robust_phase_fit(ys, xs, phases, season, scale_floor):
    """Fit seasonal intercepts and one fixed-form regressor with Huber IRLS."""
    weights = [1.0] * len(ys)
    coefficient = 0.0
    intercepts = [0.0] * season
    for _ in range(6):
        for phase in range(season):
            members = [index for index, value in enumerate(phases)
                       if value == phase]
            total = math.fsum(weights[index] for index in members)
            if total:
                intercepts[phase] = math.fsum(
                    weights[index] * (ys[index] - (
                        coefficient * xs[index] if xs is not None else 0.0))
                    for index in members) / total
        if xs is not None:
            centered = []
            for phase in range(season):
                members = [index for index, value in enumerate(phases)
                           if value == phase]
                total = math.fsum(weights[index] for index in members)
                if not total:
                    continue
                xmean = math.fsum(weights[index] * xs[index]
                                  for index in members) / total
                ymean = math.fsum(weights[index] * ys[index]
                                  for index in members) / total
                centered.extend((index, xs[index] - xmean,
                                 ys[index] - ymean) for index in members)
            denominator = math.fsum(weights[index] * x * x
                                    for index, x, _ in centered)
            coefficient = (math.fsum(weights[index] * x * y
                                     for index, x, y in centered) / denominator
                           if denominator else 0.0)
        residuals = [ys[index] - intercepts[phase]
                     - (coefficient * xs[index] if xs is not None else 0.0)
                     for index, phase in enumerate(phases)]
        weights = huber_weights(residuals, scale_floor)

    for phase in range(season):
        members = [index for index, value in enumerate(phases) if value == phase]
        total = math.fsum(weights[index] for index in members)
        if total:
            intercepts[phase] = math.fsum(
                weights[index] * (ys[index] - (
                    coefficient * xs[index] if xs is not None else 0.0))
                for index in members) / total
    residuals = [ys[index] - intercepts[phase]
                 - (coefficient * xs[index] if xs is not None else 0.0)
                 for index, phase in enumerate(phases)]
    return coefficient, intercepts, residuals, weights


def _fit_ordinary(values, season, mode, scale_floor, check_budget):
    """Preserve the original least-squares selection and fit."""
    n = len(values)
    diagnostics = {"requested": mode, "selected": "none", "fit_samples": n,
                   "minimum_samples": max(8, 4 * season),
                   "minimum_error_reduction": 0.5,
                   "rate_bounds": [-0.1, 0.1],
                   "outlier_handling": "include",
                   "fit_objective": "sum_of_squares",
                   "excluded_positions": []}
    if mode == "none" or n < max(8, 4 * season):
        diagnostics["reason"] = ("disabled" if mode == "none" else
                                 "insufficient training for trend; seasonal fallback")
        return Trend(), diagnostics
    start = max(0, n - max(256, 4 * season))
    ys = values[start:]
    origin = n - 1
    groups = [[] for _ in range(season)]
    for index in range(len(ys)):
        groups[(start + index) % season].append(index)
    ymeans = [math.fsum(ys[index] for index in group) / len(group)
              for group in groups]
    centered_y = [ys[index] - ymeans[(start + index) % season]
                  for index in range(len(ys))]
    null_error = math.fsum(value * value for value in centered_y)
    floor = max(scale_floor**2 * len(ys), 1e-24)

    def fit(rate=None):
        check_budget()
        xs = [(start + index - origin) if rate is None else
              math.exp(rate * (start + index - origin) / len(ys))
              for index in range(len(ys))]
        means = [math.fsum(xs[index] for index in group) / len(group)
                 for group in groups]
        centered_x = [xs[index] - means[(start + index) % season]
                      for index in range(len(ys))]
        denominator = math.fsum(value * value for value in centered_x)
        coefficient = (math.fsum(x * y for x, y in zip(centered_x, centered_y))
                       / denominator if denominator else 0.0)
        error = math.fsum((y - coefficient * x) ** 2
                          for x, y in zip(centered_x, centered_y))
        return error, coefficient

    linear_error, slope = fit()
    selected = Trend("linear", slope, origin=origin)
    if mode == "auto" and (null_error <= floor or
                           linear_error >= 0.5 * max(null_error, floor)):
        selected = Trend()
    diagnostics.update(fit_window=[start, n - 1], seasonal_sse=null_error,
                       linear_sse=linear_error)
    if mode in ("auto", "exponential"):
        bound = min(20.0, 0.1 * len(ys))
        diagnostics["rate_bounds"] = [-bound / len(ys), bound / len(ys)]
        grid = [-bound + 2 * bound * index / 80 for index in range(81)]
        candidates = [(fit(rate)[0], index) for index, rate in enumerate(grid)
                      if abs(rate) > 1e-10]
        _, best = min(candidates)
        lo, hi = grid[max(0, best - 1)], grid[min(80, best + 1)]
        for _ in range(55):
            a, b = lo + (hi - lo) / 3, hi - (hi - lo) / 3
            if fit(a)[0] < fit(b)[0]:
                hi = b
            else:
                lo = a
        rate = (lo + hi) / 2
        error, amplitude = fit(rate)
        diagnostics["exponential_sse"] = error
        reference = linear_error if selected.kind == "linear" else null_error
        if (amplitude > 0 and abs(rate) > 1e-5
                and (mode == "exponential"
                     or error < 0.5 * max(reference, floor))):
            selected = Trend("exponential", amplitude, rate / len(ys), origin)
        elif mode == "exponential":
            selected = Trend()
            diagnostics["reason"] = "no supported positive-amplitude exponential fit; seasonal fallback"
    diagnostics.update(selected=selected.kind, coefficient=selected.coefficient,
                       rate=selected.rate, origin=selected.origin)
    return selected, diagnostics


def fit_trend(values, season, mode="auto", scale_floor=1e-8,
              check_budget=lambda: None, outlier_handling="robust"):
    """Fit trend normally, then robustly screen and refit extreme contamination."""
    ordinary, ordinary_diagnostics = _fit_ordinary(
        values, season, mode, scale_floor, check_budget)
    if outlier_handling == "include" or len(values) < max(8, 4 * season):
        return ordinary, ordinary_diagnostics

    n = len(values)
    start = max(0, n - max(256, 4 * season))
    ys = values[start:]
    phases = [(start + index) % season for index in range(len(ys))]
    if ordinary.kind == "linear":
        xs = [start + index - ordinary.origin for index in range(len(ys))]
    elif ordinary.kind == "exponential":
        xs = [math.exp(ordinary.rate * (start + index - ordinary.origin))
              for index in range(len(ys))]
    else:
        xs = None
    robust_coefficient, intercepts, residuals, weights = _robust_phase_fit(
        ys, xs, phases, season, scale_floor)
    excluded, robust_diagnostics = extreme_indices(residuals, scale_floor)
    absolute_excluded = [start + index for index in excluded]
    selected = ordinary
    selected_diagnostics = ordinary_diagnostics
    if excluded:
        cleaned = list(values)
        for index in excluded:
            phase = phases[index]
            fitted = intercepts[phase] + (
                robust_coefficient * xs[index] if xs is not None else 0.0)
            cleaned[start + index] = fitted
        selected, selected_diagnostics = _fit_ordinary(
            cleaned, season, mode, scale_floor, check_budget)

    selected_diagnostics.update(
        outlier_handling="robust",
        fit_objective="two_pass_huber_screen_then_least_squares",
        excluded_positions=absolute_excluded,
        robust_residuals=robust_diagnostics,
        downweighted_count=sum(weight < 1.0 for weight in weights))
    return selected, selected_diagnostics
