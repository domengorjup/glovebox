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
- OpenSpec (`openspec/`) is for behaviour, API and data-model changes (e.g. v2). UI/layout work is done as design iterations without OpenSpec: clickable mockup or the running app, screenshots via headless browser, user feedback, repeat. Mockups live in `.mockups/` (locally excluded from git). `.mockups/ui-v2/` is the living UI mockup the user checks at will (open `index.html` directly, no server): design changes land there first, are recorded in its `NOTES.md` changelog, then go into the app.
- Test HA instance: HAOS VM `haos-test` in the user's restricted Incus project on `linux-turbo` (reach via SSH tunnel; HA UI is on VM port 80). Credentials for it live outside the repo in `~/.config/glovebox-test/ha.env`; never print or commit them.

## Autonomous implementation–review loop
Used when the user asks Claude to work without prompting them (granted 2026-10-20).
1. **Plan:** the coordinating session splits work into independent tasks with clear file ownership and dispatches subagents (parallel where files don't overlap).
2. **Implement:** each subagent implements, runs the full test suite, and for UI work captures headless-browser screenshots (desktop 1400x900, phone 390x844, light and dark).
3. **Review:** the coordinator reviews every result: tests green, diff scope matches the task, screenshots compared against the approved mockup, docs build with `--strict`, no references to other projects, no secrets or personal data. Findings go back to the same subagent as concrete fix requests; repeat until clean (cap ~3 rounds per task; if still blocked, note it for the user instead of asking).
4. **Integrate:** commit, push `master`; release (`.dev/release_deploy.py release`), deploy to the test HA (`deploy`), screenshot inside HA (`screenshot`) and review again.
5. **Report:** a concise summary for the user at the end, including anything left open.

Standing permissions for this loop: anything on the test VM `haos-test` (start/stop/restart, updates, its image and downloads); repo changes within the current scope (including deleting superseded files, a CI test workflow and publishing the MkDocs site on GitHub Pages). Nothing that could affect the user's own machine setup or other people's work on `linux-turbo`; ask only if something outside this is truly necessary.

## Next steps
- **Install and use v1** on Home Assistant OS (task 9.3); fix anything found. Then archive the OpenSpec change `add-autotracker-v1` via the `openspec-archive` skill.
- **Drivvo import** (tasks 4.3–4.5, 9.4) is blocked on a real Drivvo CSV export (English app, needs the paid plan). The current English alias mapping is provisional.
- **v2 (new OpenSpec change, after v1 has been used for a while):**
  - HACS companion integration that reads the stats API (token-protected add-on port 8100): one HA device per vehicle, sensors with long-term statistics. The sensor set should roughly mirror the Timeline summary cards (cost this month, average consumption, last refuel, cost per km, ...). No MQTT (the user runs ZHA, no Mosquitto).
  - `glovebox.log_refuel` HA action, backed by a new token-protected write endpoint; pre-select the nearest known station from the phone's location.
  - Phone-friendly "quick add refuelling" page (could come earlier).
  - Optional "next service due" sensor (reminders were deliberately left out of v1).
- **README polish (low priority):** add the icon, screenshots from the real app, a link to the docs site and badges (CI, licence, version).
- **More vehicle details (low priority, needs an OpenSpec change):** optional fields worth keeping at hand, e.g. VIN, year, engine/tyre sizes, insurance policy number and expiry, registration expiry. Keep the list short.
- **Later:** GitHub Actions multi-arch image build to GHCR (group 10), then point `config.yaml` `image:` at it, which removes the git clone in the add-on Dockerfile.

## Structure
- `src/glovebox/`: `app.py` (factory `create_app`, `main`), `config.py`, `db.py`, `models.py`, `auth.py` (add-on source check, standalone login/token), `urls.py` (`url(request, path)` base-path helper), `migrations/` (Alembic, run at startup), `services/{records,stats,preferences}.py` (preferences = app-bar vehicle, last vehicle, summary cards in the `setting` table, migration 0002), `importers/{base,pipeline,drivvo,fuelio,fuelly,native}.py` (+ `aliases/*.toml`), `exporters/{native,fuelly}.py`, `api/v1.py`, `web/` (`timeline.py` = `/` and `/add`, `statistics.py` = `/stats`, `manage.py` = `/manage`, `preferences.py`, plus `vehicles/refuels/expenses/stations/imports/exports.py`; `common.py` holds `render`, `load_chrome`; `templating.py`; `templates/`; `static/` = `app.css` (HA-named CSS variables), `app.js` (dialogs, calc, inline SVG charts), `theme.js` (inherits the HA theme from the same-origin parent, else built-in light/dark), `icons.svg` (used MDI icons) + `LICENSE-mdi.md`, `VENDORED.md`).
- Task groups 1-9 are implemented; the change artifacts are in `openspec/changes/add-autotracker-v1/`.
- `addon/glovebox/` (HA add-on files), `Dockerfile`, `docker/entrypoint.sh`, `repository.yaml`.
- `tests/`: `test_e2e.py` (no monkeypatching, drives the real web forms), `conftest.py` (migrated in-memory `engine`, `session`, `client` fixtures), `fixtures/` (anonymised samples only).
- Run: `uv run glovebox` (env: `DATA_DIR`, `GLOVEBOX_PORT`, ...). Test: `uv run pytest`.
