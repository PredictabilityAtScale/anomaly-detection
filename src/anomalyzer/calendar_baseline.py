"""Select comparable local dates on a fixed elapsed grid."""
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import math
from zoneinfo import ZoneInfo

from .baseline import reduce_references, reference_weight


DAY = timedelta(days=1)
TICK = timedelta(microseconds=1)
STEP_CHECK = timedelta(hours=6)


@dataclass(frozen=True)
class Tier:
    name: str
    minimum_age_days: int
    clock_width_minutes: int
    same_weekday: bool
    peer_weeks: int
    calibration_weeks: int


TIERS = (
    Tier("mature_same_weekday", 42, 10, True, 4, 3),
    Tier("developing_same_weekday", 14, 60, True, 4, 3),
    Tier("same_day_type", 3, 60, False, 2, 2),
)
PEER_DATES = 4
CALIBRATION_DATES = 3


def week(day):
    return day.toordinal() - day.weekday()


def day_group(day, same_weekday):
    return str(day.weekday()) if same_weekday else ("weekend" if day.weekday() >= 5 else "weekday")


def _wall(instant, zone):
    return instant.astimezone(zone).replace(tzinfo=None)


def _transition_windows(start, stop, zone, check):
    """Locate IANA offset transitions, including their skipped or repeated wall times."""
    windows = defaultdict(list)
    left = start - 2 * DAY
    while left < stop + 2 * DAY:
        check()
        right = left + STEP_CHECK
        offset = left.astimezone(zone).utcoffset()
        if offset != right.astimezone(zone).utcoffset():
            lo, hi = left, right
            while hi - lo > TICK:
                middle = lo + (hi - lo) // 2
                if middle.astimezone(zone).utcoffset() == offset:
                    lo = middle
                else:
                    hi = middle
            before = hi.replace(tzinfo=None) + offset
            after = _wall(hi, zone)
            begin, end = sorted((before, after))
            reason = "ambiguous_local_time" if after < before else "nonexistent_local_time"
            day = begin.date()
            while day <= end.date():
                windows[day].append((begin, end, reason))
                day += DAY
        left = right
    return windows


@dataclass
class PeerDate:
    day: date
    indexes: list[int]
    representative: float
    expected_slots: int
    version_overrides: dict
    reference_replacements: list[int]


@dataclass
class Selection:
    age_tier: Tier | None
    tier: Tier | None
    attempts: list[dict]
    peers: list[PeerDate]
    reason: str | None = None

    def expectation(self, handling):
        if handling == "include":
            return self.peers[-1].representative, [0.0] * (len(self.peers) - 1) + [1.0]
        candidates = [(peer.representative, reference_weight(PEER_DATES - index, PEER_DATES))
                      for index, peer in enumerate(self.peers)]
        return reduce_references(candidates)


