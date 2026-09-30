# Contributing to Anomalyzer

Thanks for helping improve Anomalyzer. Focused issues and pull requests are
welcome, especially when they include a reproducible time series and explain the
expected evidence.

## Development setup

Anomalyzer supports Python 3.11–3.13. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked --extra dev
uv run pytest -q
```

With pip and a virtual environment:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
```

## Before opening a pull request

The behavior map lives in [`.capabilities/`](.capabilities/), grouped into data,
analysis, relationships, investigation, interfaces, and execution. Each capability
describes an observable outcome with 3–5 acceptance criteria, 3–5 representative
automated checks, source/test references, and a focused manual interpretation check.
The automated commands use `python -m pytest` from the repository root in the
installed development environment described above. Parameterized tests may exercise
several examples within one check.

When changing behavior, update the matching capability and run its listed checks.
Use `capabilitykit check --fix` to format and validate the map and refresh its
compiled output. Read [the local guide](docs/capabilitykit/SKILL.md) for review and
dependency workflows. `implemented` records existing behavior; passing selected
tests alone does not mean a capability has been semantically verified.

After updating capabilities or their review evidence, regenerate the interactive
maps and the static README preview:

```bash
capabilitykit graph-viewer
capabilitykit story-map-viewer
python scripts/export_capability_preview.py
```

Commit all three viewer exports and `.capabilities/dependency-preview.svg`.
The preview freezes the original bubble graph's force layout into pre-rendered
nodes and edges because SVG image embeds do not execute JavaScript.
`python scripts/export_capability_preview.py --check` checks
that it matches the graph export. The Capability maps workflow checks the preview
on pull requests and publishes the two HTML viewers, preview, and landing page
to GitHub Pages after changes reach `main`. Repository Settings → Pages must use
**GitHub Actions** as the publishing source.

- Add or update tests for behavior changes.
- Keep analysis causal: an observation must not influence its own baseline.
- Preserve deterministic numerical output except for documented runtime values
  and generated identifiers.
- Regenerate schemas with `python scripts/export_schemas.py` after changing a
  public request or result model.
- Run `python -m pytest -q` and `python examples/run_demo.py`.
- Update the README when behavior, inputs, output, or limitations change.

By contributing, you agree that your contribution is licensed under the MIT
License that covers this repository.
