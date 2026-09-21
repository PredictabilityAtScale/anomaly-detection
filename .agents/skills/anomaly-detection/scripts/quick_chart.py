#!/usr/bin/env python3
"""Render a fast, dependency-free SVG from structured Anomalyzer JSON."""

from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path
from typing import Any, Iterable


WIDTH = 1000
HEIGHT = 430
LEFT = 74
RIGHT = 28
TOP = 86
BOTTOM = 72


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _format_number(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1000 or (magnitude and magnitude < 0.01):
        return f"{value:.3g}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _method_with_evidence(result: dict[str, Any]) -> dict[str, Any]:
    for method in result.get("methods") or []:
        if method.get("evidence"):
            return method
    methods = result.get("methods") or []
    return methods[0] if methods else {}


def _segments(values: list[float | None]) -> Iterable[list[tuple[int, float]]]:
    segment: list[tuple[int, float]] = []
    for index, value in enumerate(values):
        if value is None:
            if segment:
                yield segment
                segment = []
            continue
        segment.append((index, value))
    if segment:
        yield segment


def _phase_ranges(
    method: dict[str, Any], config: dict[str, Any], count: int
) -> list[tuple[str, int, int]]:
    diagnostics = method.get("diagnostics") or {}
    segments = diagnostics.get("segments") or [
        {"start_position": 0, "end_position": count - 1}
    ]
    training = max(int(config.get("training_size", 28)), int(config.get("season_length", 1)))
    calibration = int(config.get("calibration_size", 14))
    ranges: list[tuple[str, int, int]] = []
    for segment in segments:
        start = max(0, int(segment.get("start_position", 0)))
        stop = min(count, int(segment.get("end_position", count - 1)) + 1)
        training_stop = min(stop, start + training)
        calibration_stop = min(stop, training_stop + calibration)
        if training_stop > start:
            ranges.append(("Training", start, training_stop))
        if calibration_stop > training_stop:
            ranges.append(("Calibration", training_stop, calibration_stop))
    return ranges


def render(result: dict[str, Any], title: str) -> str:
    resolved = result.get("resolved_config") or {}
    datasets = resolved.get("datasets") or []
    if len(datasets) != 1:
        raise ValueError("quick chart requires exactly one resolved dataset")
    dataset = datasets[0]
    raw_values = dataset.get("values") or []
    values = [_finite(value) for value in raw_values]
    if not values or not any(value is not None for value in values):
        raise ValueError("resolved dataset has no finite values")

    count = len(values)
    timestamps = dataset.get("timestamps") or []
    method = _method_with_evidence(result)
    evidence = method.get("evidence") or []
    by_index = {
        int(item["index"]): item
        for item in evidence
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
    expected = [
        _finite(by_index.get(index, {}).get("expected")) for index in range(count)
    ]
    triggered = [
        index
        for index in range(count)
        if by_index.get(index, {}).get("triggers")
    ]

    plotted = [value for value in values + expected if value is not None]
    low = min(plotted)
    high = max(plotted)
    spread = high - low
    padding = max(spread * 0.08, abs(high) * 0.01, 1.0)
    y_low = low - padding
    y_high = high + padding

    plot_width = WIDTH - LEFT - RIGHT
    plot_height = HEIGHT - TOP - BOTTOM
    step = plot_width / max(1, count - 1)

    def x(index: float) -> float:
        return LEFT + index * step if count > 1 else LEFT + plot_width / 2

    def y(value: float) -> float:
        return TOP + (y_high - value) / (y_high - y_low) * plot_height

    def span(start: int, stop: int) -> tuple[float, float]:
        if count == 1:
            return LEFT, LEFT + plot_width
        start_x = max(LEFT, x(start) - step / 2)
        end_x = min(LEFT + plot_width, x(stop - 1) + step / 2)
        return start_x, end_x

    config = resolved.get("config") or {}
    units = dataset.get("units") or "Value"
    status = result.get("status") or "unknown"
    observations = len(result.get("observations") or [])
    patterns = len(result.get("anomaly_patterns") or [])
    point_threshold = config.get("point_threshold")

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="chart-title chart-desc">',
        f'<title id="chart-title">{escape(title)}</title>',
        f'<desc id="chart-desc">Observed and expected values with training and calibration windows and {len(triggered)} triggered points.</desc>',
        '<rect width="1000" height="430" fill="#ffffff"/>',
        f'<text x="{LEFT}" y="34" font-family="Arial, sans-serif" font-size="24" font-weight="600" fill="#172330">{escape(title)}</text>',
        f'<text x="{LEFT}" y="59" font-family="Arial, sans-serif" font-size="14" fill="#596575">{escape(str(status))} · {observations} point episodes · {patterns} patterns</text>',
    ]

    phase_colors = {"Training": "#eef1f4", "Calibration": "#f3effa"}
    for label, start, stop in _phase_ranges(method, config, count):
        start_x, end_x = span(start, stop)
        svg.append(
            f'<rect x="{start_x:.2f}" y="{TOP}" width="{end_x - start_x:.2f}" height="{plot_height}" fill="{phase_colors[label]}"/>'
        )
        svg.append(
            f'<text x="{(start_x + end_x) / 2:.2f}" y="{TOP + 17}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#596575">{label}</text>'
        )

    diagnostics = method.get("diagnostics") or {}
    for segment in (diagnostics.get("segments") or [])[1:]:
        position = int(segment.get("start_position", 0))
        svg.append(
            f'<line x1="{x(position):.2f}" y1="{TOP}" x2="{x(position):.2f}" y2="{TOP + plot_height}" stroke="#6b7280" stroke-width="1.5" stroke-dasharray="5 4"/>'
        )

    tick_count = 5
    for tick_index in range(tick_count):
        value = y_low + (y_high - y_low) * tick_index / (tick_count - 1)
        yy = y(value)
        svg.append(
            f'<line x1="{LEFT}" y1="{yy:.2f}" x2="{LEFT + plot_width}" y2="{yy:.2f}" stroke="#dce1e7" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{LEFT - 10}" y="{yy + 5:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#596575">{escape(_format_number(value))}</text>'
        )

    svg.append(
        f'<rect x="{LEFT}" y="{TOP}" width="{plot_width}" height="{plot_height}" fill="none" stroke="#9ba6b2" stroke-width="1"/>'
    )

    for segment in _segments(values):
        points = " ".join(f"{x(index):.2f},{y(value):.2f}" for index, value in segment)
        svg.append(
            f'<polyline points="{points}" fill="none" stroke="#2563a6" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    for segment in _segments(expected):
        points = " ".join(f"{x(index):.2f},{y(value):.2f}" for index, value in segment)
        svg.append(
            f'<polyline points="{points}" fill="none" stroke="#b45a06" stroke-width="2" stroke-dasharray="7 5" stroke-linejoin="round"/>'
        )

    for index in triggered:
        observed = values[index]
        if observed is None:
            continue
        trigger_names = ", ".join(str(item) for item in by_index[index].get("triggers") or [])
        label = timestamps[index] if index < len(timestamps) else f"sample {index}"
        svg.append(
            f'<circle cx="{x(index):.2f}" cy="{y(observed):.2f}" r="5.5" fill="#c73538" stroke="#ffffff" stroke-width="1.5"><title>{escape(str(label))}: {escape(trigger_names)}</title></circle>'
        )

    tick_indices = sorted(
        {round((count - 1) * fraction / 3) for fraction in range(4)}
    )
    for index in tick_indices:
        label = timestamps[index] if index < len(timestamps) else str(index)
        label = str(label)[:10]
        xx = x(index)
        anchor = "start" if index == 0 else "end" if index == count - 1 else "middle"
        svg.append(
            f'<line x1="{xx:.2f}" y1="{TOP + plot_height}" x2="{xx:.2f}" y2="{TOP + plot_height + 6}" stroke="#9ba6b2"/>'
        )
        svg.append(
            f'<text x="{xx:.2f}" y="{TOP + plot_height + 24}" text-anchor="{anchor}" font-family="Arial, sans-serif" font-size="12" fill="#596575">{escape(label)}</text>'
        )

    legend_y = HEIGHT - 18
    svg.extend(
        [
            f'<line x1="{LEFT}" y1="{legend_y}" x2="{LEFT + 24}" y2="{legend_y}" stroke="#2563a6" stroke-width="2.5"/>',
            f'<text x="{LEFT + 31}" y="{legend_y + 5}" font-family="Arial, sans-serif" font-size="13" fill="#344050">Observed</text>',
            f'<line x1="{LEFT + 118}" y1="{legend_y}" x2="{LEFT + 142}" y2="{legend_y}" stroke="#b45a06" stroke-width="2" stroke-dasharray="7 5"/>',
            f'<text x="{LEFT + 149}" y="{legend_y + 5}" font-family="Arial, sans-serif" font-size="13" fill="#344050">Expected</text>',
            f'<circle cx="{LEFT + 259}" cy="{legend_y}" r="5" fill="#c73538"/>',
            f'<text x="{LEFT + 271}" y="{legend_y + 5}" font-family="Arial, sans-serif" font-size="13" fill="#344050">Triggered point</text>',
            f'<text x="18" y="{TOP + plot_height / 2:.2f}" transform="rotate(-90 18 {TOP + plot_height / 2:.2f})" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#344050">{escape(str(units))}</text>',
            f'<text x="{LEFT + plot_width / 2:.2f}" y="{HEIGHT - 43}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#344050">Timestamp or sample position</text>',
        ]
    )
    if point_threshold is not None:
        svg.append(
            f'<text x="{LEFT + plot_width}" y="59" text-anchor="end" font-family="Arial, sans-serif" font-size="13" fill="#596575">Point threshold: ±{escape(_format_number(float(point_threshold)))}</text>'
        )
    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a fast static anomaly chart from Anomalyzer JSON."
    )
    parser.add_argument("result", type=Path, help="Structured Anomalyzer result JSON")
    parser.add_argument("--output", type=Path, help="Destination SVG path")
    parser.add_argument("--title", default="Anomalyzer evidence", help="Chart title")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output")
    args = parser.parse_args()

    output = args.output or args.result.with_suffix(".quick.svg")
    if output.exists() and not args.overwrite:
        parser.error(f"output already exists: {output}; pass --overwrite to replace it")

    result = json.loads(args.result.read_text(encoding="utf-8"))
    svg = render(result, args.title)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
