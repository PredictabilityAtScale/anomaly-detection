"""Generate deterministic synthetic distribution-v1 requests, never observations from users."""
import json
from datetime import datetime, timedelta
from pathlib import Path


DIRECTORY = Path(__file__).resolve().parent


def population(values, prefix):
    return {"samples": [{"id": f"{prefix}-{index:04d}", "value": value} for index, value in enumerate(values)]}


def fixtures():
    numeric = dict(schema_version="distribution-v1", task="compare_distributions", kind="numeric",
        entity={"application": "synthetic-cache-example"}, units="cache_read_fraction",
        reference=population([0, .25, .5, .75, 1] * 80, "reference"),
        current=population([0, 0, .5, 1, 1] * 80, "current"), assume_exchangeable=True)
    ordinary = {**numeric, "current": population([0, .25, .5, .75, 1] * 80, "current")}
    categorical = dict(schema_version="distribution-v1", task="compare_distributions", kind="categorical",
        entity={"application": "synthetic-feature-example"}, units="feature_per_report",
        reference=population([f"feature-{k:02d}" for k in range(16) for _ in range(50)], "reference"),
        current=population([f"feature-{k:02d}" for k in range(16) for _ in range(65 if k < 8 else 35)], "current"),
        assume_exchangeable=True, config=dict(alpha=.05, min_effect=.005, permutations=1999))
    monitoring = dict(schema_version="distribution-v1", task="monitor_distributions", kind="numeric",
        monitor_id="synthetic-cache-family-1", entity={"application": "synthetic-cache-example"}, units="cache_read_fraction",
        samples=population([.25, .5, .5, .75] * 32 + [.25, .5, .5, .75] * 8 + [0, 1] * 64, "call")["samples"],
        order="trusted_sequence", assume_exchangeable=True, reference_size=128, window_sizes=[32, 64],
        max_looks=129, config=dict(alpha=.05, min_effect=.1))
    weighted = dict(schema_version="distribution-v1", task="compare_distributions", kind="categorical",
        entity={"application": "synthetic-weighted-example", "meter": "pages"}, units="pages",
        reference={"weights": {"search": 900, "export": 100}}, current={"weights": {"search": 100, "export": 900}})
    reports = dict(schema_version="distribution-v1", task="compare_distributions", kind="categorical",
        entity={"application": "synthetic-reports", "meter": "pages"}, units="pages_per_report",
        reference=population(["search", "export"] * 16, "reference"),
        current=population(["search", "export"] * 16, "current"),
        assume_exchangeable=True, config=dict(permutations=999))
    for i, sample in enumerate(reports["reference"]["samples"]):
        sample["weight"] = 9 if i % 2 == 0 else 1
    for i, sample in enumerate(reports["current"]["samples"]):
        sample["weight"] = 1 if i % 2 == 0 else 9
    seasonal_samples = []
    for day in ("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"):
        for hour, value in ((8, .8), (21, .1)):
            # Exact offset-aware source times; the explicit policy supplies the
            # IANA zone. Later same-day evening calls are intentionally ignored.
            start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00-07:00")
            seasonal_samples += [dict(id=f"{day}-{hour}-{i:03d}", value=value,
                timestamp=(start+timedelta(seconds=i)).isoformat()) for i in range(32)]
    seasonal = dict(schema_version="distribution-v1", task="compare_seasonal_distributions", kind="numeric",
        entity={"application": "synthetic-scheduled-batch"}, units="cache_read_fraction", samples=seasonal_samples,
        window_start="2026-10-30T08:00:00-07:00", window_end="2026-10-30T09:00:00-07:00",
        as_of="2026-10-30T08:05:00-07:00", assume_exchangeable=True,
        reference_policy=dict(timezone="America/Los_Angeles", matching="daily"))
    return {"numeric-shape": numeric, "numeric-ordinary": ordinary, "categorical-mix": categorical,
            "numeric-monitor": monitoring, "weighted-composition": weighted, "weighted-reports": reports,
            "seasonal-morning": seasonal}


if __name__ == "__main__":
    for name, request in fixtures().items():
        (DIRECTORY / f"{name}.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
