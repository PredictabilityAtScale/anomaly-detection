"""Standalone consumer example; needs only an installed Anomalyzer and its deps.

This synthetic example does not integrate Guard or deliver notifications.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-prefix", type=Path, required=True)
    args = parser.parse_args()

    # Prove the example and library never need network at execution time.
    def offline(*args, **kwargs):
        raise AssertionError("network access attempted during analysis")
    socket.socket = offline
    socket.create_connection = offline

    import anomalyzer
    import pydantic
    import pydantic_core
    import typing_extensions
    from anomalyzer import (
        Request, RequestV11, Result, ResultV11, analyze, analyze_series,
        analyze_relationships, get_case, replay_policy,
    )
    from anomalyzer.contracts import ActionPolicy, Context, Dataset, Settings

    prefix = args.expect_prefix.resolve()
    for module in (anomalyzer, pydantic, pydantic_core, typing_extensions):
        assert Path(module.__file__).resolve().is_relative_to(prefix), module.__file__
    assert anomalyzer.__version__ == importlib.metadata.version("anomalyzer")

    values = [100 + [-2, -1, 0, 1, 2, 1, -1][i % 7] for i in range(75)]
    values[65] = 150
    config = Settings(season_length=7, training_size=28, calibration_size=14,
                      trend="none")
    legacy = analyze(values, config)
    assert isinstance(legacy, Result)
    assert legacy.status == "completed"
    assert any(row["triggers"] for row in legacy.methods[0].evidence)
    assert legacy.methods[0].diagnostics["detection_readiness"]
    assert analyze(Request(datasets=[Dataset(values=values)], config=config)).status == "completed"
    assert analyze_series(values, config).status == "completed"
    assert anomalyzer.analyze_dataset(Dataset(values=values), config, Context()).status == "completed"

    timestamps = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat()
                  for i in range(len(values))]
    datasets = [
        {"id": name, "values": data, "timestamps": timestamps, "frequency": "1d",
         "entity": {"customer": "synthetic"}, "units": "count"}
        for name, data in (("cost", values), ("calls", [100.0] * len(values)))
    ]
    datasets[0]["rules"] = [{"id": "cost-step", "kind": "maximum_absolute_change",
                              "threshold": 10}]
    request = RequestV11.model_validate({
        "schema_version": "1.1", "datasets": datasets,
        "relationships": [{"id": "unit-cost", "kind": "ratio", "numerator": "cost",
                           "denominator": "calls", "units": "cost_per_call"}],
        "config": config.model_dump(),
    })
    result = analyze_relationships(request)
    assert isinstance(result, ResultV11)
    assert result.status == "completed"
    assert analyze(request).status == "completed"
    assert analyze_series(Dataset.model_validate({
        **datasets[1], "timezone": "America/Los_Angeles"})).status == "completed"
    assert result.relationship_results[0].lineage[65].value == 1.5
    short = analyze_relationships({**request.model_dump(mode="json"),
        "datasets": [{**datasets[0], "values": values[:4], "timestamps": timestamps[:4]}],
        "relationships": []})
    assert any(a.maturity == "early" for a in short.dataset_results[0].assessments)
    assert any(a.classification == "criterion_violation"
               for item in result.dataset_results for a in item.assessments)
    assert result.cases
    before = result.model_dump(mode="json")
    replayed = replay_policy(result, ActionPolicy(allow_explicit_rules=True))
    assert result.model_dump(mode="json") == before
    assert any(case.action_eligible for case in replayed.cases)
    assert get_case(replayed, replayed.cases[0].id) == replayed.cases[0]
    assert get_case(replayed, "missing") is None
    ResultV11.model_validate_json(replayed.model_dump_json())

    # A sustained pattern can exist with no point trigger.
    shift = [100 + [-2, -1, 0, 1, 2, 1, -1][i % 7] + (0.8 if i >= 50 else 0)
             for i in range(75)]
    patterned = analyze(shift, {"recipe": "adaptive-seasonal-v1", "season_length": 7,
                               "training_size": 28, "calibration_size": 14,
                               "point_threshold": 50, "cusum_h": 5})
    assert patterned.anomaly_patterns
    assert not any(row["triggers"] for row in patterned.methods[0].evidence)
    hourly = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)).isoformat()
              for i in range(8 * 24 + 12)]
    multi = analyze({"datasets": [{"timestamps": hourly, "frequency": "1h",
                                  "values": [i % 24 + 1 for i in range(len(hourly))]}],
                     "config": {"recipe": "multi-resolution-v1", "training_size": 2,
                                "calibration_size": 3, "completed_period_season_length": 1}})
    assert multi.data_quality["incomplete_period"]["included_in_completed_period_view"] is False
    # New source contracts must work from the distribution, without local fixtures.
    sparse = {"schema_version":"1.1", "datasets":[{
        "id":"calls","entity":{"customer":"synthetic"},"units":"calls",
        "timestamps":timestamps[:12],"frequency":"1d","values":[1,None,0,1,1,0,1,1,None,1,0,20],
        "coverage":["complete","empty"]+["complete"]*6+["unknown"]+["complete"]*3,
        "data_policy":{"measurement":"additive_volume","missing":"zero_for_empty"},
        "rules":[{"id":"measured-limit","kind":"acceptable_range","minimum":0,"maximum":10}]}],
        "config":{"season_length":1,"training_size":4,"calibration_size":3,"trend":"none"}}
    result_sparse = analyze_relationships(sparse)
    quality = result_sparse.dataset_results[0].data_quality
    assert quality["zero_filled_count"] == 1 and quality["samples"][8]["value"] is None
    assert result_sparse.cases
    events = {**sparse["datasets"][0], "data_policy":{"observation_basis":"event_index"}}
    events.pop("frequency")
    assert analyze_series(events, sparse["config"]).dataset_results[0].data_quality["coordinate"] == "event_index"
    identified = dict(id="call-cost", entity={"application":"synthetic"}, units="dollars_per_call",
        timestamps=["2026-01-01T00:00:00Z"]*2+["2026-01-01T01:00:00Z"]*3+["2026-01-01T02:00:00Z"]*2,
        values=[.10,.10,.09,.10,.11,.80,.90], event_ids=[f"call-{i}" for i in range(7)],
        data_policy={"observation_basis":"event_index"},
        rules=[{"id":"example-cap","kind":"acceptable_range","minimum":0,"maximum":.20}])
    actual = analyze_series(identified, {"season_length":1,"training_size":2,"calibration_size":3,"trend":"none"})
    assert {case.event_id for case in actual.cases} == {"call-5","call-6"}
    assert not actual.dataset_results[0].anomaly_patterns
    assert actual.dataset_results[0].data_quality["event_identity_contract"] == "event-identity-v1"
    assert [case.id for case in analyze_series(identified, {"training_size":2,"calibration_size":3,"trend":"none"}).cases] == [case.id for case in actual.cases]
    print(json.dumps({"version": anomalyzer.__version__, "status": result.status,
                      "cases": len(result.cases), "offline": True,
                      "pydantic_core": pydantic_core.__file__}))


if __name__ == "__main__":
    main()
