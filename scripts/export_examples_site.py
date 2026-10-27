"""Publish the existing numbered README progression with its checked-in figures."""
import argparse
import html
from pathlib import Path
import re
import shutil

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/PredictabilityAtScale/anomaly-detection/blob/main/"


def page(markdown, destination, title):
    def target(match):
        label, link = match.groups()
        if link.startswith("docs/images/") or link.startswith("images/"):
            link = "assets/"+Path(link).name
        elif link == "docs/sparse-data.md":
            link = "sparse-data.html"
        elif not link.startswith(("https://", "http://", "#")):
            link = SOURCE+link.removeprefix("../")
        return f"[{label}]({link})"
    markdown = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", target, markdown)
    renderer = MarkdownIt("default", {"html": False})
    # Stable heading anchors preserve links in the numbered progression.
    def heading_open(tokens, index, options, env):
        text = tokens[index+1].content.lower()
        anchor = re.sub(r"[^\w -]", "", text).replace(" ", "-")
        return f'<{tokens[index].tag} id="{html.escape(anchor)}">'
    renderer.add_render_rule("heading_open", lambda self, tokens, idx, opts, env: heading_open(tokens, idx, opts, env))
    content = renderer.render(markdown)
    destination.write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font:18px/1.6 Arial,sans-serif;color:#172330;max-width:1140px;margin:36px auto;padding:0 24px}}
a{{color:#2563a6}}nav{{border-bottom:1px solid #dce1e7;padding-bottom:18px}}img{{width:100%;height:auto}}
pre{{background:#eef1f4;padding:18px;overflow:auto}}code{{font-size:.88em}}table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;border:1px solid #dce1e7;padding:10px}}h2,h3{{line-height:1.25;margin-top:2em}}</style>
<nav><a href="../">Capability maps</a> · <a href="index.html">Numbered examples</a> ·
<a href="sparse-data.html">Sparse-data API</a> · <a href="{SOURCE}docs/releases/README.md">Release guide</a></nav>
<main>{content}</main><footer>Synthetic examples establish mechanics, not measured abuse accuracy.</footer></html>''', encoding="utf-8")
    for image in re.findall(r'src="(assets/[^\"]+)"', content):
        if not (destination.parent/image).is_file():
            raise FileNotFoundError(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".tmp/examples-site"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assets = args.output/"assets"
    assets.mkdir(exist_ok=True)
    for image in (ROOT/"docs/images").glob("*.png"):
        shutil.copyfile(image, assets/image.name)
    readme = (ROOT/"README.md").read_text(encoding="utf-8")
    progression = readme.split("## The progression", 1)[1].split("## Baseline and calibration reference", 1)[0]
    page("# Anomalyzer: the progression\n"+progression, args.output/"index.html", "Anomalyzer — numbered examples")
    page((ROOT/"docs/sparse-data.md").read_text(), args.output/"sparse-data.html", "Anomalyzer — sparse data")
    print(f"Exported numbered progression and sparse-data guide to {args.output}")


if __name__ == "__main__":
    main()
