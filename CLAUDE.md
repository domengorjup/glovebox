# Project: autotracker

## Purpose
A self-hosted Home Assistant add-on for tracking car running costs across multiple vehicles: refuelling (fuel quantity, price per litre, total price, gas station), maintenance, and insurance/registration. It shows stats and filters (e.g. consumption over time, comparison across gas stations) and replaces Drivvo.

## Key constraints
- Runs as a Home Assistant OS add-on: Docker container, web UI served through HA Ingress (sidebar panel), data kept in a SQLite database under `/data`.
- Publishes a small set of HA sensors (e.g. last L/100km, monthly cost, next service due).
- Python backend; dependencies managed with `uv` (`pyproject.toml`).
- Import: Drivvo CSV, Fuelio CSV, Fuelly CSV. Export: a native full CSV and a Fuelly-compatible CSV.
- Scope is only the features listed above; no feature creep.
- Never commit real user export files (they contain personal data); use anonymised fixtures in tests.

## Git
- Standing permission (granted 2026-10-20): commit locally at sensible checkpoints (after the foundation, after each completed task group, after final checks). Never push without asking.

## Structure
- `src/autotracker/`: `app.py` (factory `create_app`, `main`), `config.py`, `db.py`, `models.py`, `urls.py` (`url(request, path)` base-path helper), `migrations/` (Alembic, run at startup), `services/{records,stats}.py`, `importers/{base,pipeline}.py` (+ `aliases/`), `exporters/{native,fuelly}.py`, `api/v1.py`, `web/` (routes, `templating.py`, `templates/`, `static/`).
- Group-1 interfaces are frozen stubs (`NotImplementedError`) that later task groups fill in; see `openspec/changes/add-autotracker-v1/`.
- `tests/`: `conftest.py` (migrated in-memory `engine`, `session`, `client` fixtures), `fixtures/` (anonymised samples only).
- Run: `uv run autotracker` (env: `DATA_DIR`, `AUTOTRACKER_PORT`, ...). Test: `uv run pytest`.
