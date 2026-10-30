"""Population detectors. Standard library only; no residual fitting or filtering.

Numeric KS uses conditional permutation counts across whole tied-value groups.
Categorical Jensen-Shannon uses exact label allocations for small populations,
otherwise Monte Carlo permutations with the conservative plus-one correction.
"""
from collections import Counter
import hashlib
from itertools import combinations
import json
import math
import random

from .budget import RuntimeBudget
from .distribution_contracts import (
    DistributionMonitorRequest, DistributionMonitorResult, DistributionPopulation,
    DistributionRequest, DistributionResult,
)


LIMITATIONS = [
    "Inference assumes independent, exchangeable observations from comparable populations under the null; IDs do not establish independence.",
    "Clustering, serial dependence, changing traffic mix and informative missingness can invalidate statistical interpretation; use representative chronological replay.",
    "The testing family covers only declared comparisons; caller owns budgets across metrics, monitors, reference selection, restarts and deployments.",
    "No finding establishes cause, abuse, incident probability or business impact; no finding does not establish normality.",
]


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _summary(population, kind):
    samples = [sample for sample in population.samples if sample.complete and sample.value is not None]
    values = [sample.value for sample in samples]
    summary = dict(sample_count=len(samples), sample_ids=[sample.id for sample in samples],
                   excluded_ids=[s.id for s in population.samples if not s.complete or s.value is None],
                   unknown_count=sum(s.value is None for s in population.samples),
                   incomplete_count=sum(not s.complete for s in population.samples))
    if kind == "categorical":
        summary["total_weight"] = math.fsum(sample.weight for sample in samples)
        summary["sampling_unit"] = "event (not consumed units)"
    times = [sample.timestamp for sample in samples if sample.timestamp is not None]
    summary["interval"] = [min(times), max(times)] if times else None
    if kind == "numeric" and values:
        # Scaling first keeps a mean of very large finite inputs finite.
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else ordered[middle-1] / 2 + ordered[middle] / 2
        scale = max(abs(value) for value in values)
        mean = scale * (math.fsum(value / scale for value in values) / len(values)) if scale else 0.0
        summary.update(mean=mean, median=median,
                       minimum=min(values), maximum=max(values), zero_fraction=values.count(0) / len(values))
    return samples, summary


def _ks_statistic(a, b):
    ca, cb = Counter(a), Counter(b)
    n, m = len(a), len(b)
    left = right = peak = 0
    location = None
    sign = 0
    for value in sorted(ca.keys() | cb.keys()):
        left += ca[value]
        right += cb[value]
        difference = left * m - right * n
        if abs(difference) > peak:
            peak, location, sign = abs(difference), value, 1 if difference > 0 else -1
    return peak, location, sign


def _ks_exact(a, b, budget):
    """Count assignments strictly inside the observed KS boundary.

    Multiplicity C(tie_count, left_count) counts distinct event labelings. CDF
    differences are evaluated only after a whole tie group, never within a tie.
    Integer arithmetic includes all equally extreme assignments without rounding.
    """
    n, m = len(a), len(b)
    peak, location, sign = _ks_statistic(a, b)
    if peak == 0:
        return 0.0, 1.0, location, sign
    pooled = Counter(a + b)
    paths, seen = {0: 1}, 0
    for value in sorted(pooled):
        budget.check()
        count = pooled[value]
        next_paths = {}
        for left, ways in paths.items():
            budget.check()
            lo, hi = max(0, seen + count - m - left), min(count, n - left)
            for allocated in range(lo, hi + 1):
                after = left + allocated
                if abs(after * m - (seen + count - after) * n) < peak:
                    next_paths[after] = next_paths.get(after, 0) + ways * math.comb(count, allocated)
        paths, seen = next_paths, seen + count
    total = math.comb(n + m, n)
    return peak / (n * m), (total - paths.get(n, 0)) / total, location, sign


def _js(a, b, categories):
    na, nb = math.fsum(a.values()), math.fsum(b.values())
    terms = []
    for category in categories:
        p, q = a.get(category, 0) / na, b.get(category, 0) / nb
        total = p + q
        terms.append((p * math.log2(2 * p / total) / 2 if p else 0) +
                     (q * math.log2(2 * q / total) / 2 if q else 0))
    return max(0.0, min(1.0, math.fsum(terms)))


def _mass(events):
    grouped = {}
    for category, weight in events:
        grouped.setdefault(category, []).append(weight)
    return {category: math.fsum(weights) for category, weights in grouped.items()}


