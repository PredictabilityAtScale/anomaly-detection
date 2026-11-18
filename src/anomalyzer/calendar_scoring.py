"""Chronological scoring and calibration for opt-in calendar datasets."""
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import math
import statistics
import time
import uuid

from .budget import RuntimeBudget
from .calendar_baseline import CALIBRATION_DATES, PEER_DATES, TIERS, CalendarIndex, day_group, week
from .contracts import Context, DataPolicy, MethodResult, Result
from .events import fingerprint
from .evidence import anomaly_patterns, episodes
from .readiness import MAX_TRAINING_CHECK, assess_segment, summarize_segments
from .registry import versions
from .robust import EXTREME_Z, extreme_indices
from .sparse import active_resets, cadence_seconds, normalize
from .validation import timestamp


@dataclass
class Calibration:
    minimum_dates: int
    minimum_weeks: int
    records: list = field(default_factory=list)
    dates: set = field(default_factory=set)
    weeks: set = field(default_factory=set)
    center: float = 0.0
    squared_deviations: float = 0.0
    frozen: dict | None = None

    def estimate(self, config):
        if self.frozen:
            return (self.frozen["center"], self.frozen["scale"],
                    self.frozen["retained_residual_count"], "calibrated")
        count = len(self.records)
        if count < 3:
            return None, None, count, "reference_only"
        raw_scale = math.sqrt(max(0.0, self.squared_deviations) / (count - 1))
        return self.center, max(raw_scale, config.scale_floor), count, "provisional"

    def admit(self, record, day, times, config, training, check, *, season_length=None):
        self.records.append(record)
        self.dates.add(day)
        self.weeks.add(week(day))
        delta = record["residual"] - self.center
        self.center += delta / len(self.records)
        self.squared_deviations += delta * (record["residual"] - self.center)
        if not self.supports(len(self.records), self.dates, self.weeks, config):
            return
        check()
        raw = [item["residual"] for item in self.records]
        offsets, screening = extreme_indices(raw, config.scale_floor) if config.outlier_handling == "robust" else ([], None)
        excluded = set(offsets)
        retained = [item for offset, item in enumerate(self.records) if offset not in excluded]
        dates = {item["day"] for item in retained}
        weeks = {week(day) for day in dates}
        if not self.supports(len(retained), dates, weeks, config):
            return
        residuals = [item["residual"] for item in retained]
        center, raw_scale = statistics.mean(residuals), statistics.stdev(residuals)
        positions = [self.records[offset]["index"] for offset in offsets]
        index = record["index"]
        self.frozen = dict(center=center, scale=max(raw_scale, config.scale_floor), raw_scale=raw_scale,
                           scale_floor_used=raw_scale < config.scale_floor, cutoff=times[index],
                           effective_from_index=index + 1, retained_residual_count=len(retained),
                           target_date_count=len(dates), target_week_count=len(weeks),
                           excluded_residual_indexes=positions, residual_screening=screening)
        self.frozen["detection_readiness"] = assess_segment(
            training, self.records, positions, season_length, "none", config.scale_floor)
        if self.frozen["scale_floor_used"]:
            readiness = self.frozen["detection_readiness"]
            if readiness["status"] == "supported":
                readiness["status"] = "caution"
                readiness["reasons"].clear()
            readiness["reasons"].append("The frozen residual scale uses the configured scale floor.")

    def supports(self, count, dates, weeks, config):
        return count >= config.calibration_size and len(dates) >= self.minimum_dates and len(weeks) >= self.minimum_weeks


class AvailableVersions:
    def __init__(self, quality):
        self.samples = quality["samples"]
        self.versions = {index: (tuple(cutoff for cutoff, _ in history), tuple(sample for _, sample in history))
                         for index, history in quality.get("_calendar_versions", {}).items()}
        self.replacements = {}
        self.visible = self.samples.copy()
        self.changed_at = sorted((cutoff, index, version, row)
                                 for index, (cutoffs, rows) in self.versions.items()
                                 for version, (cutoff, row) in enumerate(zip(cutoffs, rows)))
        self.position = 0
        for index, (_, rows) in self.versions.items():
            first = rows[0]
            self.visible[index] = {**first, "value": None, "original_value": None,
                                   "coverage": "unknown", "reason": "not_available_at_target_start",
                                   "available_at": None, "revision_id": None}

    def advance(self, cutoff):
        while self.position < len(self.changed_at) and self.changed_at[self.position][0] <= cutoff:
            _, index, _, row = self.changed_at[self.position]
            self.visible[index] = row
            self.position += 1

    def peer(self, index):
        row = self.visible[index]
        value = row["value"]
        replacement = self.replacements.get(index)
        replaced = replacement is not None and replacement[0] is row
        if replaced:
            value = replacement[1]
        version = ((row["available_at"], row["revision_id"]) if value is not None
                   and (row["available_at"] is not None or row["revision_id"] is not None)
                   else None)
        reason = row["coverage"] if row["coverage"] in ("excluded", "incomplete") else "unknown"
        return value, reason, version, replaced

    def protect_calibration(self, state):
        if state.frozen:
            excluded = set(state.frozen["excluded_residual_indexes"])
            for record in state.records:
                if record["index"] in excluded:
                    self.replacements[record["index"]] = (record["sample"], record["expected"])


