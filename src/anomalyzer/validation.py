from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
import math
from .contracts import Request


def timestamp(value: str, zone: str | None = None) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            if not zone:
                raise ValueError("local timestamps require a timezone")
            tz = ZoneInfo(zone)
            candidates = [dt.replace(tzinfo=tz, fold=i) for i in (0, 1)]
            valid = [c for c in candidates if c.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == dt]
            if not valid or len({c.utcoffset() for c in valid}) != 1:
                raise ValueError("ambiguous or nonexistent local timestamp; supply an explicit offset")
            dt = valid[0]
        return dt.astimezone(timezone.utc)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"invalid timestamp {value!r}: {exc}") from exc


def prepare(request: Request):
    ds, cfg = request.datasets[0], request.config
    if len(ds.values) > cfg.max_points:
        raise ValueError("dataset exceeds max_points")
    statuses = ds.period_statuses or ["complete"] * len(ds.values)

    def split_complete(items):
        incomplete_at = [index for index, item in enumerate(items)
                         if item[2] == "incomplete"]
        if incomplete_at and incomplete_at != list(range(incomplete_at[0], len(items))):
            raise ValueError("incomplete periods must form a trailing suffix after chronological preparation")
        cutoff = incomplete_at[0] if incomplete_at else len(items)
        incomplete = [dict(index=item[3], timestamp=item[0], observed=item[1],
                           period_status="incomplete")
                      for item in items[cutoff:]]
        return items[:cutoff], incomplete

    if ds.timestamps is None:
        if request.context.as_of:
            raise ValueError("as_of requires timestamps")
        items = [(None, value, status, index)
                 for index, (value, status) in enumerate(zip(ds.values, statuses))]
        complete, incomplete = split_complete(items)
        complete_values = [item[1] for item in complete]
        quality = dict(
            input_count=len(ds.values), observation_count=len(complete_values),
            complete_count=len(complete_values), incomplete_count=len(incomplete),
            incomplete_periods=incomplete,
            missing_count=sum(v is None for v in complete_values), duplicate_count=0,
            regular=True, transformations=[], timestamp_normalization=None,
            coordinate="position", regularity_basis="position_order",
            window=[0, len(complete_values) - 1] if complete_values else None,
            units=ds.units, entity=ds.entity)
        return [None] * len(complete_values), complete_values, quality
    if ds.timezone:
        try:
            ZoneInfo(ds.timezone)
        except (ValueError, KeyError) as exc:
            raise ValueError(f"unknown timezone: {ds.timezone}") from exc
    pairs = [(timestamp(t, ds.timezone), v, status, index)
             for index, (t, v, status) in enumerate(
                 zip(ds.timestamps, ds.values, statuses))]
    transforms = []
    if pairs != sorted(pairs, key=lambda p: p[0]):
        transforms.append("sorted by timestamp")
    pairs.sort(key=lambda p: p[0])
    groups = {}
    for t, v, status, index in pairs:
        groups.setdefault(t, []).append((v, status, index))
    duplicates = len(pairs) - len(groups)
    if duplicates and cfg.duplicate_policy == "error":
        raise ValueError("duplicate timestamps require duplicate_policy mean or sum; group entities before analysis")
    if any(len(items) > 1 and any(status == "incomplete" for _, status, _ in items)
           for items in groups.values()):
        raise ValueError("incomplete periods cannot be duplicate-aggregated; submit one latest value")
    pairs = []
    for t, items in groups.items():
        values = [value for value, _, _ in items]
        v = None if None in values else math.fsum(values)
        if v is not None and cfg.duplicate_policy != "sum":
            v /= len(values)
        if v is not None and not math.isfinite(v):
            raise ValueError("duplicate aggregation produced a nonfinite value")
        pairs.append((t, v, items[0][1], items[0][2]))
    if duplicates:
        transforms.append(f"aggregated {duplicates} duplicates using {cfg.duplicate_policy}; null propagates")
    excluded = 0
    if request.context.as_of:
        cutoff = timestamp(request.context.as_of, ds.timezone)
        excluded = sum(t > cutoff for t, *_ in pairs)
        pairs = [item for item in pairs if item[0] <= cutoff]
        transforms.append(f"as_of excluded {excluded} samples")
    pairs, incomplete = split_complete(pairs)
    number, unit = re.fullmatch(r"([1-9][0-9]*)(s|min|h|d|w)", ds.frequency).groups()
    cadence = timedelta(seconds=int(number) * {"s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800}[unit])
    regular = all(b[0] - a[0] == cadence for a, b in zip(pairs, pairs[1:]))
    incomplete = [{**item, "timestamp": item["timestamp"].isoformat()
                   if item["timestamp"] is not None else None}
                  for item in incomplete]
    quality = dict(input_count=len(ds.values), observation_count=len(pairs),
                   complete_count=len(pairs), incomplete_count=len(incomplete),
                   incomplete_periods=incomplete,
                   missing_count=sum(v is None for _, v, *_ in pairs),
                   duplicate_count=duplicates, regular=regular,
                   transformations=transforms, timestamp_normalization="UTC",
                   coordinate="timestamp", regularity_basis="declared_cadence",
                   window=[pairs[0][0].isoformat(), pairs[-1][0].isoformat()]
                   if pairs else None, units=ds.units, entity=ds.entity)
    return [t.isoformat() for t, *_ in pairs], [v for _, v, *_ in pairs], quality


def resolve_reset_points(points, times, zone=None):
    """Resolve manual segment starts against the prepared chronological series."""
    resolved = []
    timestamped = bool(times and times[0] is not None)
    for point in points:
        if isinstance(point, int):
            index = point
        elif not timestamped:
            raise ValueError("timestamp reset_points require a timestamped dataset")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", point):
            matches = [i for i, value in enumerate(times) if value[:10] == point]
            if len(matches) != 1:
                raise ValueError(f"date reset point {point!r} must identify exactly one observed sample")
            index = matches[0]
        else:
            normalized = timestamp(point, zone).isoformat()
            matches = [i for i, value in enumerate(times) if value == normalized]
            if len(matches) != 1:
                raise ValueError(f"timestamp reset point {point!r} must match an observed sample")
            index = matches[0]
        if index <= 0 or index >= len(times):
            raise ValueError(f"reset point {point!r} resolves outside positions 1..{len(times)-1}")
        resolved.append(index)
    if len(set(resolved)) != len(resolved):
        raise ValueError("reset_points resolve to duplicate sample positions")
    return sorted(resolved)
