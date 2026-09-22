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
import shutil
import subprocess
import tempfile
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
          label=None, boundaries=()):
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
        svg.text(x - 12, yy + 6, f"{value:.0f}", 15, MUTED, anchor="end")
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
    header(svg, "04", "Treat discontinuities as new regimes", "A reviewed change point restarts seasonal history, trend fitting, and calibration.")
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
    header(svg, "05", "Discover a stable season", "When positional input omits the lag, detrend a prefix, rank candidates, then confirm the winner early.")
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
    header(svg, "06", "Detect a sustained location shift",
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
    header(svg, "07", "Protect the model from an incident",
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
    header(svg, "08", "Do not normalize a new regime automatically",
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
        "anomaly-progression-04-change-points": figure_four(),
        "anomaly-progression-05-season-discovery": figure_five(),
        "anomaly-progression-06-location-shift": figure_six(),
        "anomaly-progression-07-robust-outliers": figure_seven(),
        "anomaly-progression-08-reviewed-regime": figure_eight(),
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
