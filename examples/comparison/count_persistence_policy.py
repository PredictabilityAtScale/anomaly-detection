"""Experimental alert policy for count series with a nearly constant reference."""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class CountReference:
    level: int
    longest_one_count_run: int

    @property
    def confirmation_buckets(self):
        return max(2, self.longest_one_count_run + 1)


def learn_reference(history):
    """Use only the caller's training and calibration prefix, gaps included."""
    counts = Counter(value for value in history if value is not None)
    if not counts:
        return None
    level, support = counts.most_common(1)[0]
    # Keep the experiment narrow. It assumes a single stable count level and
    # no more than 10% deviations, all within one count of that level.
    if support < 0.9 * counts.total() or any(abs(value - level) > 1 for value in counts):
        return None
    longest, run, previous = 0, 0, None
    for value in history:
        if value is None or value == level:
            run = 0
        else:
            run = run + 1 if value == previous else 1
            longest = max(longest, run)
        previous = value
    return CountReference(level, longest)


def confirm_alerts(values, scored, point_flags, patterns, reference):
    """Return point flags, emitted alerts, and new persistence-rule starts.

    The scored positions delimit the replay and must already be calibrated.
    Magnitude and position come from observed counts and no incident labels.
    """
    if reference is None:
        return point_flags, point_flags | (patterns.keys() & scored), set()
    kept_points, alerts, confirmations = set(), set(), set()
    prior_index, previous_small, run = None, None, 0
    for index in sorted(scored):
        value = values[index]
        if value is None:
            prior_index, previous_small, run = None, None, 0
            continue
        departure = value - reference.level
        if abs(departure) >= 2:
            if index in point_flags:
                kept_points.add(index)
            if index in point_flags or index in patterns:
                alerts.add(index)
        if abs(departure) == 1:
            adjacent = prior_index is not None and index == prior_index + 1
            run = run + 1 if adjacent and departure == previous_small else 1
            if run == reference.confirmation_buckets:
                confirmations.add(index)
                alerts.add(index)
            previous_small = departure
        else:
            previous_small, run = None, 0
        prior_index = index
    return kept_points, alerts, confirmations
