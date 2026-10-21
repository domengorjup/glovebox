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

Screenshots are taken with a headless browser (Playwright with Chromium) against a running app with demo data. The images used by these docs and the exact states needed are listed in `docs/assets/screenshots/NEEDED.md`. Use a 1400x900 viewport for desktop and 390x844 for phone.

## Documentation

```sh
uv run --group docs mkdocs serve          # live preview at http://127.0.0.1:8000
uv run --group docs mkdocs build --strict # build into site/ (git-ignored)
```

The docs dependencies are in the separate `docs` dependency group, so `uv sync` does not install them. There is no automatic publishing yet.

## Dependencies

Add runtime dependencies with `uv add <package>`, and docs tooling with `uv add --group docs <package>`. Do not use `pip` directly.
