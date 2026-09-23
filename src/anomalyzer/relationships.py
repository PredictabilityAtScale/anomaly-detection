"""Deterministic derived relationship series with point-level lineage."""
from __future__ import annotations

import math

from .alignment import PreparedDataset, exact_sources
from .contracts import Dataset, LineagePoint, Relationship


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
        pairs = []
        for index in range(relationship.lag, min(len(times), training_size + relationship.lag)):
            x = predictor.values[index - relationship.lag]
            y = response.values[index]
            if x is not None and y is not None:
                pairs.append((x, y))
        denominator = math.fsum(x * x for x, _ in pairs)
        if len(pairs) < 2 or denominator == 0:
            raise ValueError("lagged-response training prefix cannot estimate a coefficient")
        coefficient = math.fsum(x * y for x, y in pairs) / denominator
        coefficient_cutoff = relationship.lag + training_size - 1
        parameters = {
            "coefficient": coefficient, "coefficient_source": "estimated",
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
            formula = (f"{relationship.response}[t] - {coefficient} * "
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
            raise ValueError(f"derived nonfinite value at aligned index {index}")
        values.append(value)
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
    first = sources[0].dataset
    derived = Dataset(
        id=relationship.id, timestamps=times, values=values,
        frequency=first.frequency, units=relationship.units,
        entity=first.entity)
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
