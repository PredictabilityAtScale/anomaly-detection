"""Schema-1.1 native and complete-day evidence with independent view eligibility."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import time
import uuid

from .budget import RuntimeBudget
from .cases import compose_cases, target_entities
from .contracts import Context, DataPolicy, DatasetV11, RelationshipResult, RequestV11, ResultV11
from .registry import versions
from .sparse import active_resets, cadence_seconds, normalize
from .validation import timestamp


def view_cases(datasets, relationships, request):
    result = []
    for resolution in sorted({item.resolution for item in datasets + relationships if item.resolution}):
        cases = compose_cases([d for d in datasets if d.resolution == resolution],
                              [r for r in relationships if r.resolution == resolution],
                              target_entities(request))
        for case in cases:
            case.resolution = resolution
            case.id = f"{resolution}:{case.id}"
            case.revision_id = f"{resolution}:{case.revision_id}"
            case.non_claims.append("Native and completed-day views reuse the same observations; they are not independent confirmation.")
        result.extend(cases)
    return result


def label_view(result, label):
    """Namespace evidence identifiers without changing original source IDs or times."""
    for collection in (result.dataset_results, result.relationship_results):
        for item in collection:
            item.resolution = label
            evidence_ids, pattern_ids, method_ids = {}, {}, {}
            for method in item.methods:
                old = method.id
                method.id = f"{label}:{old}"
                method_ids[old] = method.id
                for row in method.evidence:
                    old_id = row["id"]
                    row["id"] = f"{label}:{old_id}"
                    row["method"] = method.id
                    evidence_ids[old_id] = row["id"]
            for pattern in item.anomaly_patterns:
                old_id = pattern["id"]
                pattern["id"] = f"{label}:{old_id}"
                pattern_ids[old_id] = pattern["id"]
                pattern["evidence_refs"] = [evidence_ids.get(ref, ref) for ref in pattern["evidence_refs"]]
            for observation in item.observations:
                observation["id"] = f"{label}:{observation['id']}"
                observation["evidence_refs"] = [evidence_ids.get(ref, ref) for ref in observation["evidence_refs"]]
                observation["supporting_methods"] = [method_ids.get(ref, ref) for ref in observation["supporting_methods"]]
                observation["quiet_methods"] = [method_ids.get(ref, ref) for ref in observation["quiet_methods"]]
            for assessment in item.assessments:
                assessment.id = f"{label}:{assessment.id}"
                assessment.evidence_refs = [evidence_ids.get(ref, ref) for ref in assessment.evidence_refs]
                if "method" in assessment.baseline:
                    assessment.baseline["method"] = method_ids.get(assessment.baseline["method"], assessment.baseline["method"])
                if "pattern_ids" in assessment.baseline:
                    assessment.baseline["pattern_ids"] = [pattern_ids.get(ref, ref) for ref in assessment.baseline["pattern_ids"]]
            item.data_quality["resolution"] = label


def daily_dataset(ds, cfg, context, budget):
    """Sum only wholly observed finalized additive children. Never average ratios."""
    times, values, quality = normalize(ds, cfg, context, budget)
    measurements = quality["rule_values"]
    policy = ds.data_policy or DataPolicy()
    unsupported = None
    if policy.observation_basis != "calendar":
        unsupported = "completed-day aggregation is unavailable on event_index"
        seconds = None
    else:
        seconds = cadence_seconds(ds.frequency)
        if seconds >= 86400 or 86400 % seconds:
            unsupported = "source cadence must evenly divide a fixed 24-hour day"
    if policy.measurement != "additive_volume" or cfg.aggregate_function != "sum":
        unsupported = "completed-day view requires additive_volume and sum; per-event percentages/ratios are not averaged"
    if unsupported:
        return (DatasetV11(id=ds.id, entity=ds.entity, units=ds.units, timestamps=[], values=[],
                           frequency="1d", data_policy=DataPolicy()),
                [dict(complete=False, reason=unsupported)], set())
    anchor = timestamp(cfg.aggregate_anchor, ds.timezone) if cfg.aggregate_anchor else (
        datetime.fromisoformat(times[0]).replace(hour=0, minute=0, second=0, microsecond=0) if times else None)
    buckets = {}
    for index, observed_at in enumerate(times):
        budget.check()
        moment = datetime.fromisoformat(observed_at)
        if seconds and anchor and (moment-anchor).total_seconds() % seconds:
            raise ValueError("source timestamps are off the aggregate_anchor grid")
        bucket = int((moment-anchor).total_seconds() // 86400)
        buckets.setdefault(bucket, []).append(index)
    daily_times, daily_values, coverage, records, available_at = [], [], [], [], []
    reset_indexes = active_resets(cfg.reset_points, times, ds.timezone, context.as_of)
    reset_times = [datetime.fromisoformat(times[index]) for index in reset_indexes]
    daily_reset_times = set()
    if buckets:
        for bucket in range(min(buckets), max(buckets)+1):
            budget.check()
            start = anchor + timedelta(days=bucket)
            indexes = buckets.get(bucket, [])
            expected = 86400 // seconds if seconds and 86400 % seconds == 0 else None
            inside_resets = [t for t in reset_times if start <= t < start+timedelta(days=1)]
            for t in inside_resets:
                daily_reset_times.add((start if t == start else start+timedelta(days=1)).isoformat())
            complete = (not unsupported and len(indexes) == expected and
                        all(measurements[i] is not None for i in indexes))
            excluded = any(t != start for t in inside_resets) or any(quality["samples"][i]["coverage"] == "excluded" for i in indexes)
            value = math.fsum(measurements[i] for i in indexes) if complete else None
            if value is not None and not math.isfinite(value):
                value, complete = None, False
            reason = ("missing_or_unfinished_children" if not complete else
                      "reset_inside_aggregate" if any(t != start for t in inside_resets) else
                      "excluded_model_child" if excluded else None)
            daily_times.append(start.isoformat())
            daily_values.append(value)
            known_arrivals = [quality["samples"][i]["available_at"] for i in indexes if quality["samples"][i]["available_at"] and measurements[i] is not None]
            available_at.append(max([*known_arrivals, *[times[i] for i in indexes]]) if known_arrivals else None)
            coverage.append("excluded" if complete and excluded else "complete" if complete else "incomplete")
            records.append(dict(timestamp=start.isoformat(), complete=bool(complete), reason=reason,
                expected_children=expected, usable_children=sum(measurements[i] is not None for i in indexes),
                model_eligible=bool(complete and not excluded),
                policy_zero_children=sum(quality["samples"][i]["reason"] == "confirmed_empty_additive_volume" for i in indexes),
                source_input_indexes=[raw for i in indexes for raw in quality["samples"][i]["source_indexes"]],
                source_grid_indexes=indexes, observed_sum=(math.fsum(measurements[i] for i in indexes if measurements[i] is not None)
                    if any(measurements[i] is not None for i in indexes) else None),
                aggregate_value=value))
    child = DatasetV11(id=ds.id, entity=ds.entity, units=ds.units,
        timestamps=daily_times, values=daily_values, frequency="1d", coverage=coverage, available_at=available_at,
        data_policy=DataPolicy(measurement="additive_volume", reference_gaps=policy.reference_gaps,
            minimum_phase_samples=policy.minimum_phase_samples, change_max_gap_seconds=policy.change_max_gap_seconds),
        rules=ds.completed_period_rules)
    return child, records, daily_reset_times


def analyze_multi_request(request, budget=None):
    from .orchestrator import analyze_relationships
    started = time.perf_counter()
    budget = budget or RuntimeBudget(request.config.max_runtime_seconds)
    # Every child source is explicitly prepared so incomplete/unknown grid slots survive.
    native_sources = [d.model_copy(update={"data_policy": d.data_policy or DataPolicy()}) for d in request.datasets]
    native_config = request.config.model_copy(update={"recipe": "seasonal-residual-v1",
        "season_length": request.config.intraday_season_length or request.config.season_length})
    native_request = request.model_copy(update={"datasets": native_sources, "config": native_config})
    native = analyze_relationships(native_request, _budget=budget)
    label_view(native, "intraday")
    sources, aggregation, reset_times = [], {}, set()
    for ds in native_sources:
        try:
            child, records, resets = daily_dataset(ds, request.config, request.context, budget)
            sources.append(child)
            aggregation[ds.id] = records
            reset_times.update(resets)
        except (ValueError, TimeoutError) as exc:
            sources.append(DatasetV11(id=ds.id, entity=ds.entity, units=ds.units,
                                     timestamps=[], values=[], frequency="1d", data_policy=DataPolicy()))
            aggregation[ds.id] = {"error": str(exc)}
    all_times = {t for ds in sources for t in ds.timestamps}
    daily_config = request.config.model_copy(update={"recipe": "seasonal-residual-v1",
        "season_length": request.config.completed_period_season_length,
        "reset_points": sorted(t for t in reset_times if t in all_times and any(t != ds.timestamps[0] for ds in sources if ds.timestamps))})
    daily_relationships = [r.model_copy(update={"rules": r.completed_period_rules})
                           for r in request.relationships if r.kind in ("ratio", "difference")]
    daily_request = request.model_copy(update={"datasets": sources, "config": daily_config, "relationships": daily_relationships})
    daily = analyze_relationships(daily_request, _budget=budget)
    for relationship in request.relationships:
        if relationship.kind not in ("ratio", "difference"):
            daily.relationship_results.append(RelationshipResult(relationship_id=relationship.id, kind=relationship.kind,
                status="inapplicable", definition=relationship.model_dump(mode="json"),
                applicability="completed-day view supports ratio-of-sums and differences of compatible additive sums only",
                data_quality={"unavailable_count": 0}, lineage=[], methods=[], observations=[], anomaly_patterns=[], assessments=[],
                limitations=["No hourly lag, normalization scale or joint-condition threshold was silently reinterpreted as daily input."]))
    label_view(daily, "completed_period")
    for item in daily.dataset_results:
        item.data_quality["aggregation"] = aggregation[item.dataset_id]
        item.limitations.append("Incomplete sums are progress only, never completed consumption; ratio views divide summed compatible source quantities.")
    for relationship in daily.relationship_results:
        for point in relationship.lineage:
            for source_id, source_index in point.source_indexes.items():
                records = aggregation[source_id]
                if isinstance(records, list) and 0 <= source_index < len(records):
                    point.source_input_indexes[source_id] = records[source_index].get("source_input_indexes", [])
    datasets = native.dataset_results + daily.dataset_results
    relationships = native.relationship_results + daily.relationship_results
    status = "completed" if native.status == daily.status == "completed" else "partial"
    resolved = request.model_dump(mode="json")
    return ResultV11(run_id=str(uuid.uuid4()), status=status,
        input_fingerprint=hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest(),
        resolved_config=resolved, dependencies=versions(), dataset_results=datasets,
        relationship_results=relationships, cases=view_cases(datasets, relationships, request),
        limitations=["Views are correlated evidence, not independent incident votes.",
                     "Schema-1.1 multi-resolution uses a frozen seasonal child recipe and fixed UTC 24-hour periods; adaptive children and local-calendar/DST aggregation remain unsupported.",
                     "Caller rules are evaluated in each view's declared units; change and sum thresholds require a suitable per-view interpretation."],
        runtime_seconds=time.perf_counter()-started, stop_reason="runtime_budget" if budget.remaining == 0 else "completed")


def analyze_sparse_views(ds, cfg, context, budget=None):
    if budget:
        budget.check()
    return analyze_multi_request(RequestV11(schema_version="1.1", datasets=[ds], config=cfg,
                                 context=Context.model_validate(context or {})), budget)
