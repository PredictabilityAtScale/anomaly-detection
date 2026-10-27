"""Bounded synthetic consumer benchmark; runs against an installed offline package."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import statistics
import time

from anomalyzer import analyze, __version__


def workloads():
    count = 1344
    times = [(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat() for i in range(count)]
    values = [1.0+(i%3)*.1 if i%13 == 0 else None for i in range(count)]
    ds = {"id":"volume", "entity":{"customer":"synthetic"}, "units":"calls", "timestamps":times,
          "frequency":"1h", "values":values, "data_policy":{}}
    base = {"schema_version":"1.1", "datasets":[ds],
            "config":{"season_length":1,"training_size":28,"calibration_size":14,"trend":"none"}}
    result = {"1344h_preserve_unknown":deepcopy(base)}
    zero = deepcopy(base)
    zero["datasets"][0]["data_policy"] = {"measurement":"additive_volume","missing":"zero_for_empty","absence_means_zero":True}
    result["1344h_confirmed_empty_volume"] = zero
    relationship = deepcopy(zero)
    relationship["datasets"][0]["id"] = "cost"
    relationship["datasets"][0]["units"] = "dollars"
    relationship["datasets"].append({**deepcopy(zero["datasets"][0]), "id":"calls", "values":[1 if v is not None else None for v in values]})
    relationship["relationships"] = [{"id":"unit-cost","kind":"ratio","numerator":"cost","denominator":"calls","units":"dollars_per_call"}]
    result["1344h_two_sources_and_ratio"] = relationship
    multi = deepcopy(relationship)
    multi["config"].update(recipe="multi-resolution-v1",completed_period_season_length=7)
    result["1344h_two_source_multi_resolution"] = multi
    events = deepcopy(base)
    events["datasets"][0].update(timestamps=[times[i] for i in range(0,count,3)],
        values=[.10+(i%5)*.001 for i in range(0,count,3)], units="dollars_per_call",
        data_policy={"observation_basis":"event_index"})
    events["datasets"][0].pop("frequency")
    result["448_comparable_events"] = events
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    assert 1 <= args.repeats <= 10
    rows = []
    for name, request in workloads().items():
        analyze(request)
        samples = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            result = analyze(request)
            samples.append(time.perf_counter()-started)
        started = time.perf_counter()
        encoded = result.model_dump_json().encode()
        serialization = time.perf_counter()-started
        assert not any(item.status == "failed" for item in result.dataset_results), name
        rows.append({"workload":name,"input_positions":sum(len(d["values"]) for d in request["datasets"]),
            "median_ms":round(statistics.median(samples)*1000,2), "serialization_ms":round(serialization*1000,2),
            "result_bytes":len(encoded), "status":result.status})
    report = {"version":__version__,"environment":platform.platform(),"python":platform.python_version(),
        "repeats":args.repeats,"rows":rows,
        "limits":"Synthetic warm process timings exclude imports, scheduling, cold starts and persistence. No accuracy, capacity or production cost claim."}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
