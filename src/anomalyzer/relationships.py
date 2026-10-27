"""Deterministic derived relationship series with point-level lineage."""
from __future__ import annotations

import math
from dataclasses import replace

from .alignment import PreparedDataset, exact_sources
from .contracts import DataPolicy, Dataset, DatasetV11, LineagePoint, Relationship


def _compare(value: float, operator: str, threshold: float) -> bool:
    return {
        "lt": value < threshold, "lte": value <= threshold,
        "gt": value > threshold, "gte": value >= threshold,
        "eq": value == threshold,
    }[operator]


def _source_ids(relationship: Relationship) -> list[str]:
    if relationship.kind == "ratio":
        return [relationship.numerator, relationship.denominator]
    if relationship.kind == "difference":
        return [relationship.minuend, relationship.subtrahend]
    if relationship.kind == "normalized_residual":
        return [relationship.observed, relationship.expected]
    if relationship.kind == "lagged_response":
        return [relationship.response, relationship.predictor]
    return [condition.dataset for condition in relationship.conditions]


def derive(relationship: Relationship,
           prepared: dict[str, PreparedDataset]) -> tuple[Dataset, list[LineagePoint], dict]:
    ids = _source_ids(relationship)
    sources = exact_sources(ids, prepared)
    identified = "event_identity_contract" in sources[0].quality
    if (identified and relationship.kind == "lagged_response"
            and sources[0].quality["unordered_tie_positions"]):
        raise ValueError("lagged_response cannot order tied events without trusted_sequence")
    # Exclusion from a model does not erase a genuine measured value.
    sources = [replace(source, values=source.quality.get("rule_values", source.values)) for source in sources]
    by_id = {source.dataset.id: source for source in sources}
    times = sources[0].times
    if any(value is None for value in times):
        raise ValueError("relationship timestamps cannot be positional")
    parameters = {}
    coefficient = getattr(relationship, "coefficient", None)
    coefficient_cutoff = None
    if relationship.kind == "difference":
        a, b = sources
        if not a.dataset.units or a.dataset.units != b.dataset.units:
            raise ValueError("difference requires identical declared source units")
        if relationship.units != a.dataset.units:
            raise ValueError("difference output units must equal the source units")
    if relationship.kind == "lagged_response" and coefficient is None:
        response, predictor = sources
        training_size = relationship.training_size
        coefficient_cutoff = relationship.lag + training_size - 1
        training_complete = len(times) > coefficient_cutoff
        if training_complete:
            pairs = []
            for index in range(relationship.lag, coefficient_cutoff + 1):
                x = predictor.values[index - relationship.lag]
                y = response.values[index]
                if x is not None and y is not None:
                    pairs.append((x, y))
            denominator = math.fsum(x * x for x, _ in pairs)
            if len(pairs) < 2 or denominator == 0:
                raise ValueError("lagged-response training prefix cannot estimate a coefficient")
            coefficient = math.fsum(x * y for x, y in pairs) / denominator
        parameters = {
            "coefficient": coefficient,
            "coefficient_source": "estimated" if training_complete else "pending_training",
            "training_size": training_size,
            "training_cutoff_index": coefficient_cutoff,
            "fit": "least_squares_through_origin",
        }
    elif relationship.kind == "lagged_response":
        parameters = {
            "coefficient": coefficient, "coefficient_source": "supplied",
            "training_size": None, "training_cutoff_index": None,
        }

    values: list[float | None] = []
    lineage: list[LineagePoint] = []
    unavailable_count = 0
    excluded_indexes = set()
    for index, observed_at in enumerate(times):
        used: list[tuple[PreparedDataset, int]] = []
        unavailable = None
        formula = ""
        lag = 0
        if relationship.kind == "ratio":
            numerator, denominator = sources
            used = [(numerator, index), (denominator, index)]
            top, bottom = numerator.values[index], denominator.values[index]
            formula = f"{relationship.numerator}[t] / {relationship.denominator}[t]"
            if top is None or bottom is None:
                value, unavailable = None, "missing_source_value"
            elif bottom == 0:
                if relationship.zero_denominator == "error":
                    raise ValueError(f"zero denominator at aligned index {index}")
                value, unavailable = None, "zero_denominator"
            else:
                value = top / bottom
        elif relationship.kind == "difference":
            minuend, subtrahend = sources
            used = [(minuend, index), (subtrahend, index)]
            left, right = minuend.values[index], subtrahend.values[index]
            formula = f"{relationship.minuend}[t] - {relationship.subtrahend}[t]"
            if left is None or right is None:
                value, unavailable = None, "missing_source_value"
            else:
                value = left - right
        elif relationship.kind == "normalized_residual":
            observed, expected = sources
            used = [(observed, index), (expected, index)]
            left, right = observed.values[index], expected.values[index]
            formula = f"({relationship.observed}[t] - {relationship.expected}[t]) / {relationship.scale}"
            if left is None or right is None:
                value, unavailable = None, "missing_source_value"
            else:
                value = (left - right) / relationship.scale
        elif relationship.kind == "lagged_response":
            response, predictor = sources
            lag = relationship.lag
            predictor_index = index - lag
            factor = coefficient if coefficient is not None else "pending_coefficient"
            formula = (f"{relationship.response}[t] - {factor} * "
                       f"{relationship.predictor}[t-{lag}]")
            if predictor_index < 0:
                used = [(response, index)]
                value, unavailable = None, "lag_reference_unavailable"
            else:
                used = [(response, index), (predictor, predictor_index)]
                y, x = response.values[index], predictor.values[predictor_index]
                if coefficient_cutoff is not None and index <= coefficient_cutoff:
                    value, unavailable = None, "coefficient_training_prefix"
                elif y is None or x is None:
                    value, unavailable = None, "missing_source_value"
                else:
                    value = y - coefficient * x
        else:
            used = [(by_id[condition.dataset], index)
                    for condition in relationship.conditions]
            source_values = [source.values[source_index]
                             for source, source_index in used]
            formula = (relationship.combine + "(" + ", ".join(
                f"{condition.dataset}[t] {condition.operator} {condition.threshold}"
                for condition in relationship.conditions) + ")")
            if any(value is None for value in source_values):
                value, unavailable = None, "missing_or_incomplete_condition_source"
            else:
                matches = [_compare(value, condition.operator, condition.threshold)
                           for value, condition in zip(source_values, relationship.conditions)]
                value = float(all(matches) if relationship.combine == "all" else any(matches))
        if value is not None and not math.isfinite(value):
            value, unavailable = None, "nonfinite_derived_value"
        values.append(value)
        if any("samples" in source.quality and source.quality["samples"][i]["coverage"] == "excluded" for source, i in used):
            excluded_indexes.add(index)
        unavailable_count += unavailable is not None
        source_indexes = {source.dataset.id: source.source_indexes[source_index]
                          for source, source_index in used}
        source_timestamps = {source.dataset.id: source.times[source_index]
                             for source, source_index in used}
        cutoff = max(source_timestamps.values())
        lineage.append(LineagePoint(
            index=index, timestamp=observed_at, value=value,
            source_dataset_ids=sorted(source_indexes),
            source_indexes=source_indexes, source_timestamps=source_timestamps,
            formula=formula, parameters=parameters, units=relationship.units,
            lag=lag, unavailable_reason=unavailable,
            latest_source_cutoff=cutoff))
        lineage[-1].source_values = {source.dataset.id: source.values[i] for source, i in used}
        lineage[-1].source_coverage = {source.dataset.id:
            source.quality["samples"][i]["coverage"] if "samples" in source.quality else
            "complete" if source.values[i] is not None else "unknown_or_incomplete" for source, i in used}
        lineage[-1].source_revision_ids = {source.dataset.id:
            source.quality["samples"][i]["revision_id"] if "samples" in source.quality else None for source, i in used}
        lineage[-1].source_available_at = {source.dataset.id:
            source.quality["samples"][i]["available_at"] if "samples" in source.quality else None for source, i in used}
        lineage[-1].source_input_indexes = {source.dataset.id:
            source.quality["samples"][i]["source_indexes"] if "samples" in source.quality else [source.source_indexes[i]] for source, i in used}
        if identified:
            lineage[-1].source_event_ids = {source.dataset.id: source.quality["samples"][i]["event_id"] for source, i in used}
            lineage[-1].source_original_timestamps = {source.dataset.id: source.quality["samples"][i]["original_timestamp"] for source, i in used}
        known = [lineage[-1].source_available_at[source.dataset.id] for source, i in used
                 if source.values[i] is not None and lineage[-1].source_available_at[source.dataset.id]]
        lineage[-1].latest_source_cutoff = max([cutoff, *known])
    first = sources[0].dataset
    if any("data_policy" in source.quality for source in sources) or any(v is None for v in values):
        basis = "event_index" if sources[0].quality.get("coordinate") == "event_index" else "calendar"
        policies = [getattr(source.dataset, "data_policy", None) or DataPolicy() for source in sources]
        separation = [policy.change_max_gap_seconds for policy in policies if policy.change_max_gap_seconds]
        derived = DatasetV11(id=relationship.id, timestamps=times, values=values,
            frequency=first.frequency, units=relationship.units, entity=first.entity, timezone=first.timezone,
            data_policy=DataPolicy(observation_basis=basis,
                event_order=policies[0].event_order if identified else "timestamp",
                reference_gaps="restart" if any(p.reference_gaps == "restart" for p in policies) else "same_phase",
                minimum_phase_samples=max(p.minimum_phase_samples for p in policies),
                change_max_gap_seconds=min(separation) if separation else None),
            coverage=["excluded" if i in excluded_indexes else "complete" if v is not None else "unknown" for i, v in enumerate(values)],
            event_ids=[s["event_id"] for s in sources[0].quality["samples"]] if identified else None,
            available_at=[p.latest_source_cutoff if any(p.source_available_at.values()) else None for p in lineage] if identified else None,
            event_sequence=[s["event_sequence"] for s in sources[0].quality["samples"]] if identified and policies[0].event_order == "trusted_sequence" else None)
    else:
        derived = Dataset(id=relationship.id, timestamps=times, values=values,
            frequency=first.frequency, units=relationship.units, entity=first.entity, timezone=first.timezone)
    quality = {
        "alignment": "exact", "cadence": first.frequency,
        "aligned_count": len(times), "available_count": len(times) - unavailable_count,
        "unavailable_count": unavailable_count,
        "source_dataset_ids": sorted(ids), "parameters": parameters,
        "missing_values_are_zero": False,
        "latest_evidence_state": (
            "insufficient_evidence" if values and values[-1] is None else "available"),
    }
    return derived, lineage, quality