class CalendarIndex:
    def __init__(self, instants, zone, step, check):
        self.instants = instants
        self.origin = instants[0]
        self.zone = ZoneInfo(zone)
        self.step = step
        self.step_seconds = int(step.total_seconds())
        self.locals = [instant.astimezone(self.zone) for instant in instants]
        self.days = sorted({local.date() for local in self.locals})
        self.groups = defaultdict(list)
        for day in self.days:
            self.groups[True, day_group(day, True)].append(day)
            self.groups[False, day_group(day, False)].append(day)
        self.transitions = _transition_windows(self.origin, instants[-1], self.zone, check)
        self.dst = []
        for index in range(len(instants)):
            check()
            self.dst.append(self.target_dst(index))
        self.slots = lru_cache(maxsize=32768)(self._slots)

    def target_dst(self, index):
        local = self.locals[index]
        if local.utcoffset() != local.replace(fold=1-local.fold).utcoffset():
            return "ambiguous_target_time"
        end = (self.instants[index] + self.step - TICK).astimezone(self.zone)
        if end.utcoffset() != local.utcoffset():
            return "bucket_crosses_offset_transition"
        return None

    def _slots(self, day, clock, width):
        """Project closed clock windows to native slots, including off-grid history."""
        midnight = datetime.combine(day, time())
        radius = timedelta(minutes=width)
        low, high = clock - radius, clock + radius
        parts = [(max(low, timedelta(0)), min(high, DAY - TICK))]
        if low < timedelta(0):
            parts.append((DAY + low, DAY - TICK))
        if high >= DAY:
            parts.insert(0, (timedelta(0), high - DAY))
        ranges = []
        offsets = set()
        for left, right in sorted(parts):
            begin, end = midnight + left, midnight + right
            for invalid_start, invalid_end, reason in self.transitions.get(day, ()):
                if begin < invalid_end and end >= invalid_start:
                    return (), reason
            local = begin.replace(tzinfo=self.zone)
            offsets.add(local.utcoffset())
            origin_offset = local.astimezone(timezone.utc) - self.origin
            start, remainder = divmod(origin_offset, self.step)
            last = (origin_offset + right - left) // self.step
            ranges.append(range(start + bool(remainder), last + 1))
        if len(offsets) > 1:
            return (), "window_crosses_offset_transition"
        return tuple(ranges), None

    def select(self, index, segment, policy, peer_values, check, *, widths=None):
        instant, local = self.instants[index], self.locals[index]
        day = local.date()
        age = instant - self.instants[segment]
        tiers = [tier for tier in TIERS if age >= timedelta(days=tier.minimum_age_days)]
        if not tiers:
            return Selection(None, None, [], [], "segment_younger_than_three_days")
        attempted = tiers[:1] if policy.fallback == "none" else tiers
        guard_buckets = (policy.guard_minutes * 60 + self.step_seconds - 1) // self.step_seconds
        last_peer = max(0, index - guard_buckets)
        first_peer = max(segment, index - policy.lookback_days * 86400 // self.step_seconds)
        earliest_day = self.locals[first_peer].date()
        clock = local.replace(tzinfo=None) - datetime.combine(day, time())
        reports = []
        for tier in attempted:
            check()
            dates = self.groups[tier.same_weekday, day_group(day, tier.same_weekday)]
            last_date = bisect_left(dates, day)
            first_date = bisect_left(dates, earliest_day)
            supported, weeks, rejected, dst = [], set(), Counter(), {}
            width = tier.clock_width_minutes if widths is None else widths
            examined = 0
            for date_index in range(last_date - 1, first_date - 1, -1):
                candidate_day = dates[date_index]
                examined += 1
                slots, reason = self.slots(candidate_day, clock, width)
                if reason:
                    rejected["dst_windows"] += 1
                    dst[candidate_day.isoformat()] = reason
                    continue
                expected = sum(map(len, slots))
                if not expected:
                    rejected["no_native_slots"] += 1
                    continue
                indexes, values, revisions, replacements = [], [], {}, []
                for span in slots:
                    lo, hi = max(span.start, first_peer), min(span.stop, last_peer)
                    before_history = max(0, min(span.stop, first_peer) - span.start)
                    within_guard = max(0, span.stop - max(span.start, first_peer, last_peer))
                    if before_history:
                        rejected["segment_or_lookback"] += before_history
                    if within_guard:
                        rejected["guard"] += within_guard
                    for peer in range(lo, hi):
                        if self.dst[peer]:
                            rejected["dst_buckets"] += 1
                            continue
                        value, reason, version, replaced = peer_values(peer)
                        if value is None:
                            rejected[reason] += 1
                            continue
                        indexes.append(peer)
                        values.append(value)
                        if version is not None:
                            revisions[peer] = version
                        if replaced:
                            replacements.append(peer)
                if 5 * len(indexes) < 4 * expected:
                    rejected["insufficient_slot_coverage"] += 1
                    continue
                candidate_week = week(candidate_day)
                if len(supported) == PEER_DATES - 1 and len(weeks | {candidate_week}) < tier.peer_weeks:
                    rejected["insufficient_week_diversity"] += 1
                    continue
                weeks.add(candidate_week)
                supported.append(PeerDate(candidate_day, indexes, math.fsum(values) / len(values),
                                          expected, revisions, replacements))
                if len(supported) == PEER_DATES:
                    break
            report = dict(tier=tier.name, clock_width_minutes=width, examined_dates=examined,
                          supported_dates=len(supported), supported_weeks=len(weeks),
                          rejection_counts=dict(rejected), dst_exclusions=dst,
                          outcome="selected" if len(supported) == PEER_DATES else "insufficient_date_or_week_support")
            reports.append(report)
            if len(supported) == PEER_DATES:
                return Selection(tiers[0], tier, reports, list(reversed(supported)))
        return Selection(tiers[0], None, reports, [], "unsupported_calendar_reference")
