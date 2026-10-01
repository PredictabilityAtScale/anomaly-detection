"""Render the README's anomaly-detection progression as reproducible PNGs.

The figures use checked-in synthetic examples and real ``analyze`` results.
They have no plotting-library dependency: an installed Chromium browser renders
small, self-contained SVG pages to PNG.

Run from the project root:
    .venv/Scripts/python examples/render_readme_progression.py
"""

from __future__ import annotations

import html
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anomalyzer import analyze


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
OUTPUT = ROOT / "docs" / "images"
WIDTH, HEIGHT = 1200, 680

INK = "#172330"
MUTED = "#596575"
GRID = "#dce1e7"
AXIS = "#9ba6b2"
BLUE = "#2563a6"
BLUE_LIGHT = "#8db3dc"
NAVY = "#173f6f"
GOLD = "#b7791f"
RED = "#c73538"
ORANGE = "#b45a06"
SHADE = "#eef1f4"


class Svg:
    def __init__(self) -> None:
        self.items = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
        ]

    def text(self, x, y, value, size=18, color=INK, weight=400, anchor="start"):
        value = html.escape(str(value))
        self.items.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{value}</text>'
        )

    def line(self, x1, y1, x2, y2, color=GRID, width=1, dash=None):
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width}"{dashed}/>'
        )

    def rect(self, x, y, width, height, fill="none", stroke="none", radius=0):
        self.items.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}" '
            f'rx="{radius}" fill="{fill}" stroke="{stroke}"/>'
        )

    def circle(self, x, y, radius, fill, stroke="none", width=1):
        self.items.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"/>'
        )

    def polyline(self, points, color, width=3, dash=None, opacity=1.0):
        chunks, current = [], []
        for point in points:
            if point is None:
                if current:
                    chunks.append(current)
                    current = []
            else:
                current.append(point)
        if current:
            chunks.append(current)
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        for chunk in chunks:
            coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in chunk)
            self.items.append(
                f'<polyline points="{coords}" fill="none" stroke="{color}" '
                f'stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round" '
                f'opacity="{opacity}"{dashed}/>'
            )

    def finish(self):
        return "\n".join(self.items + ["</svg>"])


