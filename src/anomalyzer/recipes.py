import hashlib
import json
import math
import re
import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone
from .baseline import expected_value
from .contracts import Dataset, Request, Result, MethodResult, Settings
from .evidence import anomaly_patterns, episodes
from .registry import versions
from .seasonality import infer_season_length
from .trend import Trend, fit_trend
from .validation import prepare, resolve_reset_points, timestamp


def analyze(request: Request | dict | list[float | None],
            settings: Settings | dict | None = None) -> Result:
    """Dispatch a validated request to its causal anomaly-detection recipe."""
    if isinstance(request, list):
        if isinstance(settings, Settings):
            settings = settings.model_dump(exclude_unset=True)
        request = {"datasets": [{"values": request}], "config": settings or {}}
    elif settings is not None:
        raise ValueError("separate settings are only supported with a bare values list")
    request = Request.model_validate(request)
    if request.config.recipe == "multi-resolution-v1":
        return _analyze_multi_resolution(request)
    return _analyze_seasonal(request)


def _analyze_seasonal(request: Request) -> Result:
    """Emit causal seasonal evidence, and flag only fully calibrated scores."""
    start = time.perf_counter()
    cfg = request.config
    times, values, quality = prepare(request)
    reset_positions = resolve_reset_points(cfg.reset_points, times,
                                           request.datasets[0].timezone)
    season_source = ("explicit" if "season_length" in request.config.model_fields_set
                     else "default")
    season_inference = None
    if quality["coordinate"] == "position" and season_source != "explicit":
        if quality["missing_count"]:
            season_inference = {"status": "not_detected", "selected_lag": 1,
                                "reason": "missing values make the method inapplicable"}
            season_source = "fallback"
        else:
            inference_values = values[:reset_positions[0]] if reset_positions else values
            season, detection_training, season_inference = infer_season_length(
                inference_values, cfg.training_size, cfg.calibration_size, cfg.scale_floor)
            if reset_positions:
                season_inference["manual_segment_scope"] = [0, reset_positions[0]-1]
            cfg = cfg.model_copy(update={"season_length": season,
                                         "training_size": detection_training})
            season_source = ("inferred" if season_inference["status"] == "detected"
                             else "fallback")
    resolved = request.model_dump(mode="json")
    resolved["config"] = cfg.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(resolved, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    training = max(cfg.training_size, cfg.season_length)
    end_calibration = training + cfg.calibration_size
    method = MethodResult(
        id="seasonal_naive" if cfg.trend == "none" else "seasonal_trend", status="completed",
        applicability="regular, complete series with separate training/calibration/evaluation windows",
        parameters={**cfg.model_dump(), "training_size": training,
                    "resolved_reset_positions": reset_positions,
                    "season_length_source": season_source,
                    "baseline_update": "within each manual segment, use the previous seasonal observation plus a training-fitted trend change; trend and calibration are frozen"})
    if season_inference is not None:
        method.diagnostics["season_inference"] = season_inference
    if quality["missing_count"] or not quality["regular"]:
        method.status = "inapplicable"
        method.applicability = "requires complete data at declared cadence; no filling or resampling performed"
    elif len(values) <= cfg.season_length:
        method.status = "insufficient_history"
        method.applicability = (f"reference evidence requires at least {cfg.season_length + 1} observations; "
                                f"received {len(values)}")
    else:
        try:
            def check_budget():
                if time.perf_counter() - start >= cfg.max_runtime_seconds:
                    raise TimeoutError("runtime budget exhausted")
            errors = []
            maturity_counts = {"reference_only": 0, "provisional": 0, "calibrated": 0}
            provisional_floor_count = 0
            segment_diagnostics = []
            boundaries = [0, *reset_positions, len(values)]
            first_calibrated = True
            total_calibration = 0
            for segment_number, (segment_start, segment_stop) in enumerate(zip(boundaries, boundaries[1:])):
                trend = Trend()
                calibration = []
                center = scale = raw_scale = None
                segment_errors = []
                segment_length = segment_stop - segment_start
                segment = {
                    "number": segment_number,
                    "start_position": segment_start,
                    "end_position": segment_stop - 1,
                    "start": times[segment_start] if times[segment_start] is not None else segment_start,
                    "end": times[segment_stop-1] if times[segment_stop-1] is not None else segment_stop-1,
                    "reset_source": None if segment_start == 0 else "manual",
                    "status": "insufficient_history",
                }
                for index in range(segment_start + cfg.season_length, segment_stop):
                    check_budget()
                    local_index = index - segment_start
                    expected = expected_value(values, index, cfg.season_length)
                    if local_index == training:
                        trend, trend_diagnostics = fit_trend(
                            values[segment_start:index], cfg.season_length,
                            cfg.trend, cfg.scale_floor, check_budget)
                        segment["trend"] = trend_diagnostics
                        if "trend" not in method.diagnostics:
                            method.diagnostics["trend"] = trend_diagnostics
                    expected += trend.change(local_index - cfg.season_length, local_index)
                    residual = values[index] - expected
                    if not math.isfinite(residual):
                        raise RuntimeError("nonfinite forecast residual")
                    relative = residual / abs(expected) if expected != 0 else None
                    if relative is not None and not math.isfinite(relative):
                        relative = None
                    maturity = "reference_only"
                    calibration_samples = 0
                    z = None
                    triggers = []
                    semantics = "raw seasonal residual and relative deviation; calibration not yet available"
                    if training <= local_index < end_calibration:
                        calibration_samples = len(calibration)
                        if calibration_samples >= 3:
                            provisional_center = statistics.mean(calibration)
                            provisional_raw_scale = statistics.stdev(calibration)
                            provisional_scale = max(provisional_raw_scale, cfg.scale_floor)
                            if not math.isfinite(provisional_center) or not math.isfinite(provisional_scale):
                                raise RuntimeError("nonfinite provisional calibration statistics")
                            provisional_floor_count += provisional_raw_scale < cfg.scale_floor
                            z = (residual - provisional_center) / provisional_scale
                            if not math.isfinite(z):
                                raise RuntimeError("nonfinite provisional detector statistic")
                            maturity = "provisional"
                            semantics = ("provisional standardized forecast residual using earlier, incomplete "
                                         "segment calibration residuals; not threshold-eligible or a probability")
                        calibration.append(residual)
                    elif local_index >= end_calibration:
                        if center is None:
                            if len(calibration) != cfg.calibration_size:
                                raise RuntimeError("segment calibration residual count does not match calibration_size")
                            center = statistics.mean(calibration)
                            raw_scale = statistics.stdev(calibration)
                            scale = max(raw_scale, cfg.scale_floor)
                            if not math.isfinite(center) or not math.isfinite(scale):
                                raise RuntimeError("nonfinite calibration statistics")
                            if raw_scale < cfg.scale_floor:
                                method.limitations.append("Calibration variance is zero or tiny in a segment; scale_floor determines sensitivity, with no probability interpretation.")
                            segment.update(
                                status="calibrated", calibration_center=center,
                                calibration_scale=scale, raw_scale=raw_scale,
                                training_window=[times[segment_start] if times[segment_start] is not None else segment_start,
                                                 times[segment_start+training-1] if times[segment_start+training-1] is not None else segment_start+training-1],
                                calibration_window=[times[segment_start+training] if times[segment_start+training] is not None else segment_start+training,
                                                    times[segment_start+end_calibration-1] if times[segment_start+end_calibration-1] is not None else segment_start+end_calibration-1],
                                evaluation_window=[times[index] if times[index] is not None else index,
                                                   times[segment_stop-1] if times[segment_stop-1] is not None else segment_stop-1])
                            if first_calibrated:
                                method.diagnostics.update(
                                    calibration_center=center, calibration_scale=scale,
                                    raw_scale=raw_scale,
                                    training_window=segment["training_window"],
                                    calibration_window=segment["calibration_window"],
                                    evaluation_window=segment["evaluation_window"])
                                first_calibrated = False
                        z = (residual - center) / scale
                        if not math.isfinite(z):
                            raise RuntimeError("nonfinite detector statistic")
                        maturity = "calibrated"
                        calibration_samples = len(calibration)
                        triggers = ["point"] if abs(z) > cfg.point_threshold else []
                        semantics = "standardized forecast residual using frozen segment calibration; not a probability"
                        errors.append(residual)
                        segment_errors.append(residual)
                    method.evidence.append(dict(
                        id=f"{method.id}:{index}", method=method.id, index=index,
                        timestamp=times[index],
                        training_cutoff=(times[index-1] if times[index-1] is not None else index-1),
                        observed=values[index], expected=expected, residual=residual,
                        relative_deviation=relative, standardized_residual=z,
                        signal_maturity=maturity, calibration_samples=calibration_samples,
                        triggers=triggers, score_semantics=semantics))
                    maturity_counts[maturity] += 1
                total_calibration += len(calibration)
                segment["calibration_observed_count"] = len(calibration)
                segment["calibration_required_count"] = cfg.calibration_size
                segment["evaluated_count"] = len(segment_errors)
                segment_diagnostics.append(segment)
            method.diagnostics.update(
                maturity_counts=maturity_counts,
                segments=segment_diagnostics,
                reset_count=len(reset_positions),
                calibration_observed_count=total_calibration,
                calibration_required_count=cfg.calibration_size * len(segment_diagnostics),
                provisional_scale_floor_used_count=provisional_floor_count)
            if errors:
                largest = max(abs(e) for e in errors)
                rmse = largest * math.sqrt(statistics.mean((e / largest) ** 2 for e in errors)) if largest else 0.0
                method.diagnostics.update(held_out_mae=statistics.mean(abs(e) for e in errors),
                                          held_out_rmse=rmse, evaluated_count=len(errors))
            else:
                method.status = "insufficient_history"
                method.applicability = ("no manual segment completed its own training, calibration, and "
                                        "evaluation sequence; earlier evidence is non-triggering")
        except TimeoutError as exc:
            method.status, method.error = "budget_exceeded", str(exc)
        except Exception as exc:
            method.status, method.error = "failed", f"{type(exc).__name__}: {exc}"
    method.limitations.extend([
        "Reference-only and provisional evidence is non-triggering and does not establish an anomaly.",
        "Repeated thresholds are exploratory and do not control a family-wise false-alarm rate.",
        "Consecutive-run patterns describe the point-anomaly stream; they are not an independent probability or incident classification.",
        "Nelson Rules 2, 5, and 6 are applied only to calibrated residuals around a frozen centerline; they indicate a possible location shift, not a change in the full distribution or a business incident.",
        "Nelson Rules 3, 4, and 8 describe residual trend, systematic oscillation, and mixture patterns; they are model/process diagnostics, not location-shift claims.",
        "CUSUM and moving-range thresholds are exploratory and applied to calibrated standardized residuals; they are not probabilities or independently corroborating evidence.",
        "Classical Nelson, CUSUM, and moving-range false-alarm behavior assumes an adequately estimated stable process; residual autocorrelation, non-normal tails, and a short calibration window can change the alert rate.",
        "Trend is fitted before calibration and frozen; changes in growth rate can trigger departures.",
        "Seasonal updates adapt after one season; persistent level changes may stop triggering.",
        "A departure enters the next season's baseline and may produce an echo signal."])
    if season_source == "inferred":
        method.limitations.append("Season length was inferred from a positional training prefix; confirm it with domain knowledge or replay.")
    elif season_source == "fallback":
        method.limitations.append("No stable season was inferred; lag 1 was used as an explicit fallback.")
    if method.diagnostics.get("segments") and any(
            segment["status"] != "calibrated" for segment in method.diagnostics["segments"]):
        method.limitations.append("At least one manual segment did not reach calibrated evaluation; its available evidence is non-triggering.")
    method.runtime_seconds = time.perf_counter() - start
    failed = method.status in ("failed", "budget_exceeded")
    status = ("partial" if method.evidence else "failed") if failed else method.status
    return Result(
        run_id=str(uuid.uuid4()), status=status, input_fingerprint=fingerprint,
        resolved_config=resolved, dependencies=versions(), data_quality=quality,
        methods=[method], observations=episodes([method], request.datasets[0].id),
        anomaly_patterns=anomaly_patterns(
            [method], request.datasets[0].id,
            cusum_k=cfg.cusum_k, cusum_h=cfg.cusum_h,
            moving_range_threshold=cfg.moving_range_threshold),
        limitations=(["No timestamps supplied: evidence and episode intervals use zero-based positions."]
                     if quality["coordinate"] == "position" else []) + [
            "Arrival history is absent: samples are assumed available at event time.",
            "No labels supplied: no detection precision, recall, or business impact is claimed.",
            "Known events and concerns are context only; they do not suppress signals.",
            "Runtime limit is cooperative between samples."],
        suggested_checks=["Check collection gaps, delayed arrivals, and entity/unit definitions.",
                          "Compare flagged periods with known events and an ordinary baseline.",
                          "Review location, trend, oscillation, mixture, and variation patterns together with residual autocorrelation before declaring a regime boundary or reset.",
                          "Check that the declared season and calibration period represent ordinary behavior."],
        runtime_seconds=time.perf_counter()-start,
        stop_reason="runtime_budget" if method.status == "budget_exceeded" else "method_failure" if failed else "completed")


def _namespace_result(result: Result, prefix: str):
    """Give evidence from derived views stable, non-colliding identifiers."""
    evidence_ids = {}
    method_ids = {}
    for method in result.methods:
        old_method = method.id
        method.id = f"{prefix}:{old_method}"
        method_ids[old_method] = method.id
        for item in method.evidence:
            old_evidence = item["id"]
            item["id"] = f"{prefix}:{old_evidence}"
            item["method"] = method.id
            evidence_ids[old_evidence] = item["id"]
    for observation in result.observations:
        observation["id"] = f"{prefix}:{observation['id']}"
        observation["evidence_refs"] = [evidence_ids.get(item, item)
                                         for item in observation["evidence_refs"]]
        observation["supporting_methods"] = [method_ids.get(item, item)
                                               for item in observation["supporting_methods"]]
        observation["quiet_methods"] = [method_ids.get(item, item)
                                          for item in observation["quiet_methods"]]
    for pattern in result.anomaly_patterns:
        pattern["id"] = f"{prefix}:{pattern['id']}"
        pattern["evidence_refs"] = [evidence_ids.get(item, item)
                                     for item in pattern["evidence_refs"]]
    return result


def _aggregate(values, function):
    if function == "sum":
        return math.fsum(values)
    if function == "mean":
        return statistics.mean(values)
    return values[-1]


def _analyze_multi_resolution(request: Request) -> Result:
    """Analyze completed 24-hour aggregates and the underlying sub-day series."""
    start = time.perf_counter()
    cfg = request.config
    ds = request.datasets[0]
    if ds.timestamps is None or ds.frequency is None:
        raise ValueError("multi-resolution-v1 requires timestamped input")
    if cfg.reset_points:
        raise ValueError("multi-resolution-v1 does not yet support reset_points")

    times, values, source_quality = prepare(request)
    if source_quality["missing_count"] or not source_quality["regular"]:
        raise ValueError("multi-resolution-v1 requires complete, regular finalized subperiods")
    match = re.fullmatch(r"([1-9][0-9]*)(s|min|h|d|w)", ds.frequency)
    number, unit = match.groups()
    source_seconds = int(number) * {
        "s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800
    }[unit]
    if source_seconds >= 86400 or 86400 % source_seconds:
        raise ValueError("multi-resolution-v1 requires a sub-day frequency that evenly divides 24 hours")
    samples_per_period = 86400 // source_seconds
    source_delta = timedelta(seconds=source_seconds)
    parsed_times = [datetime.fromisoformat(value) for value in times]
    if parsed_times:
        anchor = (timestamp(cfg.aggregate_anchor, ds.timezone)
                  if cfg.aggregate_anchor else
                  parsed_times[0].astimezone(timezone.utc).replace(
                      hour=0, minute=0, second=0, microsecond=0))
    elif cfg.aggregate_anchor:
        anchor = timestamp(cfg.aggregate_anchor, ds.timezone)
    else:
        anchor = None

    buckets = {}
    if anchor is not None:
        for observed_at, value in zip(parsed_times, values):
            offset = observed_at - anchor
            if offset % source_delta:
                raise ValueError("timestamps must align to the source-frequency grid from aggregate_anchor")
            bucket = math.floor(offset.total_seconds() / 86400)
            buckets.setdefault(bucket, []).append((observed_at, value))

    complete_buckets = []
    partial_buckets = []
    for bucket, items in sorted(buckets.items()):
        record = {
            "bucket": bucket,
            "start": anchor + timedelta(days=bucket),
            "items": items,
        }
        if len(items) == samples_per_period:
            complete_buckets.append(record)
        else:
            partial_buckets.append(record)
    if len(partial_buckets) > 2 or any(
            item is not partial_buckets[0] and item is not partial_buckets[-1]
            for item in partial_buckets):
        raise ValueError("only leading and trailing aggregate periods may be incomplete")
    if partial_buckets and any(
            record["bucket"] not in (min(buckets), max(buckets))
            for record in partial_buckets):
        raise ValueError("an internal aggregate period is incomplete")

    daily_times = [record["start"].isoformat() for record in complete_buckets]
    daily_values = [_aggregate([value for _, value in record["items"]],
                               cfg.aggregate_function)
                    for record in complete_buckets]
    source_incomplete = source_quality.get("incomplete_periods", [])
    incomplete_times = [datetime.fromisoformat(item["timestamp"])
                        for item in source_incomplete if item["timestamp"]]
    incomplete_bucket_numbers = [
        math.floor((observed_at - anchor).total_seconds() / 86400)
        for observed_at in incomplete_times] if anchor is not None else []
    latest_bucket_number = max(
        [*buckets.keys(), *incomplete_bucket_numbers], default=None)
    latest_bucket = buckets.get(latest_bucket_number, [])
    latest_has_incomplete_source = latest_bucket_number in incomplete_bucket_numbers
    latest_is_complete = (len(latest_bucket) == samples_per_period
                          and not latest_has_incomplete_source)
    incomplete_period = None
    if latest_bucket_number is not None and not latest_is_complete:
        period_start = anchor + timedelta(days=latest_bucket_number)
        observed_through = ((latest_bucket[-1][0] + source_delta).isoformat()
                            if latest_bucket else
                            max(incomplete_times).isoformat())
        incomplete_period = {
            "period_status": "incomplete",
            "start": period_start.isoformat(),
            "end": (period_start + timedelta(days=1)).isoformat(),
            "observed_through": observed_through,
            "completed_subperiods": len(latest_bucket),
            "expected_subperiods": samples_per_period,
            "aggregate_function": cfg.aggregate_function,
            "observed_aggregate": (_aggregate(
                [value for _, value in latest_bucket], cfg.aggregate_function)
                if latest_bucket else None),
            "incomplete_source_samples": [
                item for item, bucket in zip(source_incomplete,
                                              incomplete_bucket_numbers)
                if bucket == latest_bucket_number],
            "included_in_completed_period_view": False,
        }

    base_config = cfg.model_copy(update={"recipe": "seasonal-residual-v1",
                                         "reset_points": []})
    context = request.context.model_copy(update={"as_of": None})
    daily_request = Request(
        datasets=[Dataset(id=ds.id, timestamps=daily_times, values=daily_values,
                          frequency="1d", units=ds.units, entity=ds.entity)],
        config=base_config.model_copy(update={
            "season_length": cfg.completed_period_season_length,
            "max_runtime_seconds": max(
                1e-12, cfg.max_runtime_seconds - (time.perf_counter() - start))}),
        context=context)
    daily = _namespace_result(_analyze_seasonal(daily_request), "completed_period")
    resolved_intraday_season = (cfg.intraday_season_length
                                if cfg.intraday_season_length is not None
                                else 7 * samples_per_period)
    intraday_request = Request(
        datasets=[Dataset(id=ds.id, timestamps=times, values=values,
                          frequency=ds.frequency, units=ds.units,
                          entity=ds.entity)],
        config=base_config.model_copy(update={
            "season_length": resolved_intraday_season,
            "max_runtime_seconds": max(
                1e-12, cfg.max_runtime_seconds - (time.perf_counter() - start))}),
        context=context)
    intraday = _namespace_result(_analyze_seasonal(intraday_request), "intraday")
    if incomplete_period:
        period_start = datetime.fromisoformat(incomplete_period["start"])
        period_end = datetime.fromisoformat(incomplete_period["end"])
        current_evidence = [
            item for method in intraday.methods for item in method.evidence
            if item["timestamp"] is not None
            and period_start <= datetime.fromisoformat(item["timestamp"]) < period_end]
        incomplete_period["intraday_evidence_refs"] = [
            item["id"] for item in current_evidence]
        incomplete_period["intraday_triggered_samples"] = [
            item["index"] for item in current_evidence if item["triggers"]]
        for method in intraday.methods:
            method.diagnostics["current_incomplete_period"] = {
                "start": incomplete_period["start"],
                "end": incomplete_period["end"],
                "completed_subperiods": incomplete_period["completed_subperiods"],
                "expected_subperiods": incomplete_period["expected_subperiods"],
                "evidence_count": len(current_evidence),
                "triggered_sample_count": len(
                    incomplete_period["intraday_triggered_samples"]),
            }

    child_statuses = [daily.status, intraday.status]
    if "completed" in child_statuses:
        status = "partial" if any(value in ("failed", "partial")
                                   for value in child_statuses) else "completed"
    elif any(value in ("failed", "partial") for value in child_statuses):
        status = "failed" if all(value == "failed" for value in child_statuses) else "partial"
    elif "insufficient_history" in child_statuses:
        status = "insufficient_history"
    else:
        status = "inapplicable"

    resolved = request.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(
        resolved, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    data_quality = {
        "input_count": source_quality["input_count"],
        "observation_count": source_quality["observation_count"],
        "source": source_quality,
        "periodization": {
            "period": "1d",
            "duration_semantics": "fixed 24-hour windows",
            "anchor": anchor.isoformat() if anchor is not None else None,
            "source_frequency": ds.frequency,
            "expected_subperiods": samples_per_period,
            "aggregate_function": cfg.aggregate_function,
            "completed_period_count": len(complete_buckets),
            "excluded_leading_partial_periods": sum(
                record["bucket"] == min(buckets) and record["bucket"] != max(buckets)
                for record in partial_buckets) if buckets else 0,
        },
        "latest_period_status": "incomplete" if incomplete_period else "complete",
        "incomplete_period": incomplete_period,
        "views": {
            "completed_period": daily.data_quality,
            "intraday": intraday.data_quality,
        },
        "units": ds.units,
        "entity": ds.entity,
    }
    limitations = list(dict.fromkeys(
        ["Completed-period and intraday evidence are correlated views of the same source samples; do not count them as independent confirmation.",
         "The initial multi-resolution recipe uses fixed 24-hour windows, not local calendar days or daylight-saving-aware wall-clock periods.",
         "Source timestamps are interpreted as the starts of finalized subperiods; explicitly marked incomplete source samples are excluded from both views."]
        + daily.limitations + intraday.limitations))
    suggested = list(dict.fromkeys(
        ["Inspect the incomplete-period marker before interpreting current pacing."]
        + daily.suggested_checks + intraday.suggested_checks))
    failed = status in ("failed", "partial")
    return Result(
        run_id=str(uuid.uuid4()), status=status, input_fingerprint=fingerprint,
        resolved_config={**resolved, "derived": {
            "completed_period_season_length": cfg.completed_period_season_length,
            "intraday_season_length": resolved_intraday_season,
            "samples_per_completed_period": samples_per_period}},
        dependencies=versions(), data_quality=data_quality,
        methods=[*daily.methods, *intraday.methods],
        observations=[*daily.observations, *intraday.observations],
        anomaly_patterns=[*daily.anomaly_patterns, *intraday.anomaly_patterns],
        limitations=limitations, suggested_checks=suggested,
        runtime_seconds=time.perf_counter() - start,
        stop_reason="method_failure" if failed else "completed")
