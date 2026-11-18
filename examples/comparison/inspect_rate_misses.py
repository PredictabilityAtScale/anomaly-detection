"""Inspect sparse misses through real MCP views; preserve the original budget.

Truth labels select cases for retrospective inspection only. They never enter
the monitor request. Follow-ups are exploratory, not fresh validation.
"""
import argparse
import csv
import json
from pathlib import Path

from anomalyzer import compare_rates, monitor_rates
from anomalyzer.mcp import _tool_call
from five_minute_fixtures import write_csv


REFERENCE, LOOKS = 96, 192
WIDTHS = [1, 6, 24]


def call(name, **arguments):
    return _tool_call(name, arguments)["structuredContent"]


def run(fixtures, incidents, output):
    output.mkdir(parents=True, exist_ok=False)
    histories = {}
    for row in csv.DictReader(fixtures.open(encoding="utf-8", newline="")):
        histories.setdefault(row["case"], []).append(dict(id=row["id"], successes=int(row["successes"]),
            trials=int(row["trials"]), timestamp=row["timestamp"], complete=True))
    missed = [row for row in csv.DictReader(incidents.open(encoding="utf-8", newline=""))
              if row["arm"] == "exact_rate" and row["status"] == "missed" and row["cohort"] == "sparse"]
    assert len(missed) == 3
    grades, scans, followups, sensitivity = [], [], [], []
    for event in missed:
        name, start, end = event["case"], int(event["onset"]), int(event["stop"])
        prefix = histories[name][:end]
        key = f"{name}-{event['kind']}"
        request = dict(schema_version="rate-v1", task="monitor_rates", monitor_id=key,
            entity={"customer": f"synthetic-{event['seed']}"},
            context=dict(concern="Investigate recent rate behavior, its exposure and uncertainty.",
                         metric_definition="Successes out of eligible trials; synthetic conversion counts.", known_events=[]),
            samples=prefix, reference_size=REFERENCE, window_sizes=WIDTHS, max_looks=LOOKS,
            assume_independent_trials=True, config=dict(alpha=0.01, min_effect=0.01))
        summary = call("monitor_rates", request=request)
        run_id = summary["run_id"]
        (output/f"{key}-request.json").write_text(json.dumps(request, indent=2)+"\n", encoding="utf-8")
        (output/f"{key}-summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
        cursor, entries = 0, []
        while cursor is not None:
            page = call("list_findings", run_id=run_id, cursor=cursor, limit=100)
            entries.extend(f for f in page["findings"] if start <= f["index"] < end)
            cursor = page["next_cursor"]
        details = []
        for finding in entries:
            detail = call("get_evidence", run_id=run_id, finding_id=finding["id"], limit=1)
            record = detail["record"]
            assert not finding["criterion_met"]  # reproduce the original miss
            if record and record["p_value"] is not None:
                details.append(detail)
                scans.append(dict(case=name, incident=event["kind"], **finding,
                    successes=record["current"]["successes"], trials=record["current"]["trials"],
                    p_value=record["p_value"], threshold=record["threshold"]))
        best = min(details, key=lambda d: d["record"]["p_value"])
        source_rows, cursor = [], 0
        while cursor is not None:
            page = call("get_evidence", run_id=run_id, finding_id=best["finding"]["id"], cursor=cursor, limit=50)
            source_rows.extend(page["samples"])
            cursor = page["next_cursor"]
        for role in ("reference", "current"):
            assert sum(r["trials"] for r in source_rows if r["role"] == role) == best["record"][role]["trials"]
            assert sum(r["successes"] for r in source_rows if r["role"] == role) == best["record"][role]["successes"]
        best["all_source_samples"] = source_rows
        (output/f"{key}-best-evidence.json").write_text(json.dumps(best, indent=2)+"\n", encoding="utf-8")
        source_ref = prefix[:REFERENCE]
        comparisons = (("exact_labeled_interval", source_ref), ("expanded_preincident_reference", prefix[:144]))
        exact = None
        for label, reference in comparisons:
            # The labeled interval is hindsight, not an onset known to a live agent.
            result = compare_rates(dict(entity=request["entity"], context=request["context"],
                reference={"samples": reference}, current={"samples": prefix[start:end]},
                assume_independent_trials=True, config=dict(max_comparisons=LOOKS*len(WIDTHS))))
            followups.append(dict(case=name, incident=event["kind"], analysis=label,
                reference_successes=result.reference["successes"], reference_trials=result.reference["trials"],
                current_successes=result.current["successes"], current_trials=result.current["trials"],
                p_value=result.p_value, threshold=result.threshold, criterion_met=result.change_detected,
                interpretation="exploratory_same_data_not_fresh_confirmation"))
            if label == "exact_labeled_interval":
                exact = result
        for width in (6, 24):
            # Disjoint later rows become available only in a later snapshot.
            later = histories[name][end:end+width]
            result = compare_rates(dict(entity=request["entity"], context=request["context"],
                reference={"samples": source_ref}, current={"samples": later},
                assume_independent_trials=True, config=dict(max_comparisons=LOOKS*len(WIDTHS))))
            followups.append(dict(case=name, incident=event["kind"], analysis=f"subsequent_{width*5}_minutes",
                reference_successes=result.reference["successes"], reference_trials=result.reference["trials"],
                current_successes=result.current["successes"], current_trials=result.current["trials"],
                p_value=result.p_value, threshold=result.threshold, criterion_met=result.change_detected,
                interpretation="later_snapshot_only_not_available_at_incident_end"))
        r, current = best["record"]["reference"], best["record"]["current"]
        grades.append(dict(case=name, incident=event["kind"], onset=start, stop=end,
            reference_successes=r["successes"], reference_trials=r["trials"], reference_rate=r["rate"],
            event_successes=exact.current["successes"], event_trials=exact.current["trials"], event_rate=exact.current["rate"],
            best_index=best["finding"]["index"], best_window=best["finding"]["window_size"],
            best_successes=current["successes"], best_trials=current["trials"], best_rate=current["rate"],
            current_ci_lower=current["interval"]["lower"], current_ci_upper=current["interval"]["upper"],
            p_value=best["record"]["p_value"], adjusted_p_value=best["record"]["adjusted_p_value"],
            threshold=best["record"]["threshold"], missing=current["unknown_count"], incomplete=current["incomplete_count"],
            initial_preview_indexes=";".join(str(f["index"]) for f in summary["findings_preview"]),
            latest_window_rate=summary["latest"]["current"]["rate"], latest_p_value=summary["latest"]["p_value"]))
    for name, samples in histories.items():
        if not name.startswith("sparse-"):
            continue
        for widths in (WIDTHS, [1, 6, 24, 48]):
            result = monitor_rates(dict(monitor_id=name, entity={"customer": name}, samples=samples,
                reference_size=REFERENCE, window_sizes=widths, max_looks=LOOKS, assume_independent_trials=True))
            assert result.status == "horizon_exhausted"
            flags = {r["index"] for r in result.evaluations if r["change_detected"]}
            spans = ((144, 192), (240, 243)) if name.endswith("injected") else ()
            truth = {i for start, end in spans for i in range(start, end)}
            false = flags-truth
            sensitivity.append(dict(case=name, window_sizes=";".join(map(str, widths)), family_size=LOOKS*len(widths),
                false_buckets=len(false), false_runs=sum(i-1 not in false for i in false),
                detected_incidents=sum(bool(flags & set(range(start, end))) for start, end in spans),
                misses=sum(not bool(flags & set(range(start, end))) for start, end in spans)))
    for name, rows in (("misses", grades), ("comparison_scan", scans), ("followups", followups), ("window_sensitivity", sensitivity)):
        write_csv(output/f"{name}.csv", rows)
    print(json.dumps(grades, indent=2), flush=True)
    print(json.dumps(sensitivity, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("analysis/rates-first-validation/fixtures.csv"))
    parser.add_argument("--incidents", type=Path, default=Path("analysis/rates-first-validation/incidents.csv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.fixtures, args.incidents, args.output)
