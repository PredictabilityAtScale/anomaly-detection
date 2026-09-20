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
