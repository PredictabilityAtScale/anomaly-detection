from anomalyzer.evaluation.alert_lifecycle import replay_alert_lifecycle


def test_recovery_requires_consecutive_scored_quiet_buckets():
    steps = replay_alert_lifecycle(["pattern", "quiet", "unknown", "quiet", "quiet"], resolve_after=2)
    assert [step.action for step in steps] == ["open", None, None, None, "resolve"]
    assert [step.active_issue for step in steps] == [1, 1, 1, 1, None]


def test_returning_pattern_is_quietened_but_point_can_realert():
    steps = replay_alert_lifecycle(["pattern", "quiet", "pattern", "quiet", "point", "point"],
                                   resolve_after=2, realert_on_point=True)
    assert [step.action for step in steps] == ["open", None, None, None, "realert", None]
    assert steps[4].event_issue == steps[0].event_issue


def test_pattern_grace_resolves_point_issues_and_reopen_preserves_identity():
    steps = replay_alert_lifecycle(["point", "quiet", "point", "quiet", "quiet", "quiet", "point"],
                                   resolve_after=3, pattern_grace_only=True, reopen_within=2)
    assert [step.action for step in steps] == ["open", "resolve", "reopen", "resolve", None, None, "open"]
    assert [steps[i].event_issue for i in (0, 2, 6)] == [1, 1, 2]
