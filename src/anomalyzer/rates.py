"""Denominator-aware comparisons and bounded replay using only the stdlib."""
import math
from statistics import NormalDist

from .budget import RuntimeBudget
from .events import fingerprint
from .rate_contracts import (
    RateMonitorRequest, RateMonitorResult, RatePopulation, RateRequest, RateResult,
)


LIMITATIONS = [
    "Inference assumes independent Bernoulli trials with a common rate within each comparable population; counts and row IDs do not establish independence or disjoint trials.",
    "Clustered customers/events, overdispersion, changing traffic mix and calendar effects can invalidate the model. Select comparable periods and validate on representative replay.",
    "Wilson intervals describe the population rate conditional on the binomial model; they are not prediction ranges for future bucket counts or guaranteed coverage.",
    "Bonferroni correction covers only the declared comparisons. Callers own budgets across metrics, monitor restarts, references and deployments.",
    "A rate departure is not an incident probability or causal explanation. Exact rate-limit violations are separate caller rules.",
]


def _wilson(successes, trials, coverage):
    if not trials:
        return None
    z = NormalDist().inv_cdf((1+coverage)/2)
    p, z2 = successes/trials, z*z
    denominator = 1+z2/trials
    center = (p+z2/(2*trials))/denominator
    radius = z*math.sqrt(p*(1-p)/trials+z2/(4*trials*trials))/denominator
    return dict(lower=max(0.0, center-radius), upper=min(1.0, center+radius),
                coverage=coverage, method="wilson_score", conditional_on_binomial_model=True)


def _summary(population, coverage):
    known = [s for s in population.samples if s.complete and s.successes is not None and s.trials is not None]
    successes, trials = sum(s.successes for s in known), sum(s.trials for s in known)
    available = len(known) == len(population.samples) and trials > 0
    times = [s.timestamp for s in population.samples if s.timestamp is not None]
    return dict(successes=successes, trials=trials, rate=successes/trials if available else None,
                available=available, low_support=trials < 20,
                sample_ids=[s.id for s in population.samples], usable_sample_ids=[s.id for s in known],
                unknown_ids=[s.id for s in population.samples if s.successes is None or s.trials is None],
                incomplete_ids=[s.id for s in population.samples if not s.complete],
                zero_trial_ids=[s.id for s in known if s.trials == 0],
                time_extent=[min(times), max(times)] if times else None,
                interval=_wilson(successes, trials, coverage) if available else None,
                totals_scope="complete known rows only; inference requires every supplied row to be known and complete")


