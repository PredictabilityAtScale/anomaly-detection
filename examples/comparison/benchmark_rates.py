"""Fresh five-minute rate replay against the existing ratio-residual path."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from random import Random

from anomalyzer import analyze, monitor_rates
from five_minute_fixtures import write_csv


REFERENCE, HOLDOUT = 96, 192
WINDOWS = [1, 6, 24]
SEEDS = (13007, 72019)


def ratio_arm(samples):
    datasets = [dict(id=name, entity={"case": "rates"}, frequency="5min", units=name,
        values=[s[field] for s in samples], timestamps=[s["timestamp"] for s in samples])
        for name, field in (("successes", "successes"), ("trials", "trials"))]
    result = analyze(dict(schema_version="1.1", datasets=datasets,
        relationships=[dict(id="rate", kind="ratio", numerator="successes", denominator="trials", units="fraction")],
        config=dict(trend="none"))).relationship_results[0]
    if result.status in ("failed", "partial"):
        raise RuntimeError(result.error)
    evidence = {e["index"]: e for method in result.methods for e in method.evidence
                if e["index"] >= REFERENCE and e["signal_maturity"] == "calibrated"}
    flags = {i for i, e in evidence.items() if e["triggers"]} | {
        p["detection_index"] for p in result.anomaly_patterns if p["detection_index"] in evidence}
    return set(evidence), flags, {}


def rate_arm(samples):
    replay = monitor_rates(dict(monitor_id="benchmark", entity={"case": "rates"}, samples=samples,
        reference_size=REFERENCE, window_sizes=WINDOWS, max_looks=HOLDOUT, assume_independent_trials=True,
        config=dict(alpha=0.01, min_effect=0.01, max_runtime_seconds=60)))
    if replay.status == "partial":
        raise RuntimeError(replay.reasons)
    scored, flags, status = set(), set(), {}
    for row in replay.evaluations:
        i = row["index"]
        status.setdefault(i, []).append(row["status"])
        if row["status"] == "completed":
            scored.add(i)
        if row["change_detected"]:
            flags.add(i)
    return scored, flags, {i: ";".join(sorted(set(s))) for i, s in status.items()}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    cases, incidents, buckets, inputs = [], [], [], []
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    events = ((REFERENCE+48, 48, 0.35, "sustained_rise"), (REFERENCE+144, 3, 0.55, "brief_rise"))
    for cohort, exposure, clustered in (("sparse", (0, 1, 2, 5), False),
            ("small", (10, 20, 50), False), ("busy", (1000, 2000), False),
            ("clustered-sparse-stress", (0, 1, 2, 5), True)):
        for seed in SEEDS:
            rng = Random(seed)
            base, injected = [], []
            for i in range(REFERENCE+HOLDOUT):
                trials = rng.choice(exposure)
                draws = [rng.random()] * trials if clustered else [rng.random() for _ in range(trials)]
                probability = next((p for at, length, p, _ in events if at <= i < at+length), 0.1)
                row = dict(id=str(i), trials=trials, timestamp=(start+i*timedelta(minutes=5)).isoformat())
                base.append(dict(**row, successes=sum(u < 0.1 for u in draws)))
                injected.append(dict(**row, successes=sum(u < probability for u in draws)))
            for variant, samples in (("control", base), ("injected", injected)):
                case = f"{cohort}-{seed}-{variant}"
                truth = {i for at, length, _, _ in events for i in range(at, at+length)} if variant == "injected" else set()
                inputs.extend(dict(case=case, index=i, incident=i in truth, **s) for i, s in enumerate(samples))
                arms = {}
                for arm, function in (("ratio_residual", ratio_arm), ("exact_rate", rate_arm)):
                    scored, flags, statuses = function(samples)
                    arms[arm] = (scored, flags)
                    false = flags-truth
                    tags = dict(case=case, cohort=cohort, variant=variant, seed=seed, arm=arm,
                        model_valid=not clustered)
                    cases.append(dict(**tags, scored=len(scored), unscored=HOLDOUT-len(scored),
                        scored_normal=len(scored-truth), false_buckets=len(false),
                        false_runs=sum(i-1 not in false for i in false)))
                    for at, length, _, kind in events if variant == "injected" else ():
                        span = set(range(at, at+length))
                        hit = min(span & flags, default=None)
                        incidents.append(dict(**tags, kind=kind, onset=at, stop=at+length,
                            status="detected" if hit is not None else "missed" if scored & span else "unassessed",
                            scored_buckets=len(scored & span), unscored_buckets=length-len(scored & span),
                            delay_minutes=5*(hit-at) if hit is not None else None))
                    buckets.extend(dict(**tags, index=i, successes=samples[i]["successes"], trials=samples[i]["trials"],
                        incident=i in truth, scored=i in scored, flag=i in flags if i in scored else None,
                        statuses=statuses.get(i)) for i in range(REFERENCE, REFERENCE+HOLDOUT))
                    print(case, arm, cases[-1], flush=True)
                common = (arms["ratio_residual"][0] & arms["exact_rate"][0]) - truth
                for row in cases[-2:]:
                    false = arms[row["arm"]][1] & common
                    row.update(shared_normal=len(common), shared_false_buckets=len(false),
                               shared_false_runs=sum(i-1 not in false for i in false))
    for name, rows in (("cases", cases), ("incidents", incidents), ("buckets", buckets), ("fixtures", inputs)):
        write_csv(output/f"{name}.csv", rows)
    summary = {}
    for scope, valid in (("independent_binomial", True), ("clustered_stress", False)):
        summary[scope] = {}
        for arm in ("ratio_residual", "exact_rate"):
            group = [r for r in cases if r["arm"] == arm and r["model_valid"] == valid]
            events = [r for r in incidents if r["arm"] == arm and r["model_valid"] == valid]
            summary[scope][arm] = dict(**{k: sum(r[k] for r in group) for k in
                ("scored", "unscored", "scored_normal", "false_buckets", "false_runs", "shared_normal", "shared_false_buckets", "shared_false_runs")},
                incidents=dict(Counter(r["status"] for r in events)))
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output)
