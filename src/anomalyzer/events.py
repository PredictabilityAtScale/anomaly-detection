"""event-identity-v1: stable logical identity, original time, and explicit order.

Timestamp/ID sorting is a reproducible layout, never an ordering assertion.
The caller owns stable IDs, comparable populations and any trusted sequence.
"""
from collections import Counter
import hashlib
import json
import re

from .validation import timestamp


CONTRACT = "event-identity-v1"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def event_token(event_id, entity):
    return fingerprint(dict(event_id=event_id, entity=entity))


def event_resets(points, times, policy, zone, as_of):
    """Timestamp resets start a whole cohort; positions cannot split unordered ties."""
    cutoff = timestamp(as_of, zone) if as_of else None
    resolved = []
    for point in points:
        if isinstance(point, int):
            if cutoff and point >= len(times):
                continue
            index = point
        else:
            date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", point))
            normalized = timestamp(point + "T00:00:00Z" if date_only else point, zone)
            if cutoff and normalized > cutoff:
                continue
            matches = [i for i, value in enumerate(times)
                       if value[:10] == point] if date_only else [
                           i for i, value in enumerate(times) if value == normalized.isoformat()]
            if not matches:
                raise ValueError("event reset must match an available timestamp")
            if date_only and len({times[i] for i in matches}) != 1:
                raise ValueError("date event reset must identify one timestamp cohort")
            index = matches[0]
        if index <= 0 or index >= len(times):
            raise ValueError("event reset is outside available positions 1..n-1")
        if policy.event_order != "trusted_sequence" and times[index] == times[index-1]:
            raise ValueError("reset position cannot split an unordered timestamp cohort")
        resolved.append(index)
    if len(set(resolved)) != len(resolved):
        raise ValueError("event resets resolve to duplicate positions")
    return sorted(resolved)


