"""Deterministic native five-minute fixtures shared by comparison runners."""

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import math
from random import Random


BUCKETS_PER_DAY = 288
TRAIN, CALIBRATION, HOLDOUT = (days * BUCKETS_PER_DAY for days in (8, 4, 3))
ORIGIN = TRAIN + CALIBRATION
START = datetime(2026, 1, 5, tzinfo=timezone.utc)
COUNT_FLOOR = 0.4
SEEDS = (14, 37, 65, 91)


@dataclass(frozen=True)
class Incident:
    kind: str
    start: int
    duration: int
    change: int
    boundary: bool = False

    @property
    def stop(self):
        return self.start + self.duration


@dataclass(frozen=True)
class Fixture:
    name: str
    values: list[int | None]
    incidents: tuple[Incident, ...] = ()
    noise_clusters: tuple[tuple[int, int], ...] = ()


def poisson(rate, rng):
    limit = math.exp(-rate)
    product, count = rng.random(), 0
    while product > limit:
        product *= rng.random()
        count += 1
    return count


def inject(values, incidents):
    values = values.copy()
    for event in incidents:
        for index in range(event.start, event.stop):
            values[index] = max(0, values[index] + event.change)
    return values


def fixtures():
    size = ORIGIN + HOLDOUT
    stable = [0] * size
    # Separate ordinary isolated events from the injected incidents. In both,
    # count 1 is physically possible and each recorded zero is a measured zero.
    for index in range(ORIGIN + 23, size, 37):
        stable[index] = 1
    quiet_incidents = (
        Incident("two_count_spike", ORIGIN + 72, 1, 2),
        Incident("burst", ORIGIN + 303, 4, 4),
        Incident("sustained_one_count_rise", ORIGIN + 550, 12, 1),
    )
    yield Fixture("quiet-control", stable)
    yield Fixture("quiet-incidents", inject(stable, quiet_incidents), quiet_incidents)
    single = (Incident("isolated_one_count_incident", ORIGIN + 68, 1, 1, boundary=True),)
    yield Fixture("one-count-boundary", inject(stable, single), single)

    flat = [12] * size
    for index in range(ORIGIN + 19, size, 49):
        flat[index] += 1 if index % 2 else -1
    flat_incidents = (Incident("two_count_drop", ORIGIN + 80, 1, -2),
                      Incident("sustained_one_count_drop", ORIGIN + 530, 12, -1))
    yield Fixture("flat-control", flat)
    yield Fixture("flat-incidents", inject(flat, flat_incidents), flat_incidents)

    for seed in SEEDS:
        rng = Random(seed)
        for volume, rate in (("low", 1.5), ("busy", 28)):
            # Fixed UTC daily season with noisier daytime counts and weekend troughs.
            values = [poisson(rate * (0.5 if i // BUCKETS_PER_DAY % 7 >= 5 else 1)
                              * (1.6 if 84 <= i % BUCKETS_PER_DAY < 228 else 0.6), rng)
                      for i in range(size)]
            events = (Incident("spike", ORIGIN + 120, 1, 10 if volume == "low" else 55),
                      Incident("outage", ORIGIN + 385, 12, -max(values[ORIGIN+385:ORIGIN+397])),
                      Incident("sustained_rise", ORIGIN + 682, 24, 2 if volume == "low" else 9))
            yield Fixture(f"{volume}-{seed}-control", values)
            observed = inject(values, events)
            # Preserve one collection gap at its actual timestamp.
            if seed == SEEDS[-1]:
                observed[ORIGIN + 610:ORIGIN + 613] = [None] * 3
            yield Fixture(f"{volume}-{seed}-incidents", observed, events)


def clustered_counts(level, seed, start_every, holdout_start_every,
                     widths=(1, 1, 2, 2, 3, 4, 5), holdout_widths=None):
    """Integer background with ordinary same-direction runs of varying length."""
    rng = Random(seed)
    values = [level] * (ORIGIN + HOLDOUT)
    clusters = []
    for start, end, spacing, choices in ((0, ORIGIN, start_every, widths),
                                         (ORIGIN, len(values), holdout_start_every, holdout_widths or widths)):
        index = start + rng.randint(3, spacing)
        while index < end:
            width = min(rng.choice(choices), end - index)
            change = rng.choice((-1, 1)) if level > 0 else 1
            values[index:index + width] = [level + change] * width
            clusters.append((index, index + width))
            index += width + rng.randint(3, 2 * spacing)
    return values, tuple(clusters)


def quiet_incident(values, level, kind, offset, duration, change, *, boundary=False):
    """Choose the first flat window after the fixed anchor, independently of scores."""
    anchor = ORIGIN + offset
    for index in range(anchor, min(anchor + 96, len(values) - duration - 1)):
        if all(value == level for value in values[index-2:index + duration + 2]):
            return Incident(kind, index, duration, change, boundary)
    raise ValueError(f"No clean injection window for {kind} after bucket {anchor}")


def holdout_fixtures():
    for name, level, seed, spacing, holdout_spacing in (
        ("zero-clusters", 0, 101, 61, 61),
        ("flat-clusters", 8, 206, 37, 37),
        ("more-clusters", 0, 307, 71, 19),
    ):
        values, clusters = clustered_counts(level, seed, spacing, holdout_spacing)
        direction = -1 if level else 1
        events = (
            quiet_incident(values, level, "isolated_one_count", 25, 1, direction, boundary=True),
            quiet_incident(values, level, "two_count_departure", 190, 1, 2 * direction),
            quiet_incident(values, level, "sustained_one_count", 370, 14, direction),
            quiet_incident(values, level, "outage" if level else "burst", 645, 12, -level if level else 5),
        )
        yield Fixture(f"{name}-control", values, noise_clusters=clusters)
        yield Fixture(f"{name}-incidents", inject(values, events), events, clusters)

    for name, rate, seed, spike, rise in (("low", 1.25, 411, 8, 2), ("busy", 23, 613, 48, 10)):
        rng = Random(seed)
        values = [poisson(rate * (1.5 if 77 <= index % BUCKETS_PER_DAY < 213 else 0.5)
                          * (0.62 if (START.weekday() + index // BUCKETS_PER_DAY) % 7 >= 5 else 1), rng)
                  for index in range(ORIGIN + HOLDOUT)]
        outage = ORIGIN + 420
        events = (Incident("spike", ORIGIN + 111, 1, spike),
                  Incident("outage", outage, 14, -max(values[outage:outage + 14])),
                  Incident("sustained_rise", ORIGIN + 693, 24, rise))
        yield Fixture(f"{name}-fresh-control", values)
        observed = inject(values, events)
        observed[ORIGIN+555:ORIGIN+558] = [None] * 3
        yield Fixture(f"{name}-fresh-incidents", observed, events)


def persistence_fixtures():
    for name, level, seed, widths, holdout_widths in (
        ("short-clusters", 0, 727, (1, 1, 2, 3), None),
        ("flat-bidirectional", 9, 887, (1, 2, 2, 4, 5), None),
        ("longer-ordinary-clusters", 0, 1499, (1, 2, 3, 4, 5, 7), (1, 2, 3, 5, 7, 9)),
    ):
        values, noise = clustered_counts(level, seed, 58, 52, widths, holdout_widths)
        direction = -1 if level else 1
        events = (
            quiet_incident(values, level, "isolated_one_count", 30, 1, direction, boundary=True),
            quiet_incident(values, level, "two_count_departure", 170, 1, 2 * direction),
            quiet_incident(values, level, "short_one_count_shift", 310, 4, direction, boundary=True),
            quiet_incident(values, level, "sustained_one_count", 465, 16, direction),
            quiet_incident(values, level, "outage" if level else "burst", 690, 12, -level if level else 4),
        )
        yield Fixture(f"{name}-control", values, noise_clusters=noise)
        yield Fixture(f"{name}-incidents", inject(values, events), events, noise)

    for name, rate, seed, spike, rise in (("low", 1.7, 953, 9, 2), ("busy", 32, 1103, 65, 8)):
        rng = Random(seed)
        values = [poisson(rate * (1.7 if 80 <= i % BUCKETS_PER_DAY < 222 else 0.55)
                          * (0.7 if (START.weekday() + i // BUCKETS_PER_DAY) % 7 >= 5 else 1), rng)
                  for i in range(ORIGIN + HOLDOUT)]
        outage = ORIGIN + 385
        events = (Incident("spike", ORIGIN + 109, 1, spike),
                  Incident("outage", outage, 15, -max(values[outage:outage + 15])),
                  Incident("sustained_rise", ORIGIN + 692, 30, rise))
        yield Fixture(f"{name}-persistence-control", values)
        observed = inject(values, events)
        observed[ORIGIN + 560:ORIGIN + 563] = [None] * 3
        yield Fixture(f"{name}-persistence-incidents", observed, events)


SUITES = {"original": fixtures, "clustered-holdout": holdout_fixtures, "persistence-holdout": persistence_fixtures}


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
