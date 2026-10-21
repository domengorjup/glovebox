# Local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                  # creates .venv and installs the project and dev tools
DATA_DIR=./data uv run glovebox
```

Open `http://localhost:8080/`. Useful variables: `DATA_DIR`, `GLOVEBOX_PORT`, `GLOVEBOX_PASSWORD`, `GLOVEBOX_API_TOKEN` (see [Install](../user/install.md)).

## Tests

```sh
uv run pytest
```

## Screenshots

Screenshots are taken with a headless browser (Playwright with Chromium) against a running app that holds fictional demo data. `.dev/make_demo_data.py` regenerates the demo files in `.dev/demo/` (two vehicles, about 14 months of records, four stations); import `.dev/demo/demo.zip` through the Import page. Use a fresh `DATA_DIR`, a 1400x900 viewport for desktop and 390x844 for phone, and never real data. The images in `docs/assets/screenshots/` are named `<page>-<desktop|phone>-<light|dark>.png`; reduce them to a palette (for example with Pillow `quantize`) to keep the repository small.

## Documentation

```sh
uv run --group docs mkdocs serve          # live preview at http://127.0.0.1:8000
uv run --group docs mkdocs build --strict # build into site/ (git-ignored)
```

The docs dependencies are in the separate `docs` dependency group, so `uv sync` does not install them. The `Docs` workflow builds the site and publishes it to GitHub Pages when `docs/`, `mkdocs.yml` or `README.md` change on `master`; the `Tests` workflow runs `pytest`.

`docs/user/standard-format.md` and `docs/user/presets.md` are generated: run `uv run python -m glovebox.formatdocs` after changing `standard.py` or a preset (`--check` verifies them).

## Dependencies

Add runtime dependencies with `uv add <package>`, and docs tooling with `uv add --group docs <package>`. Do not use `pip` directly.