def _categorical(a, b, cfg, budget):
    # Reassign whole (category, measured quantity) events; never expand a
    # report into fictitious independent units or separate its label/quantity.
    pooled = sorted(a + b)
    categories = sorted({category for category, _ in pooled})
    observed = _js(_mass(a), _mass(b), categories)
    allocations = math.comb(len(pooled), len(a))
    exact = allocations <= cfg.permutations
    draws = allocations if exact else cfg.permutations
    rng = random.Random(cfg.seed)
    selections = combinations(range(len(pooled)), len(a)) if exact else (
        rng.sample(range(len(pooled)), len(a)) for _ in range(draws))
    extreme = 0
    for indexes in selections:
        budget.check()
        selected = set(indexes)
        left = _mass(pooled[index] for index in selected)
        right = _mass(event for index, event in enumerate(pooled) if index not in selected)
        if _js(left, right, categories) >= observed - 1e-14:
            extreme += 1
    p = extreme / draws if exact else (extreme + 1) / (draws + 1)
    return observed, p, dict(permutation_method="exact" if exact else "monte_carlo_plus_one",
                             permutations=draws, seed=None if exact else cfg.seed,
                             minimum_p_value=1 / draws if exact else 1 / (draws + 1))


def compare_distributions(request: DistributionRequest | dict, *, _budget=None) -> DistributionResult:
    """Compare two explicit disjoint populations; no automatic normalization or binning."""
    request = DistributionRequest.model_validate(request)
    cfg = request.config
    budget = _budget or RuntimeBudget(cfg.max_runtime_seconds)
    reference, reference_summary = _summary(request.reference, request.kind)
    current, current_summary = _summary(request.current, request.kind)
    threshold = cfg.alpha / cfg.max_comparisons
    result = DistributionResult(status="completed", kind=request.kind, entity=request.entity, units=request.units,
        reference_id=_fingerprint(request.reference.model_dump(mode="json")),
        current_id=_fingerprint(request.current.model_dump(mode="json")),
        input_fingerprint=_fingerprint(request.model_dump(mode="json")),
        method="ks_tie_exact" if request.kind == "numeric" else "jensen_shannon_permutation",
        threshold=threshold, reference=reference_summary, current=current_summary,
        testing=dict(alpha=cfg.alpha, max_comparisons=cfg.max_comparisons,
                     comparison_index=cfg.comparison_index, correction="bonferroni",
                     assume_exchangeable=request.assume_exchangeable, min_effect=cfg.min_effect,
                     missing_current=cfg.missing_current),
        limitations=LIMITATIONS.copy())
    weighted = request.reference.weights is not None
    if cfg.missing_current == "break" and (current_summary["unknown_count"] or current_summary["incomplete_count"]):
        result.status = "insufficient_history"
        result.reasons.append("An unknown or incomplete current observation breaks this window; original positions and source identities are preserved.")
        return result
    if not weighted and (len(reference) < cfg.min_reference or len(current) < cfg.min_current):
        result.status = "insufficient_history"
        result.reasons.append("Not enough complete measured events in one or both populations; unknowns are not zeros.")
        return result
    a, b = [sample.value for sample in reference], [sample.value for sample in current]
    try:
        budget.check()
        if request.kind == "numeric":
            peak, location, sign = _ks_statistic(a, b)
            result.statistic = peak / (len(a) * len(b))
            result.details.update(statistic_location=location, cdf_sign=sign,
                                  effect_semantics="maximum absolute CDF share difference; not a mean shift or probability")
            if request.assume_exchangeable:
                _, result.p_value, _, _ = _ks_exact(a, b, budget)
                result.details["permutation_method"] = "exact_tie_conditional"
        else:
            a_events = [(sample.value, sample.weight) for sample in reference]
            b_events = [(sample.value, sample.weight) for sample in current]
            ca = request.reference.weights if weighted else _mass(a_events)
            cb = request.current.weights if weighted else _mass(b_events)
            categories = sorted(ca.keys() | cb.keys())
            if len(categories) > 128:
                raise ValueError("categorical comparisons support at most 128 pooled categories")
            result.statistic = _js(ca, cb, categories)
            na, nb = math.fsum(ca.values()), math.fsum(cb.values())
            contributions = [dict(category=k, reference_share=ca.get(k, 0) / na,
                current_share=cb.get(k, 0) / nb, share_change=cb.get(k, 0) / nb - ca.get(k, 0) / na) for k in categories]
            result.details.update(categories=contributions,
                total_variation=math.fsum(abs(row["share_change"]) for row in contributions) / 2,
                effect_semantics="Jensen-Shannon divergence in bits (0..1); category contributions are descriptive, not independent tests")
            if weighted:
                result.method = "jensen_shannon_descriptive"
                result.reference.update(total_weight=na, sample_count=None)
                result.current.update(total_weight=nb, sample_count=None)
                result.reasons.append("Consumed units/weights are not independent event counts; no statistical test or finding is produced.")
            elif request.assume_exchangeable:
                _, result.p_value, metadata = _categorical(a_events, b_events, cfg, budget)
                result.details.update(metadata)
        result.practical_change = result.statistic > 0 and result.statistic >= cfg.min_effect
        if result.p_value is None:
            result.status = "descriptive"
            if not weighted:
                result.reasons.append("Exchangeability was not asserted; effect sizes are descriptive only.")
        else:
            result.adjusted_p_value = min(1.0, result.p_value * cfg.max_comparisons)
            result.statistical_change = result.p_value <= threshold
            result.change_detected = result.statistical_change and result.practical_change
            if result.details.get("minimum_p_value", 0) > threshold:
                result.status = "resolution_limited"
                result.reasons.append("Permutation resolution cannot reach the allocated threshold; increase permutations or revise the planned family before observing results.")
            if not result.change_detected:
                result.reasons.append("No finding under the configured statistical and practical thresholds; this does not establish normality.")
    except TimeoutError:
        result.status = "budget_exceeded"
        result.p_value = result.adjusted_p_value = None
        result.statistical_change = result.change_detected = False
        result.reasons.append("Runtime budget exhausted; unfinished inference cannot trigger a finding.")
    return result


