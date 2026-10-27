"""Exact timestamp alignment for declared relationships."""
from dataclasses import dataclass

from .contracts import Context, DatasetV11, Settings
from .validation import prepare, timestamp


@dataclass
class PreparedDataset:
    dataset: DatasetV11
    times: list[str | None]
    values: list[float | None]
    quality: dict
    source_indexes: list[int]


def prepare_source(dataset: DatasetV11, settings: Settings,
                   context: Context, budget=None) -> PreparedDataset:
    from .sparse import normalize, uses_policy
    explicit = uses_policy(dataset)
    times, values, quality = (normalize(dataset, settings, context, budget)
                              if explicit else prepare(dataset, settings, context))
    if dataset.timestamps is None:
        indexes = list(range(len(values)))
    else:
        if quality["duplicate_count"] and dataset.data_policy is None:
            raise ValueError(
                "relationship lineage requires unique source timestamps; duplicates are not supported")
        by_time = {
            timestamp(value, dataset.timezone).isoformat(): index
            for index, value in enumerate(dataset.timestamps)
        }
        indexes = ([sample["source_index"] if len(sample["source_indexes"]) <= 1 else -1
                    for sample in quality["samples"]] if explicit else [by_time.get(value, -1) for value in times])
        # Retain trailing explicitly incomplete periods for relationship
        # alignment, but represent their values as unavailable. The
        # single-series engine still receives the original Dataset and excludes
        # these periods during its own preparation.
        for item in ([] if explicit else quality.get("incomplete_periods", [])):
            times.append(item["timestamp"])
            values.append(None)
            indexes.append(item["index"])
    return PreparedDataset(dataset, times, values, quality, indexes)


def exact_sources(ids: list[str], prepared: dict[str, PreparedDataset]):
    sources = [prepared[source_id] for source_id in ids]
    if any(source.dataset.timestamps is None for source in sources):
        raise ValueError("exact relationship alignment requires timestamped datasets")
    frequencies = {source.dataset.frequency for source in sources}
    if len(frequencies) != 1:
        raise ValueError("related datasets must declare the same cadence")
    bases = {source.quality.get("coordinate") == "event_index" for source in sources}
    if len(bases) != 1:
        raise ValueError("related datasets must share the observation basis")
    entities = {tuple(sorted(source.dataset.entity.items())) for source in sources}
    if len(entities) != 1:
        raise ValueError("related datasets must declare matching entity metadata")
    reference = sources[0].times
    if any(source.times != reference for source in sources[1:]):
        raise ValueError(
            "exact relationship alignment requires identical UTC-normalized timestamps")
    if any("event_identity_contract" in source.quality for source in sources):
        signatures = [[(s.get("event_id"), s.get("event_sequence"))
                       for s in source.quality.get("samples", [])] for source in sources]
        if (not all("event_identity_contract" in source.quality for source in sources)
                or any(signature != signatures[0] for signature in signatures[1:])
                or len({source.quality["event_order"] for source in sources}) != 1):
            raise ValueError("identified relationships require matching logical event IDs and order contracts")
    return sources