def normalize_events(ds, cfg, context, budget):
    policy = ds.data_policy
    cutoff = timestamp(context.as_of, ds.timezone) if context.as_of else None
    rows = {}
    statuses = ds.period_statuses or ["complete"] * len(ds.values)
    for index, event_id in enumerate(ds.event_ids):
        budget.check()
        if event_id in rows:
            raise ValueError("duplicate logical event IDs; deduplicate retry deliveries before analysis")
        observed = timestamp(ds.timestamps[index], ds.timezone)
        supplied_at = ds.available_at[index] if ds.available_at else None
        available = timestamp(supplied_at, ds.timezone) if supplied_at else observed
        if available < observed:
            raise ValueError("available_at cannot precede event time")
        value, status = ds.values[index], statuses[index]
        coverage = ds.coverage[index] if ds.coverage else (
            "incomplete" if status == "incomplete" else "complete" if value is not None else "unknown")
        if status == "incomplete" and coverage != "incomplete":
            raise ValueError("incomplete period_status conflicts with coverage")
        rows[event_id] = dict(event_id=event_id, observed=observed,
            original_timestamp=ds.timestamps[index], source_index=index, initial_value=value,
            initial_available_at=available, initial_coverage=coverage,
            event_sequence=ds.event_sequence[index] if ds.event_sequence is not None else None,
            original_value=value, coverage=coverage, period_status=status,
            available_at=available, availability_supplied=supplied_at is not None, revision_id=None)
    # Validate the complete declared sequence independently of availability filtering.
    if policy.event_order == "trusted_sequence":
        ordered = sorted(rows.values(), key=lambda row: row["event_sequence"])
        if any(a["observed"] > b["observed"] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("trusted event_sequence contradicts original timestamp order")
    revision_keys, revision_ids = set(), set()
    for revision in ds.revisions:
        budget.check()
        if revision.event_id not in rows:
            raise ValueError("revision event_id must identify an existing logical event")
        row = rows[revision.event_id]
        observed = timestamp(revision.timestamp, ds.timezone)
        available = timestamp(revision.available_at, ds.timezone)
        if observed != row["observed"]:
            raise ValueError("event revision cannot change the original event timestamp")
        if available <= row["initial_available_at"]:
            raise ValueError("event revision must be available strictly after the initial observation")
        key, identity = (revision.event_id, available), (revision.event_id, revision.revision_id)
        if key in revision_keys or identity in revision_ids:
            raise ValueError("duplicate event revision identity or availability")
        revision_keys.add(key)
        revision_ids.add(identity)
        if cutoff and available > cutoff:
            continue
        if available > row["available_at"]:
            row.update(original_value=revision.value, coverage=revision.coverage,
                       period_status="incomplete" if revision.coverage == "incomplete" else "complete",
                       available_at=available, revision_id=revision.revision_id)
            row["availability_supplied"] = True
    visible = [row for row in rows.values() if not cutoff or row["available_at"] <= cutoff]
    visible.sort(key=lambda row: (row["observed"],
        row["event_sequence"] if policy.event_order == "trusted_sequence" else row["event_id"]))
    times, values, rule_values, samples = [], [], [], []
    for index, row in enumerate(visible):
        budget.check()
        state, original = row["coverage"], row["original_value"]
        if state == "empty" and original not in (None, 0):
            raise ValueError("empty coverage conflicts with nonzero observed value")
        if state in ("complete", "revised") and original is None:
            state = "unknown"
        value = original if state in ("complete", "revised") else None
        reason = None if value is not None else {
            "empty": "empty_preserved_as_missing", "unknown": "collection_unknown",
            "incomplete": "period_incomplete", "excluded": "explicit_model_exclusion"}[state]
        observed = row["observed"].isoformat()
        times.append(observed)
        values.append(value)
        rule_values.append(original if state == "excluded" else value)
        selected_revision = fingerprint(dict(event_id=row["event_id"], timestamp=observed,
            value=original, coverage=state, available_at=row["available_at"].isoformat(),
            revision_id=row["revision_id"], event_sequence=row["event_sequence"]))
        samples.append(dict(index=index, event_id=row["event_id"], event_sequence=row["event_sequence"],
            original_timestamp=row["original_timestamp"], source_index=row["source_index"],
            source_indexes=[row["source_index"]], original_value=original, initial_value=row["initial_value"],
            original_period_status=row["period_status"], original_coverage=row["coverage"],
            origin="revision" if row["revision_id"] else "supplied", value=value, coverage=state,
            reason=reason, available_at=row["available_at"].isoformat() if row["availability_supplied"] else None, revision_id=row["revision_id"],
            selected_revision=selected_revision))
    cohorts = []
    for i, observed in enumerate(times):
        if not cohorts or observed != times[cohorts[-1][0]]:
            cohorts.append([])
        cohorts[-1].append(i)
    ties = [group for group in cohorts if len(group) > 1]
    ambiguous = [i for group in ties for i in group] if policy.event_order == "timestamp" else []
    boundaries = sorted({p for i in ambiguous for p in (i, i+1) if p < len(times)})
    quality = dict(input_count=len(ds.values), grid_count=len(times),
        observation_count=sum(v is not None for v in rule_values),
        reported_measurement_count=sum(v is not None for v in rule_values),
        complete_count=sum(v is not None for v in values),
        incomplete_count=sum(s["coverage"] == "incomplete" for s in samples),
        incomplete_periods=[dict(index=s["index"], timestamp=times[s["index"]],
            event_id=s["event_id"], observed=s["original_value"], period_status="incomplete")
            for s in samples if s["coverage"] == "incomplete"],
        missing_count=sum(v is None for v in values), duplicate_count=0,
        regular=True, timestamp_normalization="UTC", coordinate="event_index",
        regularity_basis="explicit_comparable_events", units=ds.units, entity=ds.entity,
        window=[times[0], times[-1]] if times else None, data_policy=policy.model_dump(mode="json"),
        samples=samples, rule_values=rule_values, coverage_counts=dict(Counter(s["coverage"] for s in samples)),
        zero_filled_count=0, omitted_count=0, usable_model_count=sum(v is not None for v in values),
        measured_value_count=sum(v is not None for v in rule_values), duplicate_sources=[],
        latest_evidence_state="insufficient_evidence" if values and values[-1] is None else "available",
        arrival_semantics="supplied availability, otherwise event-time snapshot; no delivery latency claim",
        event_identity_contract=CONTRACT, event_order=policy.event_order,
        deterministic_order="timestamp then trusted sequence" if policy.event_order == "trusted_sequence" else "timestamp then event_id (layout only)",
        tied_timestamp_count=len(ties), tied_event_count=sum(map(len, ties)),
        unordered_tie_positions=ambiguous, sequence_boundaries=boundaries,
        reference_cohort_ends=[group[-1] for group in cohorts] if policy.event_order == "timestamp" else list(range(len(times))),
        reference_restart_positions=([group[-1]+1 for group in cohorts
            if group[-1]+1 < len(times) and any(values[i] is None for i in group)]
            if policy.event_order == "timestamp" else [i+1 for i, v in enumerate(values[:-1]) if v is None]),
        transformations=["Distinct logical events retained; no jitter, aggregation, interpolation or retry duplication."])
    quality["event_reset_positions"] = event_resets(cfg.reset_points, times, policy, ds.timezone, context.as_of)
    return times, values, quality


def _availability_ranges(samples):
    """Bounded O(n) storage and O(log n) queries for descriptive reference spans."""
    size = 1 << max(0, len(samples)-1).bit_length()
    tree = [None]*(2*size)
    tree[size:size+len(samples)] = [s["available_at"] for s in samples]
    def greatest(a, b):
        return max(a, b) if a and b else a or b
    for i in range(size-1, 0, -1):
        tree[i] = greatest(tree[2*i], tree[2*i+1])
    def latest(start, stop):
        start, stop, found = start+size, stop+size, None
        while start < stop:
            if start%2:
                found = greatest(found, tree[start])
                start += 1
            if stop%2:
                stop -= 1
                found = greatest(found, tree[stop])
            start //= 2
            stop //= 2
        return found
    return latest


def annotate_assessments(assessments, quality, methods):
    if "event_identity_contract" not in quality:
        return
    revisions, reference_cutoffs = {}, {}
    latest = _availability_ranges(quality["samples"])
    evidence_indexes = {row["id"]: row["index"] for method in methods for row in method.evidence}
    for method in methods:
        for segment in method.diagnostics.get("segments", []):
            references = segment["training_indexes"] + segment["calibration_indexes"]
            known = [quality["samples"][i]["available_at"] for i in references
                     if quality["samples"][i]["available_at"]]
            reference_cutoff = max(known) if known else None
            for i in range(segment["start_position"], segment["end_position"]+1):
                revisions[i] = segment.get("reference_revision")
                reference_cutoffs[i] = reference_cutoff
    for assessment in assessments:
        sample = quality["samples"][assessment.index]
        assessment.event_id = sample["event_id"]
        assessment.id = assessment.id.replace(f":assessment:{assessment.index}:",
            f":assessment:event:{event_token(sample['event_id'], quality['entity'])}:", 1)
        assessment.baseline["event_identity"] = dict(contract=CONTRACT,
            event_id=sample["event_id"], original_timestamp=sample["original_timestamp"],
            event_sequence=sample["event_sequence"], revision_id=sample["revision_id"],
            selected_revision=sample["selected_revision"], event_order=quality["event_order"])
        statistical = assessment.baseline["kind"] in ("seasonal_residual", "location_shift_pattern")
        if statistical:
            assessment.baseline["reference_revision"] = revisions.get(assessment.index)
        # A same-time sibling is not an input to this point's reference or rule.
        # Replace the generic conservative prefix cutoff with actual support.
        available = [sample["available_at"]]
        if statistical:
            available.append(reference_cutoffs.get(assessment.index))
            if assessment.baseline["kind"] == "location_shift_pattern":
                available += [quality["samples"][evidence_indexes[ref]]["available_at"]
                    for ref in assessment.evidence_refs if ref in evidence_indexes]
        elif assessment.baseline["kind"] == "explicit_rules":
            if any(rule["kind"] != "acceptable_range" for rule in assessment.baseline["violations"]):
                available.append(quality["samples"][assessment.index-1]["available_at"])
        else:
            available.append(latest(max(0, assessment.index-assessment.comparison_samples), assessment.index))
        available = [value for value in available if value]
        assessment.baseline.pop("known_input_availability_cutoff", None)
        if available:
            assessment.baseline["known_input_availability_cutoff"] = max([assessment.timestamp, *available])
        assessment.assumptions = [text for text in assessment.assumptions
            if text != "Input order is chronological after preparation."
            and not text.startswith("Availability cutoff is conservative across known prior inputs")]
        assessment.assumptions.append("Event IDs identify observations, not independent confirmations; ID tie order establishes no chronology or elapsed rate.")


def identify_evidence(methods, observations, patterns, quality):
    """Stable IDs and bounded lineage live beside the original index/time contract."""
    mapping = {}
    samples = quality["samples"]
    for method in methods:
        for item in method.evidence:
            mapping[item["id"]] = f"{method.id}:event:{event_token(samples[item['index']]['event_id'], quality['entity'])}"
            item["id"] = mapping[item["id"]]
    for observation in observations:
        ids = [samples[i]["event_id"] for i in observation["triggering_samples"]]
        observation["id"] = "event-episode:" + fingerprint([quality["entity"], ids])
        observation["evidence_refs"] = [mapping[ref] for ref in observation["evidence_refs"]]
    for pattern in patterns:
        pattern["id"] = "event-pattern:" + fingerprint([
            quality["entity"], pattern["rule"], pattern["direction"], samples[pattern["detection_index"]]["event_id"]])
        pattern["evidence_refs"] = [mapping[ref] for ref in pattern["evidence_refs"]]