def _calendar_parameters(policy, zone, width_override):
    return dict(**policy.model_dump(), timezone=zone, peer_dates=PEER_DATES,
                min_date_slot_fraction=0.8, min_calibration_target_dates=CALIBRATION_DATES,
                tiers=[dict(asdict(tier), clock_width_minutes=tier.clock_width_minutes
                            if width_override is None else width_override) for tier in TIERS],
                week_starts_on="Monday", clock_distance="circular within each candidate date",
                historical_cutoff="target bucket start UTC", guard_endpoint="peer bucket end at or before cutoff",
                date_reduction="mean of eligible native slots",
                robust_date_reduction="discard lowest and highest date representative; newest-to-oldest nominal weight ratio 1.5",
                include_date_reduction="newest supported date representative")


def _selection_record(selection, weights, parameters_id, segment, records):
    peers = [
        dict(local_date=peer.day.isoformat(), week_start=(peer.day - timedelta(days=peer.day.weekday())).isoformat(),
             peer_indexes=peer.indexes, eligible_slots=len(peer.indexes), expected_slots=peer.expected_slots,
             representative=peer.representative, weight=weight,
             historical_versions=peer.version_overrides, reference_replacements=peer.reference_replacements)
        for peer, weight in zip(selection.peers, weights)
    ]
    record = dict(selector=parameters_id, segment_start_index=segment, tier=selection.tier.name,
                  dates=peers, distinct_dates=len(peers), distinct_weeks=len({week(peer.day) for peer in selection.peers}))
    selection_id = fingerprint(record)
    records.setdefault(selection_id, record)
    return selection_id


