from examples.comparison.count_persistence_policy import confirm_alerts, learn_reference


def test_persistence_uses_historical_duration_and_gaps_break_confirmation():
    reference = learn_reference([7] * 180 + [8, 8, None, 8, 6, 6])
    assert reference.level == 7
    assert reference.confirmation_buckets == 3
    values = [8, 8, None, 8, 6, 6, 6, 7, 9]
    scored = {0, 1, 3, 4, 5, 6, 7, 8}
    point_flags = {0, 8}
    patterns = {i: {"pattern"} for i in scored}
    points, alerts, confirmed = confirm_alerts(values, scored, point_flags, patterns, reference)
    assert points == {8}
    assert alerts == {6, 8}
    assert confirmed == {6}


def test_nonflat_count_series_keeps_the_existing_alerts():
    values = [7, 3, 6, 12, 2]
    assert learn_reference(values) is None
    assert confirm_alerts(values, {1, 2, 3}, {1}, {3: {"pattern"}, 4: {"pattern"}}, None) == (
        {1}, {1, 3}, set(),
    )
