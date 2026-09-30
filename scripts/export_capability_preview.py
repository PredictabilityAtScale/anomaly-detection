"""Render CapabilityKit's graph data as a script-free README image."""

import argparse
from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".capabilities/dependency-graph.svg"
OUTPUT = ROOT / ".capabilities/dependency-preview.svg"
COLORS = {"full": "#059669", "partial": "#d97706", "uncovered": "#e11d48"}


def render(source: str) -> str:
    # Reuse the export's actual coverage and declared edges, without reassessing
    # capabilities or executing the JavaScript bundled with the viewer.
    match = re.search(r"^const graph = (.+);$", source, re.MULTILINE)
    if not match:
        raise ValueError("CapabilityKit export has no graph JSON payload")
    graph = json.loads(match.group(1))
    nodes = {node["id"]: node for node in graph["nodes"]}
    parents = defaultdict(list)
    children = defaultdict(list)
    for link in graph["links"]:
        if link["kind"] == "committed":
            parents[link["target"]].append(link["source"])
            children[link["source"]].append(link["target"])

    ranks = {}
    visiting = set()

    def rank(node_id):
        if node_id in visiting:
            raise ValueError(f"Dependency cycle at {node_id}")
        if node_id not in ranks:
            visiting.add(node_id)
            ranks[node_id] = max((rank(p) for p in parents[node_id]), default=-1) + 1
            visiting.remove(node_id)
        return ranks[node_id]

    for node_id in nodes:
        rank(node_id)
    last_rank = max(ranks.values(), default=0)
    columns = defaultdict(list)
    leaves = []
    for node_id in sorted(nodes):
        if children[node_id]:
            columns[ranks[node_id]].append(node_id)
        else:
            leaves.append(node_id)
    # Move terminal capabilities rightward to avoid one crowded middle column.
    for node_id in sorted(leaves, key=lambda i: (-ranks[i], i)):
        column = min(range(ranks[node_id], last_rank + 1),
                     key=lambda c: (len(columns[c]), c))
        columns[column].append(node_id)

    card_w, card_h, gap_x, gap_y = 240, 112, 66, 28
    margin, top = 36, 160
    rows = max((len(column) for column in columns.values()), default=1)
    width = margin * 2 + (last_rank + 1) * card_w + last_rank * gap_x
    graph_bottom = top + rows * (card_h + gap_y)
    long_links = [link for link in graph["links"]
                  if positions_column(link["target"], columns)
                  - positions_column(link["source"], columns) != 1]
    height = graph_bottom + len(long_links) * 8 + 70
    positions = {}
    for column in range(last_rank + 1):
        # Keep related nodes near the vertical positions of their dependencies.
        columns[column].sort(key=lambda i: (
            sum(positions[p][1] for p in parents[i]) / len(parents[i])
            if parents[i] else 0, nodes[i]["scope"], i))
        offset = (rows - len(columns[column])) * (card_h + gap_y) / 2
        for row, node_id in enumerate(columns[column]):
            positions[node_id] = (
                margin + column * (card_w + gap_x),
                top + offset + row * (card_h + gap_y),
            )

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Anomalyzer capability dependencies</title>',
        '<desc id="desc">Static capability map. Arrows lead from a dependency to '
        'the capability that uses it. Colors reflect saved acceptance coverage, '
        'not detection accuracy. Open the interactive map for evidence.</desc>',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" '
        'refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" '
        'fill="#94a3b8"/></marker></defs>',
        '<style>text {font-family:Segoe UI,Arial,sans-serif;fill:#0f172a} '
        '.heading {font-size:30px;font-weight:700} '
        '.note {font-size:17px;fill:#475569} '
        '.label {font-size:17px;font-weight:600} '
        '.scope {font-size:13px;fill:#64748b}</style>',
        f'<rect width="{width}" height="{height}" fill="#f8fafc"/>',
        '<text x="36" y="50" class="heading">Anomalyzer capability dependencies</text>',
        '<text x="36" y="82" class="note">Dependency → dependent capability · '
        f'{len(nodes)} capabilities · {len(graph["links"])} dependencies</text>',
    ]
    for index, (coverage, color) in enumerate(COLORS.items()):
        x = margin + index * 250
        label = {"full": "Full coverage", "partial": "Partial coverage",
                 "uncovered": "Not covered"}[coverage]
        svg.append(f'<circle cx="{x + 7}" cy="118" r="6" fill="{color}"/>')
        svg.append(f'<text x="{x + 23}" y="124" class="note">{label}</text>')

    rail = 0
    for link in graph["links"]:
        x1, y1 = positions[link["source"]]
        x2, y2 = positions[link["target"]]
        x1 += card_w
        y1 += card_h / 2
        y2 += card_h / 2
        if x2 - x1 > gap_x:
            # Route links that skip a column through gutters and bottom rails;
            # drawing them behind unrelated cards suggests false dependencies.
            rail_y = graph_bottom + rail * 8
            rail += 1
            path = (f"M{x1},{y1} H{x1 + 18} V{rail_y} "
                    f"H{x2 - 18} V{y2} H{x2 - 3}")
        else:
            bend = gap_x / 2
            path = (f"M{x1},{y1} C{x1 + bend},{y1} "
                    f"{x2 - bend},{y2} {x2 - 3},{y2}")
        dash = ' stroke-dasharray="6 5"' if link["kind"] == "suggested" else ""
        svg.append(f'<path d="{path}" fill="none" '
                   f'stroke="#94a3b8" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>')

    for node_id, (x, y) in positions.items():
        node = nodes[node_id]
        color = COLORS[node["coverage"]]
        svg.append(f'<g data-capability="{escape(node_id, quote=True)}">')
        svg.append(f'<title>{escape(node["title"])} ({escape(node["coverage"])})</title>')
        svg.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" '
                   f'rx="10" fill="white" stroke="{color}" stroke-width="2"/>')
        lines = textwrap.wrap(node["title"], width=26)
        if len(lines) > 4:
            raise ValueError(f"Title needs a taller card: {node_id}")
        for index, line in enumerate(lines):
            svg.append(f'<text x="{x + 14}" y="{y + 24 + index * 20}" '
                       f'class="label">{escape(line)}</text>')
        svg.append(f'<text x="{x + 14}" y="{y + card_h - 10}" '
                   f'class="scope">{escape(node["scope"])}</text></g>')
    svg.append(f'<text x="36" y="{height - 36}" class="note">'
               'Coverage reflects saved reviews, not detection accuracy. '
               'Open the interactive map for acceptance criteria and evidence.</text>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n"


def positions_column(node_id, columns):
    return next(column for column, members in columns.items() if node_id in members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the preview is stale")
    args = parser.parse_args()
    preview = render(SOURCE.read_text(encoding="utf-8"))
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != preview:
            parser.exit(1, "Capability preview is stale; run python scripts/export_capability_preview.py\n")
        print("Capability preview is current")
    else:
        OUTPUT.write_text(preview, encoding="utf-8")
        print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