def monitor_distributions(request: DistributionMonitorRequest | dict) -> DistributionMonitorResult:
    """Replay a predeclared finite monitoring family against one frozen prefix.

    Windows contain original event positions. Unknown values break a window;
    they are never compacted into artificial adjacency. Incomplete suffixes
    are retained as quality information and not evaluated.
    """
    request = DistributionMonitorRequest.model_validate(request)
    budget = RuntimeBudget(request.config.max_runtime_seconds)
    reference = DistributionPopulation(samples=request.samples[:request.reference_size])
    frozen = _fingerprint(reference.model_dump(mode="json"))
    completed = next((i for i, sample in enumerate(request.samples) if not sample.complete), len(request.samples))
    first_end = request.reference_size + min(request.window_sizes)
    family_size = request.max_looks * len(request.window_sizes)
    evaluations, first = [], None
    status = "completed"
    looks = 0
    for look in range(request.max_looks):
        end = first_end + look * request.stride
        if end > completed:
            break
        try:
            budget.check()
        except TimeoutError:
            status = "partial"
            break
        looks += 1
        for window_index, size in enumerate(request.window_sizes):
            comparison_index = look * len(request.window_sizes) + window_index
            start = end - size
            # Reserve the test even when a larger window is not ready yet.
            samples = request.samples[start:end] if start >= request.reference_size else []
            cfg = request.config.model_copy(update=dict(max_comparisons=family_size, comparison_index=comparison_index,
                                                        missing_current="break"))
            result = compare_distributions(DistributionRequest(kind=request.kind, entity=request.entity, units=request.units,
                reference=reference, current=DistributionPopulation(samples=samples), config=cfg,
                assume_exchangeable=request.assume_exchangeable), _budget=budget)
            row = dict(look=look, index=end - 1, timestamp=request.samples[end-1].timestamp,
                       event_id=request.samples[end-1].id, window_size=size, window_start=max(request.reference_size, start),
                       result=result.model_dump(mode="json"))
            evaluations.append(row)
            if result.change_detected and first is None:
                first = {key: row[key] for key in ("look", "index", "timestamp", "event_id", "window_size")}
            if result.status == "budget_exceeded":
                status = "partial"
                break
        if status == "partial":
            break
    horizon_end = first_end + (request.max_looks-1) * request.stride
    if status != "partial":
        status = "horizon_exhausted" if looks == request.max_looks else "completed" if evaluations else "insufficient_history"
    return DistributionMonitorResult(monitor_id=request.monitor_id, status=status,
        input_fingerprint=_fingerprint(request.model_dump(mode="json")), reference_id=frozen,
        evaluations=evaluations, first_detection=first,
        testing=dict(alpha=request.config.alpha, correction="bonferroni", max_comparisons=family_size,
                     max_looks=request.max_looks, evaluated_looks=looks, planned_last_index=horizon_end-1,
                     threshold=request.config.alpha / family_size, reference_policy="frozen_prefix_no_automatic_reset"),
        data_quality=dict(source_samples=len(request.samples), complete_samples=completed,
                          unknown_samples=sum(sample.value is None for sample in request.samples),
                          incomplete_samples=len(request.samples)-completed,
                          after_horizon_samples=max(0, completed-horizon_end), order=request.order),
        limitations=LIMITATIONS + ["Overlapping windows are correlated findings, not independent incidents. Replaying an unchanged family is reproducible; restarting it does not create a new free alpha budget.",
            "The reference is never fitted with current observations or automatically reset. This API does not persist state, schedule calls or deliver alerts."])
