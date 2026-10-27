"""Reproducible continuation of the README's feature-by-feature progression."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def dataset(values, **extra):
    return {"id": "series", "entity": {"customer": "synthetic"}, "units": "calls",
            "timestamps": [(datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(hours=i)).isoformat() for i in range(len(values))],
            "values": values, "frequency": "1h", **extra}


def request(ds, **config):
    return {"schema_version": "1.1", "datasets": [ds],
            "config": {"season_length": 1, "training_size": 4, "calibration_size": 3, "trend": "none", **config}}


def fixtures():
    result = {}
    values = [10, 12, 11, 9, None, 10, None, 11, 9, None, 10, 12, None, 10, 11, 9, 10, 30]
    preserve = request(dataset(values, coverage=["empty" if v is None else "complete" for v in values],
                               data_policy={"measurement": "additive_volume"}))
    zero = deepcopy(preserve)
    zero["datasets"][0]["data_policy"]["missing"] = "zero_for_empty"
    result.update(preserve=preserve, zero_empty=zero)
    result["statuses"] = request(dataset([10, 0, None, 8, 10, 9, 11, 0, 12, None, 9, 10, 20, 3],
        coverage=["complete"]*2+["unknown"]+["complete"]*6+["unknown"]+["complete"]*3+["incomplete"], data_policy={}))
    values = [1.0 if i % 12 == 0 else None for i in range(84)]
    values[-1] = 40
    result["quiet_volume"] = request(dataset(values,
        coverage=["empty" if v is None else "complete" for v in values],
        data_policy={"measurement": "additive_volume", "missing": "zero_for_empty"}), season_length=12, training_size=36, calibration_size=24)
    hours = [0, 1, 8, 35, 80, 100, 130, 180, 220, 300, 350, 430]
    costs = [.10, .11, .09, .10, .09, .10, .11, .10, .09, .10, .11, .80]
    events = dataset(costs, units="dollars_per_call", data_policy={"observation_basis": "event_index"})
    events.pop("frequency")
    events["timestamps"] = [(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(hours=h)).isoformat() for h in hours]
    result["cost_events"] = request(events)
    calendar = deepcopy(events)
    calendar["frequency"] = "1h"
    calendar["data_policy"] = {}
    result["cost_calendar"] = request(calendar, season_length=24)
    phase = dataset([100+[0,10,-5,8,2,-12,-8][i%7]+[.2,-.4,.6,-.3,.1][i%5] for i in range(90)],
                    frequency="1d", data_policy={})
    phase["timestamps"] = [(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat() for i in range(90)]
    for index in (8, 21, 35, 50, 69):
        phase["values"][index] = None
    phase["values"][-1] += 35
    result["weekday_phase"] = request(phase, season_length=7, training_size=28, calibration_size=14)
    result["pattern_gap"] = request(dataset([100]*4+[99,100,101]+[102]*4+[None]+[102]*7, data_policy={}), point_threshold=100)
    result["first_rule"] = request(dataset([100], data_policy={}, units="measured_units",
        rules=[{"id": "example-range", "kind": "acceptable_range", "minimum": 0, "maximum": 20}]))
    result["first_rule"]["policy"] = {"allow_explicit_rules": True}
    relation = request(dataset([1,2,None,3,0,2,4,5,1,3,2,9], units="dollars", data_policy={"measurement":"additive_volume"}))
    relation["datasets"].append(dataset([10,0,10,10,0,20,40,50,10,None,20,10], id="calls", data_policy={"measurement":"additive_volume"}))
    relation["relationships"] = [{"id":"unit-cost","kind":"ratio","numerator":"series","denominator":"calls","units":"dollars_per_call"}]
    result["relationships"] = relation
    daily = request(dataset([1.0]*60, data_policy={"measurement":"additive_volume"}), recipe="multi-resolution-v1",
                    completed_period_season_length=1)
    daily["datasets"][0]["values"][5] = None
    daily["datasets"][0]["coverage"] = ["complete"]*59+["incomplete"]
    daily["datasets"][0]["values"][-1] = 3
    result["unfinished_daily"] = daily
    # Genuine distinct calls share the recorded timestamp; IDs do not order them.
    same_time = {"id":"call-cost", "entity":{"application":"synthetic"}, "units":"dollars_per_call",
        "timestamps":["2026-01-01T09:00:00.123Z"]*3+["2026-01-01T09:00:05.456Z"]*4+["2026-01-01T09:00:10.789Z"]*3,
        "values":[.10,.10,.10,.09,.10,.11,.10,.80,.12,.90],
        "event_ids":[f"call-{i:02}" for i in range(10)],
        "data_policy":{"observation_basis":"event_index"},
        "rules":[{"id":"illustrative-cap","kind":"acceptable_range","minimum":0,"maximum":.20}]}
    result["identified_calls"] = request(same_time, training_size=2, calibration_size=3)
    corrected = deepcopy(result["identified_calls"])
    corrected["datasets"][0]["revisions"] = [{"event_id":"call-07", "timestamp":same_time["timestamps"][7],
        "value":.85,"available_at":"2026-01-01T09:01:00Z","revision_id":"corrected-cost-1"}]
    corrected["context"] = {"as_of":"2026-01-01T09:02:00Z"}
    result["identified_corrected"] = corrected
    before = deepcopy(corrected)
    before["context"]["as_of"] = "2026-01-01T09:00:30Z"
    result["identified_before_correction"] = before
    tied_pattern = deepcopy(same_time)
    tied_pattern.update(values=[.10,.10,.10,.09,.10,.11,.10]+[.12]*12,
        timestamps=same_time["timestamps"][:7]+[same_time["timestamps"][-1]]*12,
        event_ids=[f"call-{i:02}" for i in range(19)])
    result["identified_pattern_ties"] = request(tied_pattern, training_size=2, calibration_size=3, point_threshold=100)
    ordered = deepcopy(tied_pattern)
    ordered["event_sequence"] = list(range(100,119))
    ordered["data_policy"]["event_order"] = "trusted_sequence"
    result["identified_pattern_sequence"] = request(ordered, training_size=2, calibration_size=3, point_threshold=100)
    return result


def retry_fixture():
    document = deepcopy(fixtures()["identified_calls"])
    ds = document["datasets"][0]
    for name in ("timestamps", "values", "event_ids"):
        ds[name].append(ds[name][-1])
    return document


def generate():
    directory = Path(__file__).parent / "sparse"
    directory.mkdir(exist_ok=True)
    for name, document in {**fixtures(), "identified_retry":retry_fixture()}.items():
        (directory/f"{name}.json").write_text(json.dumps(document, indent=2)+"\n", encoding="utf-8")


def run_checks():
    from anomalyzer import analyze
    directory = Path(__file__).parent / "sparse"
    outputs = {name: analyze(json.loads((directory/f"{name}.json").read_text())) for name in fixtures()}
    for name, result in outputs.items():
        assert all(item.status != "failed" for item in result.dataset_results), name
    preserve, zero = [outputs[n].dataset_results[0] for n in ("preserve", "zero_empty")]
    assert preserve.data_quality["zero_filled_count"] == 0
    assert zero.data_quality["zero_filled_count"] == 4
    assert outputs["statuses"].dataset_results[0].data_quality["samples"][-1]["value"] is None
    assert outputs["quiet_volume"].cases
    assert outputs["cost_calendar"].status == "insufficient_history"
    assert outputs["cost_events"].cases
    phase = outputs["weekday_phase"].dataset_results[0]
    last = phase.methods[0].evidence[-1]
    assert last["index"] == 89 and last["triggers"] == ["point"]
    assert not any(p["rule"] == "nelson_rule_2" for p in outputs["pattern_gap"].dataset_results[0].anomaly_patterns)
    assert outputs["first_rule"].status == "insufficient_history" and outputs["first_rule"].cases[0].action_eligible
    reasons = [row.unavailable_reason for row in outputs["relationships"].relationship_results[0].lineage]
    assert "missing_source_value" in reasons and "zero_denominator" in reasons
    daily = next(item for item in outputs["unfinished_daily"].dataset_results if item.resolution == "completed_period")
    assert [r["complete"] for r in daily.data_quality["aggregation"]] == [False, True, False]
    calls = outputs["identified_calls"]
    assert {c.event_id for c in calls.cases} == {"call-07","call-09"}
    assert not calls.dataset_results[0].anomaly_patterns
    again = analyze(fixtures()["identified_calls"])
    assert [c.model_dump() for c in calls.cases] == [c.model_dump() for c in again.cases]
    assert [c.model_dump() for c in calls.cases] == [c.model_dump() for c in outputs["identified_before_correction"].cases]
    original = next(c for c in calls.cases if c.event_id == "call-07")
    revised = next(c for c in outputs["identified_corrected"].cases if c.event_id == "call-07")
    assert original.id == revised.id and original.revision_id != revised.revision_id
    assert not outputs["identified_pattern_ties"].dataset_results[0].anomaly_patterns
    assert any(p["rule"] == "nelson_rule_2" for p in outputs["identified_pattern_sequence"].dataset_results[0].anomaly_patterns)
    try:
        analyze(json.loads((directory/"identified_retry.json").read_text()))
    except ValueError as exc:
        assert "duplicate logical" in str(exc)
    else:
        raise AssertionError("Retry delivery must not become another logical call")
    for name, result in outputs.items():
        print(f"PASS sparse/{name}: {result.status}; {len(result.cases)} numerical case(s)")
    return outputs


if __name__ == "__main__":
    generate()
    run_checks()
