"""Offline alert lifecycle replay over a detector's already resolved evidence."""

from dataclasses import dataclass
from typing import Iterable, Literal


Signal = Literal["pattern", "point", "quiet", "unknown"]
Action = Literal["open", "reopen", "realert", "resolve"]
ALERT_ACTIONS = frozenset({"open", "reopen", "realert"})


@dataclass(frozen=True)
class AlertStep:
    active_issue: int | None
    action: Action | None
    event_issue: int | None


def replay_alert_lifecycle(
    signals: Iterable[Signal], *, resolve_after: int = 1, reopen_within: int = 0,
    realert_on_point: bool = False, pattern_grace_only: bool = False,
) -> list[AlertStep]:
    """Replay one scope in order. Unknown buckets interrupt recovery, not issues.

    A point after verified quiet can send a fresh alert while an issue remains
    open. Reopening a resolved issue preserves its identity and emits an alert.
    ``reopen_within`` is measured from the last signal, in supplied buckets.
    """
    if type(resolve_after) is not int or resolve_after < 1:
        raise ValueError("resolve_after must be a positive number of buckets")
    if type(reopen_within) is not int or reopen_within < 0:
        raise ValueError("reopen_within must be a nonnegative number of buckets")

    steps = []
    active = last_issue = last_signal = None
    quiet = 0
    last_was_point = False
    for i, signal in enumerate(signals):
        action, event_issue = None, None
        if signal in ("point", "pattern"):
            if active is None:
                if last_signal is not None and i - last_signal <= reopen_within:
                    active, action = last_issue, "reopen"
                else:
                    last_issue = 1 if last_issue is None else last_issue + 1
                    active, action = last_issue, "open"
            elif signal == "point" and realert_on_point and quiet > 0:
                action = "realert"
            event_issue = active if action else None
            quiet, last_signal, last_was_point = 0, i, signal == "point"
        elif signal == "quiet":
            if active is not None:
                quiet += 1
                required = 1 if pattern_grace_only and last_was_point else resolve_after
                if quiet >= required:
                    action, event_issue, active = "resolve", active, None
        elif signal == "unknown":
            quiet = 0
        else:
            raise ValueError(f"Unrecognized alert signal: {signal!r}")
        steps.append(AlertStep(active, action, event_issue))
    return steps
