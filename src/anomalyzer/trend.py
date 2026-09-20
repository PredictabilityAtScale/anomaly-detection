"""Training-only trend fitting with additive seasonal offsets; no dependencies."""
import math
from dataclasses import dataclass


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


def fit_trend(values, season, mode="auto", scale_floor=1e-8, check_budget=lambda: None):
    """Fit y = seasonal intercept + slope*t or amplitude*exp(rate*t).

    Select complexity conservatively by requiring a 50% reduction in residual
    sum of squares. Exponential rate is bounded to +/-10% log change per sample.
    Inputs must be exclusively the completed training window.
    """
    n = len(values)
    diagnostics = {"requested": mode, "selected": "none", "fit_samples": n,
                   "minimum_samples": max(8, 4 * season),
                   "minimum_error_reduction": 0.5, "rate_bounds": [-0.1, 0.1]}
    if mode == "none" or n < max(8, 4 * season):
        diagnostics["reason"] = "disabled" if mode == "none" else "insufficient training for trend; seasonal fallback"
        return Trend(), diagnostics
    # Bound fitting work and exponential arguments on very long training windows.
    start = max(0, n - max(256, 4 * season))
    ys = values[start:]
    origin = n - 1
    groups = [[] for _ in range(season)]
    for j in range(len(ys)):
        groups[(start + j) % season].append(j)
    ymeans = [math.fsum(ys[j] for j in group) / len(group) for group in groups]
    centered_y = [ys[j] - ymeans[(start + j) % season] for j in range(len(ys))]
    null_error = math.fsum(y*y for y in centered_y)
    floor = max(scale_floor**2 * len(ys), 1e-24)

    def fit(rate=None):
        check_budget()
        xs = [(start+j-origin) if rate is None else math.exp(rate*(start+j-origin)/len(ys)) for j in range(len(ys))]
        means = [math.fsum(xs[j] for j in group) / len(group) for group in groups]
        centered_x = [xs[j]-means[(start+j) % season] for j in range(len(ys))]
        denominator = math.fsum(x*x for x in centered_x)
        coefficient = math.fsum(x*y for x,y in zip(centered_x, centered_y))/denominator if denominator else 0.0
        error = math.fsum((y-coefficient*x)**2 for x,y in zip(centered_x, centered_y))
        return error, coefficient

    linear_error, slope = fit()
    selected = Trend("linear", slope, origin=origin)
    if mode == "auto" and (null_error <= floor or linear_error >= 0.5 * max(null_error, floor)):
        selected = Trend()
    diagnostics.update(fit_window=[start,n-1], seasonal_sse=null_error, linear_sse=linear_error)
    if mode in ("auto", "exponential"):
        # Search both signs in dimensionless time, then refine the best grid cell.
        bound = min(20.0, 0.1 * len(ys))
        diagnostics["rate_bounds"] = [-bound/len(ys), bound/len(ys)]
        grid = [-bound + 2*bound*i/80 for i in range(81)]
        candidates = [(fit(r)[0], i) for i,r in enumerate(grid) if abs(r)>1e-10]
        _, best = min(candidates)
        lo, hi = grid[max(0,best-1)], grid[min(80,best+1)]
        for _ in range(55):
            a,b = lo+(hi-lo)/3, hi-(hi-lo)/3
            if fit(a)[0] < fit(b)[0]:
                hi=b
            else:
                lo=a
        rate=(lo+hi)/2
        error, amplitude=fit(rate)
        diagnostics["exponential_sse"] = error
        reference = linear_error if selected.kind == "linear" else null_error
        # Positive amplitude permits genuine exponential growth and decay,
        # rather than a mirrored exponential with an arbitrary sign.
        if amplitude > 0 and abs(rate)>1e-5 and (mode == "exponential" or error < 0.5*max(reference, floor)):
            selected=Trend("exponential", amplitude, rate/len(ys), origin)
        elif mode == "exponential":
            selected=Trend()
            diagnostics["reason"]="no supported positive-amplitude exponential fit; seasonal fallback"
    diagnostics.update(selected=selected.kind, coefficient=selected.coefficient,
                       rate=selected.rate, origin=selected.origin)
    return selected, diagnostics
