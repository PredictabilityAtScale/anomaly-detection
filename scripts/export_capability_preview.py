"""Freeze CapabilityKit's bubble graph as a script-free README image."""

import argparse
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".capabilities/dependency-graph.svg"
OUTPUT = ROOT / ".capabilities/dependency-preview.svg"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def settle(nodes, links, width, height):
    """Run the original export's force layout to rest, at its default spacing."""
    alpha, spacing, padding = 1.0, 1.25, 74
    for node in nodes:
        node["vx"] = node["vy"] = 0.0
    for tick in range(2000):
        for node in nodes:
            node["vx"] += (width / 2 - node["x"]) * 0.0009 * alpha
            node["vy"] += (height / 2 + 18 - node["y"]) * 0.0009 * alpha
        for source, target in links:
            dx, dy = target["x"] - source["x"], target["y"] - source["y"]
            distance = math.hypot(dx, dy) or 1
            desired = (210 + max(source["r"], target["r"]) * 0.55) * spacing
            strength = (distance - desired) * 0.012 * alpha
            fx, fy = dx / distance * strength, dy / distance * strength
            source["vx"] += fx
            source["vy"] += fy
            target["vx"] -= fx
            target["vy"] -= fy
        for index, a in enumerate(nodes):
            for b in nodes[index + 1:]:
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                distance = math.hypot(dx, dy) or 1
                minimum = (a["r"] + b["r"] + 46) * spacing
                repulsion = min(15000 * spacing / distance**2, 2.4) * alpha
                fx, fy = dx / distance * repulsion, dy / distance * repulsion
                a["vx"] -= fx
                a["vy"] -= fy
                b["vx"] += fx
                b["vy"] += fy
                if distance < minimum:
                    push = (minimum - distance) / distance * 0.55
                    a["x"] -= dx * push
                    a["y"] -= dy * push
                    b["x"] += dx * push
                    b["y"] += dy * push
        for node in nodes:
            node["vx"] *= 0.78
            node["vy"] *= 0.78
            node["x"] = max(padding + node["r"],
                            min(width - padding - node["r"], node["x"] + node["vx"]))
            node["y"] = max(118 + node["r"],
                            min(height - padding - node["r"], node["y"] + node["vy"]))
        alpha *= 0.972
        # The browser renders and checks for rest every four simulation ticks.
        velocity = max((abs(n["vx"]) + abs(n["vy"]) for n in nodes), default=0)
        if tick % 4 == 3 and alpha < 0.016 and velocity < 0.05:
            return
    raise ValueError("Bubble layout did not settle")


def render(source: str) -> str:
    match = re.search(r"^const graph = (.+);$", source, re.MULTILINE)
    if not match:
        raise ValueError("CapabilityKit export has no graph JSON payload")
    graph = json.loads(match.group(1))
    root = ET.fromstring(source)
    _, _, width, height = map(float, root.attrib["viewBox"].split())
    by_id = {node["id"]: node for node in graph["nodes"]}
    links = [(by_id[link["source"]], by_id[link["target"]]) for link in graph["links"]]
    settle(graph["nodes"], links, width, height)

    # Keep the original gradients, bubble sizes, labels, colors, legend, and
    # curves. Remove the controls and scripts that cannot work in an image.
    for parent in root.iter():
        for child in list(parent):
            if child.tag == f"{{{SVG}}}script" or child.get("id") in {"controls", "details"}:
                parent.remove(child)
    root.find(f"{{{SVG}}}desc").text = (
        "Static snapshot of CapabilityKit's bubble dependency graph. "
        "Arrows point from dependencies to dependents; colors reflect saved "
        "acceptance coverage, not detection accuracy."
    )
    for text in root.iter(f"{{{SVG}}}text"):
        if text.get("class") == "chrome-subtitle":
            text.text = "Bubble dependency map. Open the interactive map to explore paths and evidence."
        elif text.get("class") == "drag-note":
            text.text = "Coverage reflects saved reviews, not detection accuracy."
    style = root.find(f"{{{SVG}}}style")
    style.text = style.text.rstrip() + "\n    .node { cursor: default; }\n"

    def element(parent, tag, text=None, **attrs):
        child = ET.SubElement(parent, f"{{{SVG}}}{tag}",
                              {key: str(value) for key, value in attrs.items()})
        child.text = text
        return child

    links_layer = root.find(f".//{{{SVG}}}g[@id='links']")
    nodes_layer = root.find(f".//{{{SVG}}}g[@id='nodes']")
    for link, (a, b) in zip(graph["links"], links):
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        distance = math.hypot(dx, dy) or 1
        sx, sy = a["x"] + dx / distance * (a["r"] + 7), a["y"] + dy / distance * (a["r"] + 7)
        tx, ty = b["x"] - dx / distance * (b["r"] + 11), b["y"] - dy / distance * (b["r"] + 11)
        curve = min(90, distance * 0.18)
        mx, my = (sx + tx) / 2 - dy / distance * curve, (sy + ty) / 2 + dx / distance * curve
        element(links_layer, "path", **{
            "class": "link " + link["kind"],
            "d": f"M{sx:.1f},{sy:.1f} Q{mx:.1f},{my:.1f} {tx:.1f},{ty:.1f}",
        })
    for node in graph["nodes"]:
        group = element(nodes_layer, "g", **{
            "class": "node " + node["coverage"],
            "data-capability": node["id"],
            "transform": f"translate({node['x']:.1f} {node['y']:.1f})",
        })
        element(group, "title", node["title"])
        for style, radius in (("node-halo", node["r"] + 8),
                              ("node-ring", node["r"]),
                              ("node-core", max(node["r"] - 10, 20))):
            element(group, "circle", **{"class": style, "r": radius})
        label = element(group, "text", **{"class": "label", "y": -3})
        words = node["label"].split(" ")
        if len(words) > 2:
            split = math.ceil(len(words) / 2)
            element(label, "tspan", " ".join(words[:split]), x=0, dy=-3)
            element(label, "tspan", " ".join(words[split:]), x=0, dy=14)
        else:
            label.text = node["label"]
        element(group, "text", node["scopeLabel"], **{"class": "meta", "y": node["r"] - 12})
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


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
        OUTPUT.write_text(preview, encoding="utf-8", newline="\n")
        print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
