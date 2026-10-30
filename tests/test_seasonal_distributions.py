"""Explicit seasonal population matching, including calendar and evidence limits."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import jsonschema
import pytest
from pydantic import ValidationError

from anomalyzer import (
    analyze, compare_distributions, compare_seasonal_distributions,
    SeasonalDistributionRequest, SeasonalDistributionResult,
)
from anomalyzer.mcp import TOOLS, handle


ZONE = ZoneInfo("America/Los_Angeles")


def samples(day, hour=8, values=None, prefix=None):
    values = [.8] * 32 if values is None else values
    prefix = prefix or f"{day}-{hour}"
    start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=ZONE)
    return [dict(id=f"{prefix}-{i}", value=value, timestamp=(start+timedelta(seconds=i)).isoformat())
            for i, value in enumerate(values)]


def request(days=("2026-10-29", "2026-10-28", "2026-10-27"), current="2026-10-30"):
    rows = [s for day in days for s in samples(day)] + samples(current)
    start = datetime.fromisoformat(f"{current}T08:00:00").replace(tzinfo=ZONE)
    return dict(kind="numeric", entity={"app": "synthetic"}, units="cache_fraction", samples=rows,
        window_start=start.isoformat(), window_end=(start+timedelta(hours=1)).isoformat(),
        as_of=(start+timedelta(minutes=5)).isoformat(),
        reference_policy=dict(timezone=ZONE.key, matching="daily"), assume_exchangeable=True)


def test_matching_keeps_expected_morning_behavior_quiet_and_detects_changed_mornings():
    body = request()
    for day in ("2026-10-29", "2026-10-28", "2026-10-27"):
        body["samples"] += samples(day, 21, [.1] * 32)
    matched = compare_seasonal_distributions(body)
    assert matched.status == "completed" and not matched.change_detected
    assert matched.comparison.p_value == 1
    assert matched.selection["reference_windows"] == 3
    assert matched.selection["current_window"]["partial"]
    broad = compare_distributions(dict(kind=body["kind"], entity=body["entity"], units=body["units"],
        reference={"samples": [s for s in body["samples"] if not s["id"].startswith("2026-10-30")]},
        current={"samples": samples("2026-10-30")}, assume_exchangeable=True))
    assert broad.change_detected  # expected time-of-day composition, not regression
    for sample in body["samples"]:
        if sample["id"].startswith("2026-10-30"):
            sample["value"] = .1
    assert compare_seasonal_distributions(body).change_detected


def test_partial_progress_and_half_open_boundaries_exclude_later_calls():
    body = request()
    for day in ("2026-10-29", "2026-10-28", "2026-10-27", "2026-10-30"):
        start = datetime.fromisoformat(f"{day}T08:05:00").replace(tzinfo=ZONE)
        body["samples"].append(dict(id=f"{day}-at-cutoff", timestamp=start.isoformat(), value=0))
        body["samples"] += samples(day, 9, [0] * 8)
    result = compare_seasonal_distributions(body)
    assert result.comparison.reference["mean"] == .8
    assert result.comparison.current["mean"] == .8
    assert all("at-cutoff" not in s for s in result.selection["reference_sample_ids"])
    assert result.selection["current_measured_samples"] == 32
    assert result.selection["reference_measured_samples"] == 96
    assert not result.change_detected


def test_same_weekday_and_weekday_weekend_are_explicit_policies():
    body = request(days=("2026-10-23", "2026-10-16", "2026-10-09", "2026-10-29", "2026-10-24"))
    body["reference_policy"]["matching"] = "same_weekday"
    result = compare_seasonal_distributions(body)
    selected = [row["date"] for row in result.selection["windows"] if row["status"] == "selected"]
    assert selected == ["2026-10-23", "2026-10-16", "2026-10-09"]
    body["reference_policy"]["matching"] = "weekday_weekend"
    result = compare_seasonal_distributions(body)
    assert result.selection["reference_windows"] == 4
    assert not any(s.startswith("2026-10-24") for s in result.selection["reference_sample_ids"])


def test_distinct_day_support_cannot_be_replaced_by_one_large_batch():
    body = request(days=("2026-10-29",))
    body["samples"] += samples("2026-10-29", values=[.8] * 1000, prefix="one-large-batch")
    result = compare_seasonal_distributions(body)
    assert result.status == "insufficient_history" and result.comparison is None
    assert not result.change_detected and result.selection["reference_windows"] == 1


def test_fallback_is_opt_in_support_based_and_preserves_testing_allocation():
    body = request()
    body["reference_policy"]["matching"] = "same_weekday"
    assert compare_seasonal_distributions(body).status == "insufficient_history"
    body["reference_policy"]["fallback"] = "daily"
    body["config"] = dict(max_comparisons=20, comparison_index=7)
    result = compare_seasonal_distributions(body)
    assert result.status == "completed"
    assert result.selection["fallback_used"] and result.selection["resolved_matching"] == "daily"
    assert len(result.selection["attempts"]) == 2
    assert result.comparison.testing["comparison_index"] == 7
    assert result.comparison.testing["max_comparisons"] == 20
    assert result.testing["threshold"] == result.comparison.threshold == .01/20
    body = request(days=("2026-10-23", "2026-10-16", "2026-10-09", "2026-10-29"))
    body["reference_policy"].update(matching="same_weekday", fallback="daily")
    assert not compare_seasonal_distributions(body).selection["fallback_used"]


def test_nearest_complete_prior_windows_are_bounded_without_silent_subsampling():
    body = request(days=("2026-10-29", "2026-10-28", "2026-10-27", "2026-10-26"))
    body["reference_policy"].update(min_windows=2, max_windows=2)
    result = compare_seasonal_distributions(body)
    assert result.selection["reference_windows"] == 2
    assert {s["reason"] for s in result.selection["excluded_samples"]} == {"reference_window_limit"}
    assert all(s.startswith(("2026-10-29", "2026-10-28")) for s in result.selection["reference_sample_ids"])


def test_future_history_and_source_order_do_not_change_the_selected_reference():
    body = request()
    before = compare_seasonal_distributions(body)
    body["samples"] += samples("2026-10-31")
    body["samples"].reverse()
    after = compare_seasonal_distributions(body)
    assert before.reference_id == after.reference_id
    assert before.selection_id == after.selection_id
    assert before.comparison == after.comparison
    assert {row["reason"] for row in after.selection["excluded_samples"]} == {"at_or_after_assessed_end"}


def test_unknowns_incomplete_calls_and_low_volume_windows_remain_visible():
    body = request(days=("2026-10-29", "2026-10-28", "2026-10-27", "2026-10-26"))
    for sample in body["samples"]:
        if sample["id"].startswith("2026-10-29"):
            sample["value"] = None
    body["samples"][-1]["complete"] = False
    body["config"] = {"missing_current": "break"}
    result = compare_seasonal_distributions(body)
    assert result.status == "insufficient_history" and not result.change_detected
    row = next(row for row in result.selection["windows"] if row["date"] == "2026-10-29")
    assert row["reason"] == "insufficient_window_support"
    assert result.selection["reference_windows"] == 3
    assert result.comparison.current["incomplete_count"] == 1


def test_local_eight_am_matching_tracks_dst_offset_changes():
    body = request(days=("2026-03-02", "2026-02-23", "2026-02-16"), current="2026-03-09")
    body["reference_policy"].update(matching="same_weekday")
    result = compare_seasonal_distributions(body)
    assert result.status == "completed"
    selected = [row for row in result.selection["windows"] if row["status"] == "selected"]
    assert all(datetime.fromisoformat(row["start"]).hour == 16 for row in selected)
    assert datetime.fromisoformat(result.selection["current_window"]["start"]).hour == 15
    assert not result.change_detected


@pytest.mark.parametrize("current,dates,reason", [
    ("2026-11-08", ("2026-11-01", "2026-10-25", "2026-10-18"), "ambiguous_local_time"),
    ("2026-03-15", ("2026-03-08", "2026-03-01", "2026-02-22"), "nonexistent_local_time"),
])
def test_ambiguous_and_nonexistent_historical_boundaries_are_skipped(current, dates, reason):
    body = request(days=dates, current=current)
    hour = 1 if "11-" in current else 2
    for sample in body["samples"]:
        original = datetime.fromisoformat(sample["timestamp"]).astimezone(ZONE)
        sample["timestamp"] = original.replace(hour=hour, minute=30).isoformat()
    start = datetime.fromisoformat(f"{current}T{hour:02d}:15:00").replace(tzinfo=ZONE)
    body.update(window_start=start.isoformat(), window_end=(start+timedelta(minutes=30)).isoformat(), as_of=(start+timedelta(minutes=30)).isoformat())
    body["reference_policy"].update(matching="same_weekday", min_windows=2)
    result = compare_seasonal_distributions(body)
    skipped = next(row for row in result.selection["windows"] if row["date"] == dates[0])
    assert skipped["reason"] == reason
    assert result.selection["reference_windows"] == 2


@pytest.mark.parametrize("mutation", [
    lambda b: b["reference_policy"].update(timezone="Not/AZone"),
    lambda b: b["reference_policy"].update(min_windows=5, max_windows=2),
    lambda b: b["reference_policy"].update(fallback="daily"),
    lambda b: b["reference_policy"].update(matching="automatic"),
    lambda b: b.update(window_end=b["window_start"]),
    lambda b: b.update(as_of=b["window_start"]),
    lambda b: b.update(window_end="2026-10-31T01:00:00-07:00"),
    lambda b: b["samples"][0].pop("timestamp"),
    lambda b: b["samples"][0].update(id=b["samples"][-1]["id"]),
])
def test_invalid_matching_contracts_fail_explicitly(mutation):
    body = request()
    mutation(body)
    with pytest.raises(ValidationError):
        compare_seasonal_distributions(body)


def test_current_dst_transition_window_is_rejected_instead_of_guessing():
    body = request()
    body.update(window_start="2026-11-01T00:30:00-07:00", window_end="2026-11-01T02:30:00-08:00", as_of="2026-11-01T02:30:00-08:00")
    with pytest.raises(ValidationError, match="offset transition"):
        compare_seasonal_distributions(body)


def test_categorical_weighted_reports_and_unordered_timestamp_cohorts_are_supported():
    body = request()
    body.update(kind="categorical", units="pages_per_report")
    for i, sample in enumerate(body["samples"]):
        sample.update(value="export" if i % 2 else "search", weight=9 if i % 2 else 1)
        sample["timestamp"] = sample["timestamp"][:11] + "08:00:00-07:00"
    result = compare_seasonal_distributions(body)
    assert result.status == "completed" and not result.change_detected
    assert result.comparison.reference["sample_count"] == 96
    assert result.comparison.reference["total_weight"] == 480


def test_budget_exhaustion_cannot_trigger(monkeypatch):
    from anomalyzer.budget import RuntimeBudget
    def exhausted(self):
        raise TimeoutError("fixture")
    monkeypatch.setattr(RuntimeBudget, "check", exhausted)
    result = compare_seasonal_distributions(request())
    assert result.status == "budget_exceeded" and not result.change_detected
    assert result.comparison is None


def test_seasonal_api_cli_mcp_and_generated_schemas_agree():
    body = request()
    expected = compare_seasonal_distributions(body).model_dump(mode="json")
    canonical = {**body, "schema_version": "distribution-v1", "task": "compare_seasonal_distributions"}
    assert analyze(canonical).model_dump(mode="json") == expected
    assert analyze(SeasonalDistributionRequest(**canonical)).model_dump(mode="json") == expected
    command = [sys.executable, "-m", "anomalyzer", "compare-seasonal-distributions", "-"]
    run = subprocess.run(command, input=json.dumps(body), text=True, capture_output=True, check=True)
    assert json.loads(run.stdout) == expected
    human = subprocess.run(command+["--format", "text"], input=json.dumps(body), text=True, capture_output=True, check=True)
    assert "Matched prior windows: 3" in human.stdout
    tool = next(tool for tool in TOOLS if tool["name"] == "compare_seasonal_distributions")
    result = handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name=tool["name"], arguments={"request": body})))
    assert result["result"]["structuredContent"] == expected
    jsonschema.validate({"request": body}, tool["inputSchema"])
    jsonschema.validate(expected, tool["outputSchema"])
    root = Path(__file__).parents[1]/"schemas"
    for name, model in (("seasonal-distribution-request", SeasonalDistributionRequest), ("seasonal-distribution-result", SeasonalDistributionResult)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        assert schema == json.loads((root/f"{name}.schema.json").read_text())