def read_request(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def run_request(request, trend=None, outlier_handling=None):
    request = json.loads(json.dumps(request))
    if trend:
        request["config"]["trend"] = trend
    if outlier_handling:
        request["config"]["outlier_handling"] = outlier_handling
    result = analyze(request)
    method = result.methods[0]
    expected = {row["index"]: row["expected"] for row in method.evidence}
    flags = {row["index"] for row in method.evidence if row["triggers"]}
    return result, expected, flags


def mutate(request, changes):
    request = json.loads(json.dumps(request))
    values = request["datasets"][0]["values"]
    for index, amount in changes.items():
        values[index] += amount
    return request


def bounds(*series):
    values = [value for sequence in series for value in sequence if value is not None]
    low, high = min(values), max(values)
    pad = max((high - low) * 0.12, 1)
    return low - pad, high + pad


def chart(svg, values, overlays, x, y, width, height, *, y_bounds=None,
          shade_until=41, flags=(), injected=(), echoes=(), ticks=None,
          label=None, boundaries=(), y_tick_format=None):
    count = len(values)
    all_values = [values] + [series for _, series, *_ in overlays]
    low, high = y_bounds or bounds(*all_values)
    sx = lambda index: x + index / max(count - 1, 1) * width
    sy = lambda value: y + height - (value - low) / (high - low) * height

    if shade_until is not None:
        svg.rect(x, y, sx(shade_until) - x, height, SHADE)
    for step in range(5):
        value = low + (high - low) * step / 4
        yy = sy(value)
        svg.line(x, yy, x + width, yy)
        tick = y_tick_format(value) if y_tick_format else f"{value:.0f}"
        svg.text(x - 12, yy + 6, tick, 15, MUTED, anchor="end")
    svg.line(x, y, x, y + height, AXIS)
    svg.line(x, y + height, x + width, y + height, AXIS)
    if label:
        svg.text(x, y - 14, label, 18, INK, 700)
    for index in boundaries:
        xx = sx(index)
        svg.line(xx, y, xx, y + height, NAVY, 2, "7 6")

    for color, series, line_width, dash, opacity in overlays:
        points = [None if value is None else (sx(index), sy(value))
                  for index, value in enumerate(series)]
        svg.polyline(points, color, line_width, dash, opacity)
    svg.polyline([(sx(index), sy(value)) for index, value in enumerate(values)], BLUE, 2.5)

    for index in flags:
        color = RED if index in injected else ORANGE if index in echoes else RED
        svg.circle(sx(index), sy(values[index]), 4.5, color, "#ffffff", 1.5)

    if ticks is None:
        ticks = [(0, "Jan 1"), (31, "Feb 1"), (59, "Mar 1"), (count - 1, "Mar 31")]
    for index, text in ticks:
        xx = sx(index)
        svg.line(xx, y + height, xx, y + height + 5, AXIS)
        svg.text(xx, y + height + 24, text, 15, MUTED, anchor="middle")
    return sx, sy


def header(svg, number, title, subtitle):
    svg.text(60, 55, f"{number}  {title}" if number else title, 30, INK, 700)
    svg.text(60, 91, subtitle, 18, MUTED)
    svg.line(60, 116, WIDTH - 60, 116, GRID)


def legend(svg, items, y=622):
    x = 70
    for kind, color, label in items:
        if kind == "line":
            svg.line(x, y - 5, x + 28, y - 5, color, 3)
        elif kind == "dash":
            svg.line(x, y - 5, x + 28, y - 5, color, 3, "7 5")
        else:
            svg.circle(x + 13, y - 5, 5, color)
        svg.text(x + 38, y, label, 15, MUTED)
        x += 38 + len(label) * 8.2 + 28


def expected_series(expected, count):
    return [expected.get(index) for index in range(count)]


def figure_one():
    values = [80 + 0.65 * index + [0, 0.25, -0.15, 0.10, -0.20][index % 5]
              for index in range(90)]
    changes = {65: 22, 78: -18}
    for index, amount in changes.items():
        values[index] += amount
    result = analyze(values, {"season_length": 1, "trend": "linear"})
    trend = result.methods[0].diagnostics["trend"]
    slope = trend["coefficient"]
    intercept = sum(values[index] - slope * index for index in range(28)) / 28
    fitted = [intercept + slope * index for index in range(len(values))]
    flat = [sum(values[:28]) / 28] * len(values)

    svg = Svg()
    header(svg, "01", "Start with the trend", "Without a repeating season, growth itself should be expected—not treated as departure.")
    _, sy = chart(svg, values, [(GOLD, flat, 2, "8 6", 1), (NAVY, fitted, 3, "8 5", 1)],
                  95, 165, 1040, 385, injected=set(changes), flags=set(changes),
                  shade_until=41)
    svg.text(99, 150, "Calls", 15, MUTED)
    svg.text(1135, sy(flat[-1]) - 10, "flat average", 15, GOLD, 700, "end")
    svg.text(1135, sy(fitted[-1]) - 10, f"linear trend  +{slope:.2f}/day", 15, NAVY, 700, "end")
    legend(svg, [("line", BLUE, "observed"), ("dash", GOLD, "flat reference"),
                 ("dash", NAVY, "fitted trend"), ("dot", RED, "introduced spikes")])
    svg.text(1130, 658, "Gray: training + calibration · synthetic example", 14, MUTED, anchor="end")
    return svg.finish()


def figure_two():
    changes = {65: 40, 78: -35}
    request = mutate(read_request("growth_up"), changes)
    result, expected, flags = run_request(request, "linear", "include")
    values = request["datasets"][0]["values"]
    trend = result.methods[0].diagnostics["trend"]
    injected, echoes = set(changes), {72, 85}

    svg = Svg()
    header(svg, "02", "Add seasonality to linear growth", "Compare each day with the same weekday, then add the fitted change across the week.")
    chart(svg, values, [(NAVY, expected_series(expected, len(values)), 3, "7 5", 0.95)],
          95, 165, 1040, 385, flags=flags, injected=injected, echoes=echoes)
    svg.text(99, 150, "Calls", 15, MUTED)
    svg.rect(850, 133, 285, 34, "#f4f7fa", "none", 17)
    svg.text(992, 156, f"weekly lag 7  ·  linear {trend['coefficient']:+.2f}/day", 15, NAVY, 700, "middle")
    legend(svg, [("line", BLUE, "observed"), ("dash", NAVY, "seasonal + linear expectation"),
                 ("dot", RED, "introduced change"), ("dot", ORANGE, "one-week echo")])
    svg.text(1130, 658, "4 flags: 2 introduced changes + 2 baseline echoes", 14, MUTED, anchor="end")
    return svg.finish()


def figure_three():
    changes = {65: 40, 78: -35}
    request = mutate(read_request("compound"), changes)
    linear_result, linear_expected, linear_flags = run_request(request, "linear", "include")
    compound_result, compound_expected, compound_flags = run_request(request, "exponential", "include")
    values = request["datasets"][0]["values"]
    shared = bounds(values, expected_series(linear_expected, len(values)),
                    expected_series(compound_expected, len(values)))
    ticks = [(0, "Jan 1"), (31, "Feb 1"), (59, "Mar 1"), (89, "Mar 31")]

    svg = Svg()
    header(svg, "03", "Let growth compound", "A fixed daily amount eventually falls behind growth that accumulates as a rate.")
    chart(svg, values, [(GOLD, expected_series(linear_expected, len(values)), 2.5, "7 5", 1)],
          105, 170, 1015, 155, y_bounds=shared, flags=linear_flags, injected=linear_flags,
          ticks=[], label=f"Forced linear trend  ·  {len(linear_flags)} samples flagged")
    chart(svg, values, [(NAVY, expected_series(compound_expected, len(values)), 2.5, "7 5", 1)],
          105, 410, 1015, 155, y_bounds=shared, flags=compound_flags,
          injected=set(changes), echoes={72, 85}, ticks=ticks,
          label=f"Compound trend  ·  {len(compound_flags)} samples flagged")
    rate = compound_result.methods[0].diagnostics["trend"]["rate"]
    svg.rect(840, 130, 280, 34, "#f4f7fa", "none", 17)
    svg.text(980, 153, f"fitted rate  {math.expm1(rate) * 100:.2f}% per day", 15, NAVY, 700, "middle")
    legend(svg, [("line", BLUE, "observed"), ("dash", GOLD, "linear expectation"),
                 ("dash", NAVY, "compound expectation"), ("dot", RED, "flag")], y=632)
    svg.text(1130, 660, "Same weekly pattern and same two introduced changes", 14, MUTED, anchor="end")
    return svg.finish()


def figure_adaptive():
    weekly = [0, 12, -5, 9, 3, -8, -11]
    variation = [0, .8, -.5, 1.2, -.7, .4, -.3, 1, -.9]
    values = [200 + .6 * index + .015 * index * index
              + weekly[index % 7] + variation[index % 9]
              for index in range(110)]
    values[80] += 45
    frozen_request = {
        "datasets": [{"values": values}],
        "config": {"season_length": 7, "training_size": 35,
                   "calibration_size": 14},
    }
    adaptive_request = json.loads(json.dumps(frozen_request))
    adaptive_request["config"]["recipe"] = "adaptive-seasonal-v1"
    frozen = analyze(frozen_request)
    adaptive = analyze(adaptive_request)
    frozen_expected = {row["index"]: row["expected"]
                       for row in frozen.methods[0].evidence}
    adaptive_expected = {row["index"]: row["expected"]
                         for row in adaptive.methods[0].evidence}
    frozen_flags = {row["index"] for row in frozen.methods[0].evidence
                    if row["triggers"]}
    adaptive_flags = {row["index"] for row in adaptive.methods[0].evidence
                      if row["triggers"]}
    shared = bounds(values, expected_series(frozen_expected, len(values)),
                    expected_series(adaptive_expected, len(values)))
    ticks = [(0, "0"), (49, "49 · calibrated"),
             (80, "80 · isolated change"), (109, "109")]

    svg = Svg()
    header(svg, "04", "Update the expectation one step at a time",
           "A bounded rolling trend follows gradual acceleration while frozen calibration preserves comparable evidence.")
    chart(svg, values,
          [(GOLD, expected_series(frozen_expected, len(values)), 2.5, "7 5", 1)],
          105, 170, 1015, 155, y_bounds=shared, flags=frozen_flags,
          injected={80}, ticks=[],
          label=(f"Frozen training trend  ·  {len(frozen_flags)} samples flagged  ·  "
                 f"held-out MAE {frozen.methods[0].diagnostics['held_out_mae']:.1f}"))
    chart(svg, values,
          [(NAVY, expected_series(adaptive_expected, len(values)), 2.5, "7 5", 1)],
          105, 410, 1015, 155, y_bounds=shared, flags=adaptive_flags,
          injected={80}, ticks=ticks,
          label=(f"One-step rolling expectation  ·  {len(adaptive_flags)} samples flagged  ·  "
                 f"held-out MAE {adaptive.methods[0].diagnostics['held_out_mae']:.1f}"))
    legend(svg, [("line", BLUE, "actual"),
                 ("dash", GOLD, "frozen expectation"),
                 ("dash", NAVY, "rolling expectation"),
                 ("dot", RED, "flag")], y=632)
    svg.text(1130, 660,
             "Every rolling expectation uses only observations available before that point",
             14, MUTED, anchor="end")
    return svg.finish()


def figure_four():
    request = read_request("steps")
    reset_request = read_request("steps_reset")
    _, plain_expected, plain_flags = run_request(request, outlier_handling="include")
    _, reset_expected, reset_flags = run_request(reset_request, outlier_handling="include")
    values = request["datasets"][0]["values"]
    shared = bounds(values, expected_series(plain_expected, len(values)),
                    expected_series(reset_expected, len(values)))
    ticks = [(0, "Jan 1"), (50, "Feb 20"), (100, "Apr 11"), (149, "May 30")]

    svg = Svg()
    header(svg, "05", "Treat discontinuities as new regimes", "A reviewed change point restarts seasonal history, trend fitting, and calibration.")
    chart(svg, values, [(GOLD, expected_series(plain_expected, len(values)), 2.5, "7 5", 1)],
          105, 170, 1015, 155, y_bounds=shared, flags=plain_flags, injected=plain_flags,
          ticks=[], label=f"No change points  ·  {len(plain_flags)} samples flagged")
    chart(svg, values, [(NAVY, expected_series(reset_expected, len(values)), 2.5, "7 5", 1)],
          105, 410, 1015, 155, y_bounds=shared, flags=reset_flags,
          ticks=ticks, label=f"Reviewed change points at 50 and 100  ·  {len(reset_flags)} samples flagged",
          boundaries=(50, 100))
    legend(svg, [("line", BLUE, "observed"), ("dash", GOLD, "single-regime expectation"),
                 ("dash", NAVY, "reset expectation"), ("dot", RED, "flag")], y=632)
    svg.text(1130, 660, "Resets are explicit; anomaly runs never retrain automatically", 14, MUTED, anchor="end")
    return svg.finish()


def figure_five():
    request = read_request("ordinary")
    values = request["datasets"][0]["values"]
    result = analyze(values)
    inference = result.methods[0].diagnostics["season_inference"]
    ranked = inference["ranked_candidates"][:5]

    svg = Svg()
    header(svg, "06", "Discover a stable season", "When positional input omits the lag, detrend a prefix, rank candidates, then confirm the winner early.")
    # The line chart intentionally shows four complete weeks from the inference window.
    sample = values[:28]
    low, high = bounds(sample)
    x, y, width, height = 80, 190, 700, 300
    sx = lambda index: x + index / (len(sample) - 1) * width
    sy = lambda value: y + height - (value - low) / (high - low) * height
    for week in range(4):
        if week % 2 == 0:
            svg.rect(sx(week * 7), y, sx(min(week * 7 + 6.99, 27)) - sx(week * 7), height, SHADE)
        svg.text(sx(week * 7 + 3), y + height + 30, f"week {week + 1}", 15, MUTED, anchor="middle")
    for step in range(4):
        value = low + (high - low) * step / 3
        yy = sy(value)
        svg.line(x, yy, x + width, yy)
        svg.text(x - 10, yy + 5, f"{value:.0f}", 14, MUTED, anchor="end")
    svg.line(x, y, x, y + height, AXIS)
    svg.line(x, y + height, x + width, y + height, AXIS)
    svg.polyline([(sx(index), sy(value)) for index, value in enumerate(sample)], BLUE, 3)
    svg.text(x, y - 16, "First 28 values: repeating weekly shape", 18, INK, 700)

    svg.text(845, 174, "Top lag candidates", 18, INK, 700)
    bar_x, bar_width = 910, 205
    for row, candidate in enumerate(ranked):
        yy = 210 + row * 54
        correlation = max(0.0, candidate["correlation"])
        color = NAVY if candidate["lag"] == 7 else BLUE_LIGHT if candidate["lag"] in (14, 21) else AXIS
        svg.text(895, yy + 18, f"lag {candidate['lag']}", 15, MUTED, anchor="end")
        svg.rect(bar_x, yy, bar_width, 24, SHADE, "none", 4)
        svg.rect(bar_x, yy, bar_width * correlation, 24, color, "none", 4)
        svg.text(1125, yy + 18, f"{candidate['correlation']:.3f}", 14, MUTED)
    svg.rect(835, 505, 310, 88, "#f4f7fa", "none", 8)
    svg.text(855, 535, f"Detected lag: {inference['selected_lag']} samples", 20, NAVY, 700)
    start, stop = inference["selection_window"]
    svg.text(855, 566, f"Confirmed on positions {start}–{stop}", 16, MUTED)
    svg.text(60, 632, "Lag 7 wins; 14 and 21 are harmonics of the same weekly cycle.", 16, INK, 700)
    svg.text(1135, 658, "Inference suggests a lag; domain knowledge still takes precedence", 14, MUTED, anchor="end")
    return svg.finish()


def figure_six():
    request = read_request("location_shift_up")
    result = analyze(request)
    evidence = [row for row in result.methods[0].evidence
                if row["signal_maturity"] == "calibrated"]
    scores = {row["index"]: row["standardized_residual"] for row in evidence}
    detections = {pattern["rule"]: pattern["detection_index"]
                  for pattern in result.anomaly_patterns
                  if pattern["kind"] == "location_shift"}

    svg = Svg()
    header(svg, "07", "Detect a sustained location shift",
           "Moderate departures can form a shift pattern even when no single point crosses three sigma.")
    x, y, width, height = 95, 165, 1040, 385
    first, last = min(scores), max(scores)
    sx = lambda index: x + (index - first) / (last - first) * width
    sy = lambda score: y + height - (score + 3.2) / 6.4 * height

    svg.rect(sx(60), y, sx(last) - sx(60), height, "#fff7e8")
    for zone in (-3, -2, -1, 0, 1, 2, 3):
        color = NAVY if zone == 0 else GRID
        line_width = 2 if zone == 0 else 1
        svg.line(x, sy(zone), x + width, sy(zone), color, line_width,
                 None if zone == 0 else "5 5")
        svg.text(x - 12, sy(zone) + 5, f"{zone:+d}σ" if zone else "0", 14,
                 MUTED, anchor="end")
    svg.line(x, y, x, y + height, AXIS)
    svg.line(x, y + height, x + width, y + height, AXIS)
    points = [(sx(index), sy(score)) for index, score in scores.items()]
    svg.polyline(points, BLUE, 2.5)
    for index, score in scores.items():
        svg.circle(sx(index), sy(score), 3.5, BLUE, "#ffffff", 1)

    labels = (("nelson_rule_5", "Rule 5 · sample 61", GOLD, 188),
              ("cusum", "CUSUM · sample 62", NAVY, 213),
              ("nelson_rule_6", "Rule 6 · sample 63", ORANGE, 238),
              ("nelson_rule_2", "Rule 2 · sample 68", RED, 268))
    for rule, label, color, label_y in labels:
        index = detections[rule]
        svg.line(sx(index), y, sx(index), y + height, color, 2, "5 4")
        svg.text(sx(index) + 7, label_y, label, 14, color, 700)

    for index, label in ((first, str(first)), (60, "60 · shift begins"),
                         (last, str(last))):
        svg.line(sx(index), y + height, sx(index), y + height + 5, AXIS)
        svg.text(sx(index), y + height + 25, label, 14, MUTED, anchor="middle")
    svg.text(99, 150, "Standardized residual", 15, MUTED)
    legend(svg, [("line", BLUE, "residual score"),
                 ("dash", NAVY, "frozen residual centerline"),
                 ("dot", RED, "first rule detection")])
    svg.text(1130, 658, "All shifted scores are +2.28σ; point anomalies: 0", 14,
             MUTED, anchor="end")
    return svg.finish()


def figure_seven():
    request = read_request("spike")
    included, included_expected, included_flags = run_request(
        request, outlier_handling="include")
    robust, robust_expected, robust_flags = run_request(
        request, outlier_handling="robust")
    values = request["datasets"][0]["values"]
    shared = bounds(values, expected_series(included_expected, len(values)),
                    expected_series(robust_expected, len(values)))
    ticks = [(0, "Jan 1"), (31, "Feb 1"), (65, "Mar 7"),
             (72, "Mar 14"), (89, "Mar 31")]

    svg = Svg()
    header(svg, "08", "Protect the model from an incident",
           "Score the actual spike, then keep it out of future seasonal references so it cannot echo.")
    chart(svg, values,
          [(GOLD, expected_series(included_expected, len(values)), 2.5, "7 5", 1)],
          105, 170, 1015, 155, y_bounds=shared, flags=included_flags,
          injected={65}, echoes={72}, ticks=[],
          label="Include every observation  ·  spike + one-week echo")
    chart(svg, values,
          [(NAVY, expected_series(robust_expected, len(values)), 2.5, "7 5", 1)],
          105, 410, 1015, 155, y_bounds=shared, flags=robust_flags,
          injected={65}, ticks=ticks,
          label="Robust default  ·  actual spike retained, echo prevented")
    sx = lambda index: 105 + index / (len(values) - 1) * 1015
    low, high = shared
    sy = lambda value: 410 + 155 - (value - low) / (high - low) * 155
    svg.circle(sx(65), sy(values[65]), 7, "#ffffff", AXIS, 2)
    svg.circle(sx(65), sy(values[65]), 3.5, RED)
    legend(svg, [("line", BLUE, "actual"), ("dash", GOLD, "include expectation"),
                 ("dash", NAVY, "robust expectation"), ("dot", RED, "flag")], y=632)
    svg.text(1130, 660, "The point is excluded from model influence, never from evidence", 14,
             MUTED, anchor="end")
    return svg.finish()


def figure_eight():
    weekly = [0, 10, -5, 8, 2, -12, -8]
    variation = [.2, -.4, .6, -.3, .1]
    values = [100 + weekly[index % 7] + variation[index % 5]
              + (20 if index >= 60 else 0) for index in range(120)]
    ordinary = analyze(values, {"season_length": 7})
    reviewed = analyze(values, {"season_length": 7, "reset_points": [60]})
    ordinary_expected = {row["index"]: row["expected"]
                         for row in ordinary.methods[0].evidence}
    reviewed_expected = {row["index"]: row["expected"]
                         for row in reviewed.methods[0].evidence}
    ordinary_flags = {row["index"] for row in ordinary.methods[0].evidence
                      if row["triggers"]}
    reviewed_flags = {row["index"] for row in reviewed.methods[0].evidence
                      if row["triggers"]}
    shared = bounds(values, expected_series(ordinary_expected, len(values)),
                    expected_series(reviewed_expected, len(values)))
    ticks = [(0, "0"), (60, "60 · shift"),
             (102, "102 · recalibrated"), (119, "119")]

    svg = Svg()
    header(svg, "09", "Do not normalize a new regime automatically",
           "A persistent shift stays abnormal until review declares a new baseline.")
    chart(svg, values,
          [(GOLD, expected_series(ordinary_expected, len(values)), 2.5, "7 5", 1)],
          105, 170, 1015, 155, y_bounds=shared, flags=ordinary_flags,
          injected=ordinary_flags, ticks=[],
          label=f"No reset  ·  {len(ordinary_flags)} shifted samples flag")
    chart(svg, values,
          [(NAVY, expected_series(reviewed_expected, len(values)), 2.5, "7 5", 1)],
          105, 410, 1015, 155, y_bounds=shared, flags=reviewed_flags,
          ticks=ticks, boundaries=(60,),
          label="Reviewed reset at 60  ·  rebuild history, fit, and calibration")
    legend(svg, [("line", BLUE, "actual"), ("dash", GOLD, "old-regime expectation"),
                 ("dash", NAVY, "reset expectation"), ("dot", RED, "flag")], y=632)
    svg.text(1130, 660, "Detection suggests review; only a reviewed reset establishes the new normal", 14,
             MUTED, anchor="end")
    return svg.finish()


def figure_rule_reference():
    cards = [
        ("Point · default > 3σ", "Nelson Rule 1 equivalent", [-.2, .4, -.5, 3.4, .1], {3}),
        ("Rule 2 · 9 above", "possible upward location shift",
         [.2, .4, .1, .5, .3, .6, .2, .7, .4], set(range(9))),
        ("Rule 2 · 9 below", "possible downward location shift",
         [-.2, -.4, -.1, -.5, -.3, -.6, -.2, -.7, -.4], set(range(9))),
        ("Rule 5 · 2 of 3 beyond +2σ", "mirrored below for a downward shift",
         [2.2, .3, 2.4], {0, 2}),
        ("Rule 6 · 4 of 5 beyond −1σ", "mirrored above for an upward shift",
         [-1.4, -1.2, .2, -1.6, -1.3], {0, 1, 3, 4}),
        ("Adjacent point-anomaly run", "Anomalyzer pattern · not a Nelson rule",
         [3.2, 3.5], {0, 1}),
    ]

    svg = Svg()
    header(svg, "", "Implemented rule shapes",
           "Small standardized-residual series; red points satisfy the named rule and zero is the frozen centerline.")
    for card_index, (title, subtitle, scores, highlighted) in enumerate(cards):
        column, row = card_index % 2, card_index // 2
        x, y = 60 + column * 560, 135 + row * 155
        card_width, card_height = 520, 140
        svg.rect(x, y, card_width, card_height, "#fbfcfd", GRID, 8)
        svg.text(x + 16, y + 27, title, 17, INK, 700)
        svg.text(x + 16, y + 49, subtitle, 13, MUTED)
        plot_x, plot_y = x + 16, y + 61
        plot_width, plot_height = card_width - 32, 63
        sx = lambda index: plot_x + index / max(len(scores) - 1, 1) * plot_width
        sy = lambda score: plot_y + plot_height - (score + 3.7) / 7.4 * plot_height
        for zone in (-3, -2, -1, 0, 1, 2, 3):
            svg.line(plot_x, sy(zone), plot_x + plot_width, sy(zone),
                     NAVY if zone == 0 else GRID, 1.5 if zone == 0 else 1,
                     None if zone == 0 else "4 4")
        svg.polyline([(sx(index), sy(score)) for index, score in enumerate(scores)],
                     BLUE, 2)
        for index, score in enumerate(scores):
            svg.circle(sx(index), sy(score), 4.5,
                       RED if index in highlighted else BLUE, "#ffffff", 1)
    legend(svg, [("line", BLUE, "residual sequence"),
                 ("dash", NAVY, "zero centerline"),
                 ("dot", RED, "rule-qualifying point")], y=632)
    svg.text(1135, 658, "Above and below tests are symmetric unless shown separately", 14,
             MUTED, anchor="end")
    return svg.finish()


def figure_extended_rule_reference():
    cards = [
        ("Rule 3 · 6 increasing", "possible residual trend / changing slope",
         [-.5, -.3, -.1, .1, .3, .5], set(range(6))),
        ("Rule 4 · 14 alternating", "possible systematic oscillation",
         [-.4, .4] * 7, set(range(14))),
        ("Rule 8 · 8 outside ±1σ", "both sides · possible residual mixture",
         [1.2, -1.2] * 4, set(range(8))),
        ("CUSUM · repeated +0.8σ", "k=0.5, h=5 · possible upward location shift",
         [.8] * 17, set(range(17))),
        ("Moving range · −2σ to +2σ", "adjacent range 4 > default 3.686",
         [-2, 2], {0, 1}),
    ]

    svg = Svg()
    header(svg, "", "Additional residual detectors",
           "These patterns add trend, oscillation, mixture, accumulated-location, and short-term-variation evidence.")
    for card_index, (title, subtitle, scores, highlighted) in enumerate(cards):
        column, row = card_index % 2, card_index // 2
        x, y = 60 + column * 560, 135 + row * 155
        card_width, card_height = 520, 140
        svg.rect(x, y, card_width, card_height, "#fbfcfd", GRID, 8)
        svg.text(x + 16, y + 27, title, 17, INK, 700)
        svg.text(x + 16, y + 49, subtitle, 13, MUTED)
        plot_x, plot_y = x + 16, y + 61
        plot_width, plot_height = card_width - 32, 63
        sx = lambda index: plot_x + index / max(len(scores) - 1, 1) * plot_width
        sy = lambda score: plot_y + plot_height - (score + 3.7) / 7.4 * plot_height
        for zone in (-3, -2, -1, 0, 1, 2, 3):
            svg.line(plot_x, sy(zone), plot_x + plot_width, sy(zone),
                     NAVY if zone == 0 else GRID, 1.5 if zone == 0 else 1,
                     None if zone == 0 else "4 4")
        svg.polyline([(sx(index), sy(score)) for index, score in enumerate(scores)],
                     BLUE, 2)
        for index, score in enumerate(scores):
            svg.circle(sx(index), sy(score), 4.5,
                       RED if index in highlighted else BLUE, "#ffffff", 1)
    svg.rect(620, 445, 520, 140, "#f4f7fa", GRID, 8)
    svg.text(636, 478, "Nelson Rule 7 is intentionally deferred", 18, INK, 700)
    svg.text(636, 506, "15 points within ±1σ primarily diagnose overly wide limits", 14, MUTED)
    svg.text(636, 530, "or stratification; the default 14-point calibration window is", 14, MUTED)
    svg.text(636, 554, "too short to make that signal a dependable default.", 14, MUTED)
    legend(svg, [("line", BLUE, "residual sequence"),
                 ("dash", NAVY, "zero centerline"),
                 ("dot", RED, "rule-contributing point")], y=632)
    return svg.finish()


def figure_readiness():
    rng = random.Random(2)
    values = [100 + rng.gauss(0, 10) for _ in range(90)]
    result = analyze(values, {"season_length": 7})
    method = result.methods[0]
    readiness = method.diagnostics["segments"][0]["detection_readiness"]
    calibration = readiness["calibration"]
    expected = {row["index"]: row["expected"] for row in method.evidence}
    flags = {row["index"] for row in method.evidence if row["triggers"]}
    assert readiness["status"] == "caution"
    assert not result.observations and not result.anomaly_patterns and not flags

    svg = Svg()
    header(svg, "10", "Check whether the reference deserves trust",
           "Zero findings can coexist with a weak reference. Assess its training and calibration separately.")
    chart(svg, values,
          [(NAVY, expected_series(expected, len(values)), 2, "7 5", 0.9)],
          90, 180, 680, 245, shade_until=27,
          ticks=[(0, "0"), (27, "27"), (41, "41"), (65, "65"), (89, "89")],
          label="Random series with a declared lag of 7  ·  value")
    svg.text(430, 467, "Sample index (zero-based)", 15, MUTED, anchor="middle")
    # Training ends at 27; calibration ends at 41. Later values do not assess readiness.
    for start, end, label, color in (
            (0, 27, "training", AXIS), (28, 41, "calibration", GOLD),
            (42, 89, "evaluation", BLUE)):
        x1, x2 = 90 + start / 89 * 680, 90 + end / 89 * 680
        svg.line(x1, 139, x2, 139, color, 4)
        svg.text((x1 + x2) / 2, 132, label, 13, MUTED, anchor="middle")

    svg.rect(815, 145, 325, 322, "#fff7e8", "none", 8)
    svg.text(838, 180, "Reference readiness: caution", 20, ORANGE, 700)
    svg.text(838, 220, f"Point-anomaly episodes: {len(result.observations)}", 18, INK, 700)
    svg.text(838, 250, f"Pattern findings: {len(result.anomaly_patterns)}", 18, INK, 700)
    svg.text(838, 292, "Declared season: weak / unstable", 16, MUTED)
    svg.text(838, 322, "Selected trend: none", 16, MUTED)
    svg.text(838, 366, "Only earlier training and", 18, INK)
    svg.text(838, 392, "calibration assess readiness.", 18, INK)
    svg.text(838, 434, "No findings does not prove normality.", 16, ORANGE, 700)

    svg.text(90, 500, f"Calibration mean absolute error  ·  same {calibration['samples']} samples  ·  lower is better", 18, INK, 700)
    maximum = max(calibration["model_mae"], calibration["training_level_mae"]) * 1.2
    for yy, label, value, color in (
            (526, "Seasonal reference", calibration["model_mae"], GOLD),
            (566, "Constant training median", calibration["training_level_mae"], NAVY)):
        svg.text(300, yy + 19, label, 16, MUTED, anchor="end")
        svg.rect(320, yy, value / maximum * 415, 25, color)
        svg.text(330 + value / maximum * 415, yy + 19, f"{value:.2f}", 16, INK, 700)
    legend(svg, [("line", BLUE, "observed"), ("dash", NAVY, "causal seasonal expectation")], y=632)
    svg.text(1135, 658, "Fixed synthetic draw · reference quality is not detection accuracy", 14, MUTED, anchor="end")
    return svg.finish()


def figure_multi_resolution():
    rng = random.Random(11)
    day_start, count = 60 * 24, 60 * 24 + 12
    weekly = [0, 5, -3, 4, 1, -6, -4]
    values = [100 + 12 * math.sin(2 * math.pi * (index % 24) / 24)
              + weekly[(index // 24) % 7] + rng.gauss(0, 1.5)
              for index in range(count)]
    values[day_start + 9] += 45
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    request = {
        "datasets": [{"id": "calls", "values": values, "frequency": "1h", "units": "calls",
                      "timestamps": [(origin + timedelta(hours=index)).isoformat()
                                     for index in range(count)]}],
        "config": {"recipe": "multi-resolution-v1", "aggregate_function": "sum"},
    }
    result = analyze(request)
    daily, hourly = result.methods
    partial = result.data_quality["incomplete_period"]
    today = [row for row in hourly.evidence if row["index"] >= day_start]
    triggered = [row for row in today if row["triggers"]]
    daily_rows = daily.evidence[-6:]
    assert result.status == "completed"
    assert [row["index"] - day_start for row in triggered] == [9]
    assert partial["completed_subperiods"] == 12
    assert partial["included_in_completed_period_view"] is False
    assert daily_rows[-1]["index"] == 59

    svg = Svg()
    header(svg, "11", "Monitor before the day is finished",
           "At 12:00 UTC, score the 12 finalized hours; keep the unfinished daily total outside the daily detector.")
    x, y, width, height = 100, 180, 670, 185
    sx = lambda hour: x + hour / 24 * width
    sy = lambda value: y + height - (value - 70) / 100 * height
    svg.rect(sx(12), y, sx(24) - sx(12), height, SHADE)
    svg.text(x, 153, "March 2  ·  calls per finalized hour", 18, INK, 700)
    for value in (70, 95, 120, 145, 170):
        svg.line(x, sy(value), x + width, sy(value))
        svg.text(x - 12, sy(value) + 5, value, 15, MUTED, anchor="end")
    svg.line(x, y, x, y + height, AXIS)
    svg.line(x, y + height, x + width, y + height, AXIS)
    svg.polyline([(sx(row["index"] - day_start), sy(row["expected"])) for row in today],
                 NAVY, 2.5, "7 5")
    svg.polyline([(sx(row["index"] - day_start), sy(row["observed"])) for row in today], BLUE, 2.5)
    for row in today:
        svg.circle(sx(row["index"] - day_start), sy(row["observed"]),
                   5 if row["triggers"] else 3, RED if row["triggers"] else BLUE)
    svg.line(sx(12), y, sx(12), y + height, AXIS, 2, "5 5")
    svg.text(sx(18), 258, "Not yet finalized", 18, MUTED, anchor="middle")
    for hour in (0, 6, 12, 18, 24):
        svg.text(sx(hour), y + height + 24, f"{hour:02}:00", 15, MUTED, anchor="middle")
    svg.rect(820, 145, 320, 247, "#f4f7fa", "none", 8)
    svg.text(842, 180, "Hourly view: evidence now", 20, NAVY, 700)
    svg.text(842, 221, "09:00 hour: point trigger", 18, RED, 700)
    svg.text(842, 250, f"{len(today)} finalized hourly evidence records", 16, MUTED)
    svg.text(842, 291, f"{partial['completed_subperiods']} of {partial['expected_subperiods']} hours complete", 18, INK, 700)
    svg.text(842, 323, f"Partial sum: {partial['observed_aggregate']:,.0f} calls", 18, INK)
    svg.text(842, 366, "Partial total is visible, unscored.", 16, MUTED)

    svg.text(x, 426, "Calls per fixed 24-hour period  ·  last 6 complete days + today's partial sum", 18, INK, 700)
    base, bar_height = 570, 120
    daily_max = 3000
    for value in (0, 1500, 3000):
        yy = base - value / daily_max * bar_height
        svg.line(x, yy, x + width, yy)
        svg.text(x - 12, yy + 5, f"{value:,}", 15, MUTED, anchor="end")
    svg.line(x, base - bar_height, x, base, AXIS)
    svg.line(x, base, x + width, base, AXIS)
    for offset, row in enumerate(daily_rows):
        xx = x + 25 + offset * 91
        bh = row["observed"] / daily_max * bar_height
        svg.rect(xx, base - bh, 48, bh, BLUE)
        label = datetime.fromisoformat(row["timestamp"]).strftime("%b %d")
        svg.text(xx + 24, base + 22, label, 14, MUTED, anchor="middle")
    xx = x + 25 + 6 * 91
    bh = partial["observed_aggregate"] / daily_max * bar_height
    svg.rect(xx, base - bh, 48, bh, "#fff7e8", GOLD)
    svg.line(xx - 20, base - bar_height, xx - 20, base, GOLD, 2, "4 4")
    svg.text(xx + 24, base - bh - 10, "partial", 14, GOLD, 700, "middle")
    svg.text(xx + 24, base + 22, "Mar 02", 14, GOLD, anchor="middle")
    svg.rect(820, 424, 320, 176, "#f4f7fa", "none", 8)
    svg.text(842, 458, "Daily view: completed days", 20, NAVY, 700)
    complete_count = result.data_quality["views"]["completed_period"]["observation_count"]
    svg.text(842, 491, f"{complete_count} complete days in analysis", 18, INK)
    svg.text(842, 528, "Today stays out until complete.", 16, GOLD, 700)
    svg.text(842, 565, "No false drop from a partial total.", 16, MUTED)
    legend(svg, [("line", BLUE, "observed"), ("dash", NAVY, "hourly expectation"),
                 ("dot", RED, "hourly trigger")], y=632)
    svg.text(1135, 658, "Synthetic data · fixed UTC periods · both views share observations, so evidence is correlated", 14, MUTED, anchor="end")
    return svg.finish()


def figure_relationship():
    request = read_request("agentic/conversion")
    result = analyze(request)
    sources = {item["id"]: item for item in request["datasets"]}
    source_results = {item.dataset_id: item for item in result.dataset_results}
    relationship = result.relationship_results[0]
    ratios = [point.value for point in relationship.lineage]
    last = relationship.lineage[-1]
    flags = {row["index"] for row in relationship.methods[0].evidence if row["triggers"]}
    assert flags == {14}
    assert not any(row["triggers"] for item in result.dataset_results
                   for method in item.methods for row in method.evidence)

    svg = Svg()
    header(svg, "12", "Look between the metrics",
           "Orders and qualified visits have no point trigger; the declared conversion relationship does.")
    for dataset_id, yy, y_bounds, label in (
            ("qualified_visits", 170, (0, 160), "Qualified visits  ·  visits/day"),
            ("orders", 340, (0, 16), "Orders  ·  orders/day")):
        values = sources[dataset_id]["values"]
        expected = {row["index"]: row["expected"]
                    for row in source_results[dataset_id].methods[0].evidence}
        chart(svg, values,
              [(NAVY, expected_series(expected, len(values)), 2, "7 5", 0.9)],
              95, yy, 740, 100, y_bounds=y_bounds, shade_until=6, ticks=[], label=label)
        svg.circle(835, yy + 100 - values[-1] / y_bounds[1] * 100, 4, BLUE)
    expected = {row["index"]: row["expected"] for row in relationship.methods[0].evidence}
    chart(svg, ratios,
          [(NAVY, expected_series(expected, len(ratios)), 2, "7 5", 1)],
          95, 510, 740, 100, y_bounds=(0.04, 0.12), shade_until=6, flags=flags,
          ticks=[(0, "Jan 1"), (7, "Jan 8"), (14, "Jan 15 · sample 14")],
          label="Conversion  ·  orders / qualified visits",
          y_tick_format=lambda value: f"{value:.0%}")

    visits, orders = sources["qualified_visits"]["values"][-1], sources["orders"]["values"][-1]
    for yy, label, value, detail in (
            (148, "Qualified visits", str(visits), "No point trigger"),
            (318, "Orders", str(orders), "No point trigger"),
            (488, "Declared conversion", f"{last.value:.2%}", "Point trigger at sample 14")):
        svg.rect(880, yy, 260, 133, "#fff7e8" if yy == 488 else "#f4f7fa", "none", 8)
        svg.text(900, yy + 30, label, 18, INK, 700)
        svg.text(900, yy + 68, value, 28, RED if yy == 488 else NAVY, 700)
        svg.text(900, yy + 100, detail, 16, RED if yy == 488 else MUTED)
    svg.text(898, 461, f"{orders} orders / {visits} visits = {last.value:.2%}", 16, INK, 700)
    legend(svg, [("line", BLUE, "observed"), ("dash", NAVY, "causal expectation")], y=300)
    svg.text(560, 300, "Separate count scales; dates align", 14, MUTED)
    reference = expected[last.index]
    change = (last.value - reference) * 100
    svg.text(95, 469, f"Expected conversion: {reference:.0%}  ·  latest departure: {change:+.2f} percentage points", 16, RED, 700)
    svg.text(60, 658, "Synthetic short-calibration example · gray: training + calibration · reference readiness: not_assessed (3 residuals)", 14, MUTED)
    return svg.finish()


def find_browser():
    override = os.environ.get("ANOMALYZER_BROWSER")
    candidates = [
        override,
        shutil.which("google-chrome"), shutil.which("chrome"),
        shutil.which("chromium"), shutil.which("chromium-browser"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("No Chromium browser found; set ANOMALYZER_BROWSER to Chrome, Chromium, or Edge")


def render(name, svg, browser, temp):
    page = temp / f"{name}.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        'html,body{margin:0;width:1200px;height:680px;overflow:hidden;background:white}'
        '</style>' + svg,
        encoding="utf-8",
    )
    output = OUTPUT / f"{name}.png"
    command = [
        str(browser), "--headless=new", "--no-sandbox", "--disable-gpu",
        "--disable-software-rasterizer", "--disable-dev-shm-usage", "--hide-scrollbars",
        "--no-first-run", "--disable-background-networking", "--disable-extensions",
        f"--user-data-dir={temp / 'browser-profile'}",
        f"--window-size={WIDTH},{HEIGHT}", f"--screenshot={output}", page.as_uri(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if completed.returncode or not output.exists():
        details = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"Browser render failed for {name}: {details}")
    print(f"Rendered {output.relative_to(ROOT)}")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    figures = {
        "anomaly-progression-01-linear": figure_one(),
        "anomaly-progression-02-linear-seasonality": figure_two(),
        "anomaly-progression-03-compound": figure_three(),
        "anomaly-progression-04-adaptive": figure_adaptive(),
        "anomaly-progression-05-change-points": figure_four(),
        "anomaly-progression-06-season-discovery": figure_five(),
        "anomaly-progression-07-location-shift": figure_six(),
        "anomaly-progression-08-robust-outliers": figure_seven(),
        "anomaly-progression-09-reviewed-regime": figure_eight(),
        "anomaly-progression-10-reference-readiness": figure_readiness(),
        "anomaly-progression-11-multi-resolution": figure_multi_resolution(),
        "anomaly-progression-12-relationships": figure_relationship(),
        "nelson-rules-reference": figure_rule_reference(),
        "residual-detectors-reference": figure_extended_rule_reference(),
    }
    with tempfile.TemporaryDirectory(prefix="anomalyzer-readme-") as directory:
        temp = Path(directory)
        for name, svg in figures.items():
            render(name, svg, browser, temp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