def _score(ds, cfg, times, quality, step, resets, method, budget, parameters, *,
           calibration_stop, width_override, audit_selections):
    """Only admit the target after its forecast and reference action are decided."""
    diagnostics = method.diagnostics
    targets, selections = diagnostics["targets"], diagnostics["selections"]
    calibrations, boundaries = diagnostics["calibrations"], diagnostics["pattern_boundaries"]
    if not times:
        return
    instants = [timestamp(value) for value in times]
    grid = CalendarIndex(instants, ds.timezone, step, budget.check)
    available = AvailableVersions(quality)
    policy = ds.data_policy or DataPolicy()
    selector_id = fingerprint(parameters)
    segments = diagnostics["segments"]
    states = {}
    resets = set(resets)
    segment_start = 0
    training = []
    overrides = diagnostics["scoring_sample_overrides"]
    previous_missing = False
    guard_minutes = ds.calendar_reference.guard_minutes
    minute = timedelta(minutes=1)
    earliest_instant = datetime.min.replace(tzinfo=timezone.utc)
    for index, (instant, local) in enumerate(zip(instants, grid.locals)):
        budget.check()
        available.advance(instant)
        sample = available.visible[index]
        if sample != available.samples[index]:
            overrides[index] = sample
        value = sample["value"]
        restart = (index > 0 and policy.reference_gaps == "restart"
                   and previous_missing and value is not None)
        previous_missing = value is None
        if index == 0 or index in resets or restart:
            segment_start = index
            training = []
            segment = dict(start_position=index, origin=times[index], reason="explicit_reset" if index in resets
                           else "reference_gap" if restart else "series_origin", calibration_keys=[],
                           training_reference_coverage=Counter())
            segments.append(segment)
            if index:
                boundaries.append(index)
        day = local.date()
        training_position = index - segment_start < cfg.training_size
        if training_position and value is not None and len(training) < MAX_TRAINING_CHECK:
            training.append(value)
        target = dict(index=index, timestamp=times[index], local_timestamp=local.isoformat(),
                      local_date=day.isoformat(), utc_offset_seconds=int(local.utcoffset().total_seconds()),
                      fold=local.fold, segment_start_index=segment_start, segment_origin=times[segment_start],
                      lookback_start=max(instant - timedelta(days=ds.calendar_reference.lookback_days),
                                         instants[segment_start]).isoformat(),
                      guard_cutoff=((instant - guard_minutes * minute).isoformat()
                                    if guard_minutes <= (instant - earliest_instant) // minute else None),
                      observed=sample["original_value"], coverage=sample["coverage"], maturity="unavailable",
                      reason=None, dst_exclusion=grid.dst[index])
        targets.append(target)
        if value is None or grid.dst[index]:
            target["reason"] = sample["reason"] if value is None else "dst_target_exclusion"
            if training_position:
                segment["training_reference_coverage"][target["reason"]] += 1
            continue
        selection = grid.select(index, segment_start, ds.calendar_reference, available.peer,
                                budget.check, widths=width_override)
        target.update(age_tier=selection.age_tier.name if selection.age_tier else None,
                      attempts=selection.attempts)
        if selection.tier is None:
            target["reason"] = selection.reason
            if training_position:
                segment["training_reference_coverage"][selection.reason] += 1
            continue
        tier = selection.tier
        group = day_group(day, tier.same_weekday)
        key = (segment_start, selector_id, tier.name, group)
        if key not in states:
            key_id = f"{segment_start}:{selector_id}:{tier.name}:{group}"
            states[key] = (key_id, Calibration(CALIBRATION_DATES, tier.calibration_weeks))
            segment["calibration_keys"].append(key_id)
            calibrations[key_id] = dict(segment_start_index=segment_start, selector=selector_id,
                                        timezone=ds.timezone, tier=tier.name, day_group=group,
                                        clock_width_minutes=selection.attempts[-1]["clock_width_minutes"])
        key_id, state = states[key]
        expected, weights = selection.expectation(cfg.outlier_handling)
        selection_id = (_selection_record(selection, weights, selector_id, segment_start, selections)
                        if audit_selections else None)
        center, scale, count, maturity = state.estimate(cfg)
        if training_position:
            segment["training_reference_coverage"]["supported_reference"] += 1
        residual = value - expected
        z = (residual - center) / scale if scale is not None else None
        if not math.isfinite(residual) or (z is not None and not math.isfinite(z)):
            raise ValueError("nonfinite calendar residual or standardized residual")
        relative = residual / abs(expected) if expected else None
        calibrated = maturity == "calibrated"
        protected = calibrated and cfg.outlier_handling == "robust" and abs(z) > EXTREME_Z
        frozen = state.frozen
        reason = None if calibrated else "training_prefix" if training_position else "uncalibrated_calendar_key"
        target.update(selection_id=selection_id, tier=tier.name, fallback_used=tier != selection.age_tier,
                      calibration_key=key_id, calibration_residual_count=count,
                      calibration_date_count=frozen["target_date_count"] if frozen else len(state.dates),
                      calibration_week_count=frozen["target_week_count"] if frozen else len(state.weeks),
                      maturity=maturity, reason=reason)
        method.evidence.append(dict(
            id=f"{method.id}:{index}", method=method.id, index=index, timestamp=times[index],
            training_cutoff=times[max(segment_start, min(index - 1, segment_start + cfg.training_size - 1))],
            observed=value, expected=expected, residual=residual,
            relative_deviation=relative if relative is None or math.isfinite(relative) else None,
            standardized_residual=z, signal_maturity=maturity, calibration_samples=count,
            triggers=["point"] if calibrated and abs(z) > cfg.point_threshold else [],
            score_semantics="Calendar prediction residual. The point criterion uses the absolute frozen standardized residual.",
            excluded_from_model=protected, model_value=expected if protected else value,
            exclusion_reason="extreme_calibrated_residual" if protected else None,
            reference_action="use_expected" if protected else "use_observed"))
        if not calibrated and not training_position and index < calibration_stop:
            state.admit(dict(index=index, residual=residual, expected=expected, day=day, sample=sample),
                        day, times, cfg, training, budget.check)
            available.protect_calibration(state)
        if protected:
            available.replacements[index] = (sample, expected)
    for key_id, state in states.values():
        calibrations[key_id].update(
            candidate_residual_count=len(state.records), target_dates=len(state.dates),
            target_weeks=len(state.weeks), frozen=state.frozen)


def analyze_calendar(ds, cfg, context, budget=None, prepared=None, *,
                     calibration_stop=None, clock_width_override=None, audit_selections=True):
    """Run the public selector or the benchmark's predeclared sensitivity."""
    started = time.perf_counter()
    ds.calendar_reference.validate_settings(cfg)
    budget = budget or RuntimeBudget(cfg.max_runtime_seconds)
    context = Context.model_validate(context or {})
    times, _, source_quality = prepared or normalize(ds, cfg, context, budget)
    quality = {key: value for key, value in source_quality.items() if key != "_calendar_versions"}
    resets = active_resets(cfg.reset_points, times, ds.timezone, context.as_of)
    step = timedelta(seconds=cadence_seconds(ds.frequency))
    parameters = _calendar_parameters(ds.calendar_reference, ds.timezone, clock_width_override)
    parameters["outlier_handling"] = cfg.outlier_handling
    config = cfg.model_dump(mode="json", exclude={"season_length"})
    method = MethodResult(
        id="local_calendar", status="insufficient_history",
        applicability="earlier supported local dates on one native elapsed grid",
        parameters=dict(config, calendar_reference=parameters, resolved_reset_positions=resets,
                        benchmark_calibration_stop=calibration_stop),
        diagnostics=dict(targets=[], selections={}, calibrations={}, segments=[],
                         pattern_boundaries=[], scoring_sample_overrides={}),
        limitations=[
            "A recency guard delays contamination. A sustained departure can become part of later reference history.",
            "Calibration screening can protect later references once the key freezes. Earlier reference decisions and raw observations are preserved.",
            "Calendar residuals and their patterns are evidence of a modeled departure. Incident confirmation and business impact require external evidence.",
            "Unannotated complete observations are assumed available at bucket start. Supplied delivery and completion metadata are caller assertions.",
        ])
    try:
        _score(ds, cfg, times, source_quality, step, resets, method, budget, parameters,
               calibration_stop=len(times) if calibration_stop is None else calibration_stop,
               width_override=clock_width_override, audit_selections=audit_selections)
        if any(item["signal_maturity"] == "calibrated" for item in method.evidence):
            method.status = "completed"
    except TimeoutError as exc:
        method.status, method.error = "budget_exceeded", str(exc)
    except (ArithmeticError, ValueError, RuntimeError) as exc:
        method.status, method.error = "failed", f"{type(exc).__name__}: {exc}"
    diagnostics = method.diagnostics
    diagnostics["unavailable"] = [dict(index=item["index"], reason=item["reason"])
                                  for item in diagnostics["targets"] if item["reason"]]
    if len(diagnostics["targets"]) < len(times):
        diagnostics["unprocessed_indexes"] = [len(diagnostics["targets"]), len(times)]
    checks = [record.get("frozen") or {} for record in diagnostics["calibrations"].values()]
    readiness = summarize_segments(checks, method.status, unit="calibration_key")
    readiness["calendar_support"] = {
        "fixed_lag_repeatability": "not applicable to calendar selector",
        "training_buckets_by_segment": [
            dict(segment_start_index=segment["start_position"], **segment["training_reference_coverage"])
            for segment in diagnostics["segments"]],
        "supported_calibration_buckets": sum(record.get("candidate_residual_count", 0)
                                             for record in diagnostics["calibrations"].values()),
    }
    diagnostics["detection_readiness"] = readiness
    quality["calendar_reference"] = parameters
    if diagnostics["targets"]:
        latest = diagnostics["targets"][-1]
        quality["calendar_latest_target"] = {key: latest.get(key) for key in
                                             ("index", "timestamp", "tier", "maturity", "reason", "dst_exclusion")}
    observations, patterns = [], []
    bounds = [0, *diagnostics["pattern_boundaries"], len(times)]
    indexes = [item["index"] for item in method.evidence]
    for segment, (start, end) in enumerate(zip(bounds, bounds[1:])):
        segment_method = method.model_copy(update={"evidence": method.evidence[
            bisect_right(indexes, start-1):bisect_right(indexes, end-1)]})
        for row in episodes([segment_method], ds.id):
            row["id"] = f"segment:{segment}:{row['id']}"
            observations.append(row)
        for row in anomaly_patterns([segment_method], ds.id, cusum_k=cfg.cusum_k,
                                    cusum_h=cfg.cusum_h, moving_range_threshold=cfg.moving_range_threshold):
            row["id"] = f"segment:{segment}:{row['id']}"
            patterns.append(row)
    resolved = dict(datasets=[ds.model_dump(mode="json")], config=config,
                    context=context.model_dump(mode="json"))
    method.runtime_seconds = time.perf_counter() - started
    failed = method.status in ("budget_exceeded", "failed")
    return Result(run_id=str(uuid.uuid4()), status=("partial" if method.evidence else "failed") if failed else method.status,
                  input_fingerprint=fingerprint([resolved, parameters]), resolved_config=resolved,
                  dependencies=versions(), data_quality=quality, methods=[method], observations=observations,
                  anomaly_patterns=patterns, limitations=method.limitations,
                  suggested_checks=["Review date support, coverage and calibrated residuals together."],
                  runtime_seconds=method.runtime_seconds,
                  stop_reason="runtime_budget" if method.status == "budget_exceeded" else
                  "method_failure" if failed else "completed")
