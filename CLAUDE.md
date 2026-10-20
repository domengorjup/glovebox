# Project: glovebox

## Purpose
A self-hosted Home Assistant add-on for tracking car running costs across multiple vehicles: refuelling (fuel quantity, price per litre, total price, gas station), maintenance, and insurance/registration. It shows stats and filters (e.g. consumption over time, comparison across gas stations) and replaces Drivvo.

## Key constraints
- Runs as a Home Assistant OS add-on: Docker container, web UI served through HA Ingress (sidebar panel), data kept in a SQLite database under `/data`.
- Exposes a read-only stats API (/api/v1); HA sensors come later via a companion integration (see Next steps).
- Python backend; dependencies managed with `uv` (`pyproject.toml`).
- Import: Drivvo CSV, Fuelio CSV, Fuelly CSV. Export: a native full CSV and a Fuelly-compatible CSV.
- Scope is only the features listed above; no feature creep.
- Never commit real user export files (they contain personal data); use anonymised fixtures in tests.

## Git
- Release procedure: bump the version in `addon/glovebox/config.yaml`, `pyproject.toml` (then `uv lock`) and `SOURCE_REF=v<version>` in `addon/glovebox/Dockerfile`, add a CHANGELOG entry, commit, tag `v<version>`, push `master` and the tag.
- Standing permission (granted 2026-10-20): commit locally at sensible checkpoints (after the foundation, after each completed task group, after final checks).
- Standing permission (granted 2026-10-20): push `master` and release tags to `origin` (github.com/domengorjup/glovebox) after tests pass. Never force-push or rewrite published history without asking.

## Workflow
- OpenSpec (`openspec/`) is for behaviour, API and data-model changes (e.g. v2). UI/layout work is done as design iterations without OpenSpec: clickable mockup or the running app, screenshots via headless browser, user feedback, repeat. Mockups live in `.mockups/` (locally excluded from git).
- Test HA instance: HAOS VM `haos-test` in the user's restricted Incus project on `linux-turbo` (reach via SSH tunnel; HA UI is on VM port 80). Credentials for it live outside the repo in `~/.config/glovebox-test/ha.env`; never print or commit them.

## Next steps
- **Install and use v1** on Home Assistant OS (task 9.3); fix anything found. Then archive the OpenSpec change `add-autotracker-v1` via the `openspec-archive` skill.
- **Drivvo import** (tasks 4.3–4.5, 9.4) is blocked on a real Drivvo CSV export (English app, needs the paid plan). The current English alias mapping is provisional.
- **v2 (new OpenSpec change, after v1 has been used for a while):**
  - HACS companion integration that reads the stats API (token-protected add-on port 8100): one HA device per vehicle, sensors with long-term statistics. No MQTT (the user runs ZHA, no Mosquitto).
  - `glovebox.log_refuel` HA action, backed by a new token-protected write endpoint; pre-select the nearest known station from the phone's location.
  - Phone-friendly "quick add refuelling" page (could come earlier).
  - Optional "next service due" sensor (reminders were deliberately left out of v1).
- **Later:** GitHub Actions multi-arch image build to GHCR (group 10), then point `config.yaml` `image:` at it, which removes the git clone in the add-on Dockerfile.

## Structure
- `src/glovebox/`: `app.py` (factory `create_app`, `main`), `config.py`, `db.py`, `models.py`, `auth.py` (add-on source check, standalone login/token), `urls.py` (`url(request, path)` base-path helper), `migrations/` (Alembic, run at startup), `services/{records,stats}.py`, `importers/{base,pipeline,drivvo,fuelio,fuelly,native}.py` (+ `aliases/*.toml`), `exporters/{native,fuelly}.py`, `api/v1.py`, `web/` (routes, `templating.py`, `templates/`, `static/`).
- Task groups 1-9 are implemented; the change artifacts are in `openspec/changes/add-autotracker-v1/`.
- `addon/glovebox/` (HA add-on files), `Dockerfile`, `docker/entrypoint.sh`, `repository.yaml`.
- `tests/`: `test_e2e.py` (no monkeypatching, drives the real web forms), `conftest.py` (migrated in-memory `engine`, `session`, `client` fixtures), `fixtures/` (anonymised samples only).
- Run: `uv run glovebox` (env: `DATA_DIR`, `GLOVEBOX_PORT`, ...). Test: `uv run pytest`.
