"""Schema-1.1 source policies and causal sparse references; never impute a measurement.

Calendar coordinates remain dense only inside an explicitly bounded input grid.
Event coordinates retain actual timestamps and represent comparable events, not time.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import hashlib
import json
import math
import re
import statistics
import time
import uuid

from .budget import RuntimeBudget
from .contracts import Context, DataPolicy, Dataset, DatasetV11, MethodResult, Result
from .evidence import anomaly_patterns, episodes
from .registry import versions
from .robust import extreme_indices
from .validation import resolve_reset_points, timestamp


def cadence_seconds(frequency):
    number, unit = re.fullmatch(r"([1-9][0-9]*)(s|min|h|d|w)", frequency).groups()
    return int(number) * {"s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def uses_policy(ds):
    if not isinstance(ds, DatasetV11) or ds.timestamps is None:
        return False
    if ds.data_policy or ds.coverage is not None or ds.available_at is not None or ds.revisions or any(v is None for v in ds.values) or "incomplete" in (ds.period_statuses or []):
        return True
    times = sorted(timestamp(t, ds.timezone) for t in ds.timestamps)
    step = timedelta(seconds=cadence_seconds(ds.frequency))
    return any(b - a not in (timedelta(0), step) for a, b in zip(times, times[1:]))


def normalize(ds, cfg, context, budget=None):
    """Return the explicit grid, eligible model values and inspectable provenance."""
    budget = budget or RuntimeBudget(cfg.max_runtime_seconds)
    policy = ds.data_policy or DataPolicy()
    context = Context.model_validate(context or {})
    cutoff = timestamp(context.as_of, ds.timezone) if context.as_of else None
    rows = {}
    statuses = ds.period_statuses or ["complete"] * len(ds.values)
    for index, (text, value, status) in enumerate(zip(ds.timestamps, ds.values, statuses)):
        budget.check()
        observed_at = timestamp(text, ds.timezone)
        coverage = ds.coverage[index] if ds.coverage else (
            "incomplete" if status == "incomplete" else
            "complete" if value is not None else "empty" if policy.absence_means_zero else "unknown")
        if status == "incomplete" and coverage != "incomplete":
            raise ValueError("incomplete period_status conflicts with coverage")
        available = timestamp(ds.available_at[index], ds.timezone) if ds.available_at and ds.available_at[index] else None
        if available and available < observed_at:
            raise ValueError("available_at cannot precede event time")
        if cutoff and observed_at > cutoff:
            continue
        if observed_at in rows:
            if cfg.duplicate_policy == "error" or policy.observation_basis == "event_index":
                raise ValueError("duplicate timestamps require declared duplicate_policy; event_index needs unique event timestamps")
            previous = rows[observed_at]
            if coverage != "complete" or previous["coverage"] != "complete" or ds.available_at or ds.revisions:
                raise ValueError("duplicate aggregation requires complete unrevisioned values")
            previous["duplicates"].append(value)
            parts = previous["duplicates"]
            combined = None if any(v is None for v in parts) else math.fsum(parts)
            if combined is not None and cfg.duplicate_policy == "mean":
                combined /= len(parts)
            if combined is not None and not math.isfinite(combined):
                raise ValueError("duplicate aggregation produced nonfinite value")
            previous["original_value"] = combined
            previous.setdefault("source_indexes", [previous["source_index"]]).append(index)
            continue
        rows[observed_at] = dict(source_index=index, original_value=value, coverage=coverage,
                                 period_status=status, available_at=available, revision_id=None, duplicates=[value])
    revision_keys = set()
    for revision in ds.revisions:
        budget.check()
        observed_at = timestamp(revision.timestamp, ds.timezone)
        available = timestamp(revision.available_at, ds.timezone)
        key = (observed_at, available)
        if key in revision_keys:
            raise ValueError("revisions need unique event-time/available-at pairs")
        revision_keys.add(key)
        if available < observed_at:
            raise ValueError("revision available_at cannot precede event time")
        if cutoff and (observed_at > cutoff or available > cutoff):
            continue
        previous = rows.get(observed_at)
        if previous is not None and previous["available_at"] and previous["available_at"] > available and (not cutoff or previous["available_at"] <= cutoff):
            continue
        rows[observed_at] = dict(source_index=previous["source_index"] if previous else -1,
                                 original_value=revision.value, coverage=revision.coverage,
                                 period_status="incomplete" if revision.coverage == "incomplete" else "complete",
                                 available_at=available, revision_id=revision.revision_id, duplicates=[])
    times = sorted(rows)
    if policy.observation_basis == "calendar":
        known_times = [t for t in times if not cutoff or not rows[t]["available_at"] or rows[t]["available_at"] <= cutoff]
        step = timedelta(seconds=cadence_seconds(ds.frequency))
        start = timestamp(policy.grid_start, ds.timezone) if policy.grid_start else (known_times[0] if known_times else None)
        end = timestamp(policy.grid_end, ds.timezone) if policy.grid_end else (known_times[-1] if known_times else None)
        if start is None or end is None:
            grid = []
        else:
            if end < start:
                raise ValueError("grid_end precedes grid_start")
            if (end - start) % step:
                raise ValueError("grid_end is off the declared cadence grid")
            if any(t < start or t > end or (t - start) % step for t in known_times):
                raise ValueError("timestamp outside or off the declared cadence grid")
            if cutoff:
                end = min(end, cutoff)
            count = max(0, (end - start) // step + 1)
            if count + len(ds.revisions) > cfg.max_points:
                raise ValueError("expanded grid and revisions exceed max_points")
            grid = [start + i * step for i in range(count)]
    else:
        if len(times) + len(ds.revisions) > cfg.max_points:
            raise ValueError("events and revisions exceed max_points")
        grid = [t for t in times if not cutoff or not rows[t]["available_at"] or rows[t]["available_at"] <= cutoff]
    samples, values, rule_values = [], [], []
    for index, observed_at in enumerate(grid):
        budget.check()
        row = rows.get(observed_at, dict(source_index=-1, original_value=None,
                       coverage="empty" if policy.absence_means_zero else "unknown",
                       available_at=None, revision_id=None))
        state, original = row["coverage"], row["original_value"]
        if row["available_at"] and cutoff and row["available_at"] > cutoff:
            state, original = "unknown", None
            reason = "not_available_as_of"
        else:
            reason = None
        if state == "empty" and original not in (None, 0):
            raise ValueError("empty coverage conflicts with nonzero observed value")
        if state in ("complete", "revised") and original is None:
            state = "unknown"
        value = original if state in ("complete", "revised") else None
        if state == "empty" and policy.missing == "zero_for_empty":
            value, reason = 0.0, "confirmed_empty_additive_volume"
        if reason is None and value is None:
            reason = {"empty": "empty_preserved_as_missing", "unknown": "collection_unknown",
                      "incomplete": "period_incomplete", "excluded": "explicit_model_exclusion"}[state]
        values.append(value)
        rule_values.append(original if state == "excluded" else value)
        samples.append(dict(index=index, source_index=row["source_index"], original_value=original,
                            source_indexes=row.get("source_indexes", [row["source_index"]] if row["source_index"] >= 0 else []),
                            origin="duplicate_aggregate" if "source_indexes" in row else "revision" if row["revision_id"] else "supplied" if observed_at in rows else "omitted",
                            original_period_status=row.get("period_status"), original_coverage=row["coverage"],
                            value=value, coverage=state, reason=reason,
                            available_at=row["available_at"].isoformat() if row["available_at"] else None,
                            revision_id=row["revision_id"]))
    quality = dict(input_count=len(ds.values), grid_count=len(grid),
        observation_count=sum(v is not None for v in rule_values),
        reported_measurement_count=sum(s["original_value"] is not None and s["coverage"] in ("complete", "revised", "excluded") for s in samples),
        complete_count=sum(v is not None for v in values),
        incomplete_count=sum(s["coverage"] == "incomplete" for s in samples),
        incomplete_periods=[dict(index=s["index"], timestamp=grid[s["index"]].isoformat(),
                                observed=s["original_value"], period_status="incomplete")
                            for s in samples if s["coverage"] == "incomplete"],
        missing_count=sum(v is None for v in values), duplicate_count=len(ds.values)-len({timestamp(t, ds.timezone) for t in ds.timestamps}),
        regular=True, transformations=["bounded declared grid; no interpolation or carry-forward"],
        timestamp_normalization="UTC", coordinate=policy.observation_basis,
        regularity_basis="declared_cadence" if policy.observation_basis == "calendar" else "explicit_comparable_events",
        window=[grid[0].isoformat(), grid[-1].isoformat()] if grid else None,
        units=ds.units, entity=ds.entity, data_policy=policy.model_dump(mode="json"),
        samples=samples, rule_values=rule_values,
        coverage_counts=dict(Counter(s["coverage"] for s in samples)),
        zero_filled_count=sum(s["reason"] == "confirmed_empty_additive_volume" for s in samples),
        omitted_count=sum(s["origin"] == "omitted" for s in samples),
        usable_model_count=sum(v is not None for v in values),
        measured_value_count=sum(v is not None for v in rule_values),
        duplicate_sources=[dict(timestamp=t.isoformat(), source_indexes=row["source_indexes"], original_values=row["duplicates"])
                           for t, row in rows.items() if "source_indexes" in row],
        latest_evidence_state="insufficient_evidence" if values and values[-1] is None else "available",
        arrival_semantics="supplied availability timestamps; unannotated samples are event-time snapshots" if any(s["available_at"] and (s["value"] is not None or s["coverage"] == "excluded") for s in samples) else
                          "event-time snapshot only; historical delivery timing is unknown")
    return [t.isoformat() for t in grid], values, quality


def analyze_sparse(ds, cfg, context, budget=None, prepared=None):
    """Frozen training phase medians, eligible calibration counts, gap-broken patterns."""
    started = time.perf_counter()
    budget = budget or RuntimeBudget(cfg.max_runtime_seconds)
    context = Context.model_validate(context or {})
    times, values, quality = prepared or normalize(ds, cfg, context, budget)
    policy = ds.data_policy or DataPolicy()
    resets = active_resets(cfg.reset_points, times, ds.timezone, context.as_of)
    if policy.observation_basis == "calendar" and (cfg.recipe == "adaptive-seasonal-v1" or cfg.trend not in ("none", "auto")):
        return analyze_contiguous(ds, cfg, context, budget, (times, values, quality), resets)
    method = MethodResult(id="sparse_seasonal", status="insufficient_history",
        applicability="eligible observations on the original grid; frozen training phase reference",
        parameters={**cfg.model_dump(), "resolved_reset_positions": resets,
                    "profile_revision": "sparse-frozen-phase-v1",
                    "observation_basis": policy.observation_basis, "reference_updates": "frozen_until_explicit_reset"},
        diagnostics={"segments": [], "unavailable": [], "pattern_boundaries": resets.copy()})
    unsupported = ("event_index requires season_length=1, trend=none/auto and a single-resolution seasonal recipe"
        if policy.observation_basis == "event_index" and
        (cfg.season_length != 1 or cfg.trend not in ("none", "auto") or cfg.recipe != "seasonal-residual-v1")
        else "sparse references currently require seasonal-residual-v1 and trend=none/auto; other recipes need complete segments"
        if cfg.recipe != "seasonal-residual-v1" or cfg.trend not in ("none", "auto") else None)
    patterns, observations = [], []
    boundaries = sorted(set([0, *resets, len(values)] + (
        [i + 1 for i, value in enumerate(values[:-1]) if value is None]
        if policy.reference_gaps == "restart" else [])))
    try:
        if unsupported:
            method.status, method.applicability = "inapplicable", unsupported
        else:
            for segment_number, (start, stop) in enumerate(zip(boundaries, boundaries[1:])):
                budget.check()
                training, calibration = [], []
                phase_values, phase_indexes, phase_expected = {}, {}, {}
                center = scale = None
                evidence = []
                segment = dict(number=segment_number, start_position=start, end_position=stop-1,
                    training_origin=times[start] if start < len(times) else None,
                    training_indexes=[], calibration_indexes=[], phase_references=[],
                    status="insufficient_history", trend="none (explicit sparse frozen reference)")
                for index in range(start, stop):
                    budget.check()
                    value = values[index]
                    phase = (index - start) % cfg.season_length
                    if len(training) < cfg.training_size:
                        if value is not None:
                            training.append(index)
                            phase_values.setdefault(phase, []).append(value)
                            phase_indexes.setdefault(phase, []).append(index)
                        if len(training) == cfg.training_size:
                            phase_expected = {p: (safe_median(v) if cfg.outlier_handling == "robust" else statistics.mean(v)) for p, v in phase_values.items()
                                              if len(v) >= policy.minimum_phase_samples}
                            segment["training_indexes"] = training.copy()
                            segment["phase_references"] = [dict(phase=p, expected=phase_expected.get(p),
                                indexes=phase_indexes[p]) for p, v in sorted(phase_values.items())]
                        elif value is None:
                            method.diagnostics["unavailable"].append(dict(index=index, reason="missing_training_sample"))
                        continue
                    expected = phase_expected.get(phase)
                    if value is None or expected is None:
                        method.diagnostics["unavailable"].append(dict(index=index,
                            reason="missing_observation" if value is None else "no_training_support_for_calendar_phase",
                            modeled_expectation=expected))
                        continue
                    residual = value - expected
                    if not math.isfinite(residual):
                        method.diagnostics["unavailable"].append(dict(index=index, reason="nonfinite_residual"))
                        continue
                    maturity, z, triggers = "reference_only", None, []
                    count = len(calibration)
                    if count < cfg.calibration_size:
                        if count >= 3:
                            raw = [item[1] for item in calibration]
                            z = (residual - statistics.mean(raw)) / max(statistics.stdev(raw), cfg.scale_floor)
                            maturity = "provisional"
                        calibration.append((index, residual))
                        segment["calibration_indexes"].append(index)
                    else:
                        if center is None:
                            raw = [item[1] for item in calibration]
                            offsets, _ = extreme_indices(raw, cfg.scale_floor) if cfg.outlier_handling == "robust" else ([], None)
                            retained = [v for offset, v in enumerate(raw) if offset not in offsets]
                            if len(retained) < 3:
                                retained, offsets = raw, []
                            segment["excluded_calibration_indexes"] = [calibration[i][0] for i in offsets]
                            raw = retained
                            center, scale = statistics.mean(raw), max(statistics.stdev(raw), cfg.scale_floor)
                            segment.update(calibration_center=center, calibration_scale=scale,
                                           retained_calibration_samples=len(raw),
                                           calibration_cutoff=times[calibration[-1][0]])
                        count = segment["retained_calibration_samples"]
                        z = (residual - center) / scale
                        maturity = "calibrated"
                        if abs(z) > cfg.point_threshold:
                            triggers = ["point"]
                        segment["status"] = "calibrated"
                    if z is not None and not math.isfinite(z):
                        method.diagnostics["unavailable"].append(dict(index=index, reason="nonfinite_standardized_residual"))
                        continue
                    relative = residual / abs(expected) if expected else None
                    evidence.append(dict(id=f"sparse_seasonal:{index}", method=method.id, index=index,
                        timestamp=times[index], training_cutoff=times[training[-1]], observed=value,
                        expected=expected, residual=residual,
                        relative_deviation=relative if relative is None or math.isfinite(relative) else None,
                        standardized_residual=z, signal_maturity=maturity, calibration_samples=count,
                        triggers=triggers, score_semantics="frozen sparse phase residual; provisional evidence cannot trigger; not a probability",
                        excluded_from_model=False, model_value=value, exclusion_reason=None, reference_action="use_observed"))
                segment["training_indexes"] = training
                method.diagnostics["segments"].append(segment)
                method.evidence.extend(evidence)
                temporary = method.model_copy(update={"evidence": evidence})
                # Separate calls prohibit patterns/episodes crossing explicit regime boundaries.
                for pattern in anomaly_patterns([temporary], ds.id, cusum_k=cfg.cusum_k,
                        cusum_h=cfg.cusum_h, moving_range_threshold=cfg.moving_range_threshold):
                    pattern["id"] = f"segment:{segment_number}:{pattern['id']}"
                    patterns.append(pattern)
                for observation in episodes([temporary], ds.id):
                    observation["id"] = f"segment:{segment_number}:{observation['id']}"
                    observations.append(observation)
            if any(row["signal_maturity"] == "calibrated" for row in method.evidence):
                method.status = "completed"
    except TimeoutError as exc:
        method.status, method.error = "budget_exceeded", str(exc)
    except (ArithmeticError, ValueError) as exc:
        method.status, method.error = "failed", f"{type(exc).__name__}: {exc}"
    method.diagnostics["detection_readiness"] = dict(
        status="caution" if method.status == "completed" else "not_assessed",
        reasons=["Sparse frozen phase medians use only eligible training observations; gaps do not count as measurements.",
                 "Trend and simultaneous seasonal cycles are not estimated by this sparse profile.",
                 "Point references may cross gaps; consecutive residual patterns cannot."],
        assessed_segments=sum(s["status"] == "calibrated" for s in method.diagnostics["segments"]))
    method.limitations = ["Training and calibration origins remain fixed within each explicit regime; no evaluated episode updates the reference.",
        "Sparse calibration counts usable residuals, not elapsed grid positions. Phase support and readiness remain separate from business severity.",
        "No probability, health verdict, abuse accuracy, operational permission or delivery-time performance is established."]
    resolved = dict(datasets=[ds.model_dump(mode="json")], config=cfg.model_dump(mode="json"),
                    context=context.model_dump(mode="json"))
    method.runtime_seconds = time.perf_counter() - started
    status = "partial" if method.status in ("budget_exceeded", "failed") else method.status
    return Result(run_id=str(uuid.uuid4()), status=status,
        input_fingerprint=hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest(),
        resolved_config=resolved, dependencies=versions(), data_quality=quality, methods=[method],
        observations=observations, anomaly_patterns=patterns, limitations=method.limitations,
        suggested_checks=["Inspect coverage, original values, arrival timing and phase support before interpreting departures."],
        runtime_seconds=time.perf_counter()-started,
        stop_reason="runtime_budget" if method.status == "budget_exceeded" else "method_failure" if method.status == "failed" else "completed")


def active_resets(points, times, zone=None, as_of=None):
    if as_of:
        cutoff = timestamp(as_of, zone)
        points = [p for p in points if (isinstance(p, int) and p < len(times)) or
                  (isinstance(p, str) and timestamp(p + "T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p) else p, zone) <= cutoff)]
    return resolve_reset_points(points, times, zone)


def safe_median(values):
    ordered = sorted(values)
    middle = len(ordered)//2
    return statistics.mean(ordered[middle-1:middle+1]) if len(ordered)%2 == 0 else ordered[middle]


def analyze_contiguous(ds, cfg, context, budget, prepared, resets):
    """Recipes requiring complete model inputs restart at every unavailable span."""
    from .recipes import analyze_dataset, _namespace_result
    times, values, quality = prepared
    boundaries = sorted(set([0, len(values), *resets] +
        [position for i, v in enumerate(values) if v is None for position in (i, i+1)]))
    methods, observations, patterns, spans = [], [], [], []
    seen_observation = False
    policy = ds.data_policy or DataPolicy()
    for start, stop in zip(boundaries, boundaries[1:]):
        try:
            budget.check()
        except TimeoutError as exc:
            methods.append(MethodResult(id="contiguous_budget", status="budget_exceeded",
                           applicability="remaining spans were not evaluated", error=str(exc)))
            break
        if start == stop or values[start] is None:
            continue
        span = dict(start=start, stop=stop, eligible_count=stop-start)
        spans.append(span)
        if seen_observation and start not in resets and policy.reference_gaps != "restart":
            span.update(status="inapplicable", reason="post_gap_learning_requires_explicit_reset_or_restart")
            continue
        seen_observation = True
        if stop-start <= cfg.season_length:
            continue
        child = Dataset(id=ds.id, timestamps=times[start:stop], values=values[start:stop],
                        frequency=ds.frequency, units=ds.units, entity=ds.entity)
        settings = cfg.model_copy(update={"reset_points": []})
        result = analyze_dataset(child, settings, context, budget)
        _namespace_result(result, f"contiguous:{start}")
        for method in result.methods:
            method.parameters["source_grid_offset"] = start
            method.parameters["profile_revision"] = "contiguous-spans-v1"
            method.parameters["sparse_support"] = "complete contiguous spans only; post-gap learning needs explicit reset/restart"
            for row in method.evidence:
                row["index"] += start
        for item in result.observations:
            item["triggering_samples"] = [i+start for i in item["triggering_samples"]]
        for item in result.anomaly_patterns:
            item["triggering_samples"] = [i+start for i in item["triggering_samples"]]
            item["detection_index"] += start
        methods.extend(result.methods)
        observations.extend(result.observations)
        patterns.extend(result.anomaly_patterns)
    if not methods:
        methods = [MethodResult(id="contiguous_segments", status="insufficient_history",
                                applicability="no complete span supplies even a seasonal reference")]
    quality["contiguous_spans"] = spans
    limited = any(m.status in ("failed", "budget_exceeded") for m in methods)
    status = "partial" if limited else "completed" if any(m.status == "completed" for m in methods) else "insufficient_history"
    resolved = dict(datasets=[ds.model_dump(mode="json")], config=cfg.model_dump(mode="json"),
                    context=context.model_dump(mode="json"))
    return Result(run_id=str(uuid.uuid4()), status=status,
        input_fingerprint=hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest(),
        resolved_config=resolved, dependencies=versions(), data_quality=quality, methods=methods,
        observations=observations, anomaly_patterns=patterns,
        limitations=["This recipe uses complete contiguous spans only; no calendar gap is compressed. Post-gap learning requires an explicit reset or reference_gaps=restart.",
                     "Adaptive spans retain the existing rolling-reference admission policy; an episode quarantine policy is not implemented."],
        suggested_checks=["Inspect complete-span support and restart origins."],
        runtime_seconds=sum(m.runtime_seconds for m in methods), stop_reason="runtime_budget" if budget.remaining == 0 else "method_failure" if limited else "completed")