def _fisher(a, n, c, m, max_tables, budget):
    """Probability-ordered two-sided conditional test, normalized at its mode.

    Relative hypergeometric masses avoid enormous combinations and cancellation
    in log factorials. Enumerate the full finite support; never silently fall
    back to a normal approximation when the work limit is exceeded.
    """
    total, successes = n+m, a+c
    low, high = max(0, n-(total-successes)), min(n, successes)
    mode = min(high, max(low, (n+1)*(successes+1)//(total+2)))
    if a == mode:
        return 1.0, high-low+1
    if high-low+1 > max_tables:
        return None, high-low+1
    masses = [0.0]*(high-low+1)
    masses[mode-low] = 1.0
    mass = 1.0
    for x in range(mode, high):
        if x % 256 == 0:
            budget.check()
        mass *= ((successes-x)*(n-x))/((x+1)*(total-successes-n+x+1))
        masses[x+1-low] = mass
    mass = 1.0
    for x in range(mode, low, -1):
        if x % 256 == 0:
            budget.check()
        mass *= (x*(total-successes-n+x))/((successes-x+1)*(n-x+1))
        masses[x-1-low] = mass
    observed = masses[a-low]
    p = math.fsum(w for w in masses if w <= observed*(1+1e-12))/math.fsum(masses)
    return min(1.0, p), len(masses)


def _compare(request, budget):
    cfg = request.config
    reference = _summary(request.reference, cfg.interval_coverage)
    current = _summary(request.current, cfg.interval_coverage)
    result = RateResult(status="insufficient_history", entity=request.entity, context=request.context,
        input_fingerprint=fingerprint(request.model_dump(mode="json")), reference=reference, current=current,
        threshold=cfg.alpha/cfg.max_comparisons,
        testing=dict(alpha=cfg.alpha, max_comparisons=cfg.max_comparisons, comparison_index=cfg.comparison_index,
                     adjustment="bonferroni", min_effect=cfg.min_effect, units="absolute rate fraction"),
        limitations=LIMITATIONS.copy())
    if current["available"]:
        rate = current["rate"]
        for rule in request.limits:
            matches = {"lt": rate < rule.threshold, "lte": rate <= rule.threshold,
                       "gt": rate > rule.threshold, "gte": rate >= rule.threshold}
            if matches[rule.operator]:
                result.rate_limit_violations.append(dict(**rule.model_dump(), observed_rate=rate,
                    evidence_kind="exact_caller_rule"))
    if not reference["available"] or not current["available"]:
        result.reasons.append("Both populations need known, complete counts and positive total trials; unknown, incomplete or zero-exposure populations stay unavailable.")
        return result
    result.effect = current["rate"]-reference["rate"]
    result.practical_change = abs(result.effect) >= cfg.min_effect
    if reference["low_support"] or current["low_support"]:
        result.reasons.append("At least one population has fewer than 20 trials; inspect the wide rate interval. The exact test does not require a large-count approximation.")
    if reference["trials"] < cfg.min_reference_trials or current["trials"] < cfg.min_current_trials:
        result.reasons.append("The configured minimum trial support is not met.")
        return result
    if not request.assume_independent_trials:
        result.status = "descriptive"
        result.reasons.append("Independent, disjoint Bernoulli trials from comparable populations were not asserted; no statistical finding is made.")
        return result
    try:
        budget.check()
        p, tables = _fisher(reference["successes"], reference["trials"], current["successes"], current["trials"], cfg.max_tables, budget)
        result.details = dict(conditional_support_tables=tables, max_tables=cfg.max_tables,
                              p_value_definition="probability_ordered_two_sided", numerical_method="mode_normalized_hypergeometric_recurrence")
        if p is None:
            result.status = "resolution_limited"
            result.reasons.append("Exact conditional support exceeds max_tables; no approximate score was substituted.")
            return result
        result.status = "completed"
        result.p_value = p
        result.adjusted_p_value = min(1.0, p*cfg.max_comparisons)
        result.statistical_change = p <= result.threshold
        result.change_detected = result.statistical_change and result.practical_change
    except TimeoutError as exc:
        result.status = "budget_exceeded"
        result.reasons.append(str(exc))
    return result


def _observations(result):
    """Numerical observations for caller/LLM interpretation, never alert authority."""
    result.observations = [dict(kind="rate_comparison", status=result.status,
        reference_rate=result.reference["rate"], current_rate=result.current["rate"],
        effect=result.effect, p_value=result.p_value, threshold=result.threshold,
        criterion_met=result.change_detected, interpretation="statistical evidence; alert decision belongs to caller")]
    if result.reference["low_support"] or result.current["low_support"]:
        result.observations.append(dict(kind="limited_trial_support",
            reference_trials=result.reference["trials"], current_trials=result.current["trials"],
            reference_interval=result.reference["interval"], current_interval=result.current["interval"]))
    if result.status != "completed":
        result.observations.append(dict(kind="unassessed_statistical_comparison", status=result.status, reasons=result.reasons.copy()))
    result.observations.extend(dict(kind="caller_rate_limit_violation", **rule) for rule in result.rate_limit_violations)
    return result


def compare_rates(request: RateRequest | dict) -> RateResult:
    request = RateRequest.model_validate(request)
    return _observations(_compare(request, RuntimeBudget(request.config.max_runtime_seconds)))


def monitor_rates(request: RateMonitorRequest | dict) -> RateMonitorResult:
    request = RateMonitorRequest.model_validate(request)
    budget = RuntimeBudget(request.config.max_runtime_seconds)
    family = request.max_looks*len(request.window_sizes)
    reference = RatePopulation(samples=request.samples[:request.reference_size])
    evaluations, first, reasons = [], None, []
    looks, stopped = 0, False
    for look in range(request.max_looks):
        end = request.reference_size+1+look*request.stride
        if end > len(request.samples):
            break
        looks += 1
        for offset, window in enumerate(request.window_sizes):
            start = end-window
            row = dict(look=look, index=end-1, timestamp=request.samples[end-1].timestamp,
                       window_size=window, current_start_index=start, change_detected=False)
            if start < request.reference_size:
                row.update(status="insufficient_history", result=None, reason="current_window_not_yet_disjoint_from_reference")
            else:
                cfg = request.config.model_copy(update=dict(max_comparisons=family,
                    comparison_index=look*len(request.window_sizes)+offset))
                result = _observations(_compare(RateRequest(entity=request.entity, context=request.context, reference=reference,
                    current=RatePopulation(samples=request.samples[start:end]),
                    assume_independent_trials=request.assume_independent_trials, config=cfg), budget))
                row.update(status=result.status, result=result.model_dump(mode="json"), change_detected=result.change_detected)
                if result.change_detected and first is None:
                    first = {k: row[k] for k in ("look", "index", "timestamp", "window_size", "current_start_index")}
                if result.status == "budget_exceeded":
                    stopped = True
                    reasons.append("Replay stopped at the shared runtime budget; later comparisons are unassessed.")
            evaluations.append(row)
            if stopped:
                break
        if stopped:
            break
    if len(request.samples) < request.reference_size:
        reasons.append("The declared frozen reference prefix is not complete.")
    status = ("partial" if stopped else "horizon_exhausted" if looks == request.max_looks else
              "completed" if any(r["status"] == "completed" for r in evaluations) else "insufficient_history")
    return RateMonitorResult(status=status, monitor_id=request.monitor_id, entity=request.entity, context=request.context,
        input_fingerprint=fingerprint(request.model_dump(mode="json")), reference=_summary(reference, request.config.interval_coverage),
        evaluations=evaluations, first_detection=first,
        testing=dict(alpha=request.config.alpha, max_comparisons=family, max_looks=request.max_looks,
                     evaluated_looks=looks, window_sizes=request.window_sizes, adjustment="bonferroni",
                     completed_comparisons=sum(r["status"] == "completed" for r in evaluations),
                     unassessed_comparisons=sum(r["status"] != "completed" for r in evaluations),
                     reference_prefix_complete=len(request.samples) >= request.reference_size,
                     reference_size=request.reference_size, reference_last_index=request.reference_size-1,
                     reference_cutoff=request.samples[request.reference_size-1].timestamp if len(request.samples) >= request.reference_size else None,
                     horizon_exhausted=looks == request.max_looks,
                     unprocessed_samples=max(0, len(request.samples)-(request.reference_size+(looks-1)*request.stride+1)) if looks else max(0, len(request.samples)-request.reference_size)),
        reasons=reasons, limitations=LIMITATIONS+[
            "Windows pool declared rows, not inferred elapsed periods; supply every native bucket, including unknown and zero-exposure buckets. Unknown/incomplete windows remain unavailable.",
            "Reference counts stay frozen. Overlapping windows are correlated; the planned family includes all looks and widths, including unavailable comparisons."])
