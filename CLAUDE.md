# Project: glovebox

## Purpose
A self-hosted Home Assistant add-on for tracking car running costs across multiple vehicles: refuelling (fuel quantity, price per litre, total price, gas station), maintenance, and insurance/registration. It shows stats and filters (e.g. consumption over time, comparison across gas stations) and replaces Drivvo.

## Key constraints
- Runs as a Home Assistant OS add-on: Docker container, web UI served through HA Ingress (sidebar panel), data kept in a SQLite database under `/data`.
- Exposes a read-only stats API (/api/v1); HA sensors come later via a companion integration (see Next steps).
- Python backend; dependencies managed with `uv` (`pyproject.toml`).
- Import: CSV through a mapping with presets (shipped: Glovebox standard, Fuelly, Fuelio, Drivvo best-effort; own presets saved in the DB) and the documented standard format. Export: standard CSV, Fuelly-compatible CSV, custom CSV, and a full backup ZIP (standard format plus `datapackage.json`).
- Scope is only the features listed above; no feature creep.
- Never commit real user export files (they contain personal data); use anonymised fixtures in tests.

## Git
- Release procedure: bump the version in `addon/glovebox/config.yaml`, `pyproject.toml` (then `uv lock`) and `SOURCE_REF=v<version>` in `addon/glovebox/Dockerfile`, add a CHANGELOG entry, commit, tag `v<version>`, push `master` and the tag.
- Standing permission (granted 2026-10-20): commit locally at sensible checkpoints (after the foundation, after each completed task group, after final checks).
- Standing permission (granted 2026-10-20): push `master` and release tags to `origin` (github.com/domengorjup/glovebox) after tests pass. Never force-push or rewrite published history without asking.

## Workflow
- Disclaimer: the README, the add-on `DOCS.md` and every docs page (MkDocs `copyright` footer) carry the notice that the project was made with AI assistance and is provided "as is" without warranty or liability. Keep it on new user-facing documents; the sibling project uses the same wording.
- OpenSpec (`openspec/`) is for behaviour, API and data-model changes (e.g. v2). UI/layout work is done as design iterations without OpenSpec: clickable mockup or the running app, screenshots via headless browser, user feedback, repeat. Mockups live in `.mockups/` (locally excluded from git). `.mockups/ui-v2/` is the living UI mockup the user checks at will (open `index.html` directly, no server): design changes land there first, are recorded in its `NOTES.md` changelog, then go into the app.
- UI design language: `docs/dev/design.md` lists the tokens and standard elements (with class names and snippets). Reuse an element from there before making a new one; follow Home Assistant / Material conventions and only make our own element if it is significantly simpler than the standard one; add every new repeated element to that document. No plain text links for in-app navigation (use buttons, icon buttons, list rows, tabs or chips).
- Sibling project: `/mnt/data/workspace/ha_shopping_expenses_app/` (the user's shopping list + shared expenses HA app) reuses this project's infrastructure. Shared design topics are kept in step between the two; offline use is documented in `docs/dev/offline.md` in both repos, so read the other app's copy before changing ours.
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
- **Configurable CSV import/export** (decided 2026-10-21; OpenSpec change `configurable-csv-import-export`): one generic, mapping-driven CSV importer and exporter with presets (Glovebox standard, Fuelly, Fuelio, Drivvo best-effort) instead of per-app importers. We do not track other apps' export formats. The standard format is documented mechanically from one code definition. This supersedes the blocked Drivvo tasks: Drivvo is now a best-effort preset and no longer needs a real export to ship; refine it when one is available. Remaining: task 7.7 (release, deploy to the test HA, import through the mapping step and a backup round trip there, screenshots).
- **v2 (new OpenSpec change, after v1 has been used for a while):**
  - HACS companion integration that reads the stats API (token-protected add-on port 8100): one HA device per vehicle, sensors with long-term statistics. The sensor set should roughly mirror the Timeline summary cards (cost this month, average consumption, last refuel, cost per km, ...). No MQTT (the user runs ZHA, no Mosquitto).
  - `glovebox.log_refuel` HA action, backed by a new token-protected write endpoint; pre-select the nearest known station from the phone's location.
  - Phone-friendly "quick add refuelling" page (could come earlier).
  - Optional "next service due" sensor (reminders were deliberately left out of v1).
- **Path to the first real release** (agreed 2026-10-21): finish configurable CSV import/export → full test on the HAOS VM with fictional demo data → housekeeping (README with screenshots, icon, docs link, badges; real-app screenshots in the docs site on GitHub Pages) → release.
- **README polish (low priority):** add the icon, screenshots from the real app, a link to the docs site and badges (CI, licence, version).
- **Reminders** (proposed 2026-10-21, needs an OpenSpec change; reaching the user's own calendars is a must): date reminders per vehicle (optional link to an expense, e.g. "N days before coverage ends" or "+1 year"), shown on the Timeline. Delivery, in order of preference: (1) the add-on writes each reminder into a user-chosen HA calendar entity via the Core API (`homeassistant_api: true`, `calendar.create_event`), which reaches Google (HA Google Calendar integration), Local Calendar and possibly CalDAV/Outlook (verify which support creating events, and how edits/deletes propagate); (2) an "Add to calendar" .ics download per reminder, which works with any calendar app; (3) optionally an iCal feed for HA's Remote Calendar (2025.4+, Basic auth only, 24 h refresh). Later, the companion integration adds a native calendar entity and odometer-based "service due" sensors. To-do entities were rejected (no due-date trigger).
- **Offline support (low priority, shared design):** the sibling app `/mnt/data/workspace/ha_shopping_expenses_app/` (shopping list + shared expenses, built on the same infrastructure) is designing offline use for when there is no internet or HA is down. Once that design settles, apply the same approach here. Prefer existing HA practices and the simplest option. Both apps keep their notes in `docs/dev/offline.md`; compare the two before changing either.
- **More vehicle details (low priority, needs an OpenSpec change):** optional fields worth keeping at hand, e.g. VIN, year, engine/tyre sizes, insurance policy number and expiry, registration expiry. Keep the list short.
- **Later:** GitHub Actions multi-arch image build to GHCR (group 10), then point `config.yaml` `image:` at it, which removes the git clone in the add-on Dockerfile.

## Structure
- `src/glovebox/`: `app.py` (factory `create_app`, `main`), `config.py`, `db.py`, `models.py`, `auth.py` (add-on source check, standalone login/token), `urls.py` (`url(request, path)` base-path helper), `migrations/` (Alembic, run at startup), `services/{records,stats,preferences}.py` (preferences = app-bar vehicle, last vehicle, summary cards in the `setting` table, migration 0002), `standard.py` (the standard CSV format, one code definition), `formatdocs.py` (generates `docs/user/standard-format.md`, its Data Package descriptor and `presets.md`; `--check` in tests), `presets/*.toml` (shipped presets), `importers/{base,presets,engine,pipeline}.py` (engine is pure; pipeline also handles `vehicles.csv`/`stations.csv` companion tables and backups; migration 0003 adds the `preset` table), `exporters/{csv_export,backup}.py`, `api/v1.py`, `web/` (`timeline.py` = `/` and `/add`, `statistics.py` = `/stats`, `manage.py` = `/manage`, `preferences.py`, plus `vehicles/refuels/expenses/stations/imports/exports/presets.py`; `common.py` holds `render`, `load_chrome`; `templating.py`; `templates/`; `static/` = `app.css` (HA-named CSS variables), `app.js` (dialogs, calc, inline SVG charts), `theme.js` (inherits the HA theme from the same-origin parent, else built-in light/dark), `icons.svg` (used MDI icons) + `LICENSE-mdi.md`, `VENDORED.md`).
- Task groups 1-9 are implemented; the change artifacts are in `openspec/changes/add-autotracker-v1/`.
- `addon/glovebox/` (HA add-on files), `Dockerfile`, `docker/entrypoint.sh`, `repository.yaml`.
- `tests/`: `test_e2e.py` (no monkeypatching, drives the real web forms), `conftest.py` (migrated in-memory `engine`, `session`, `client` fixtures), `fixtures/` (anonymised samples only).
- UI rules and every reusable element: `docs/dev/design.md` (read before touching templates or `app.css`).
- Run: `uv run glovebox` (env: `DATA_DIR`, `GLOVEBOX_PORT`, ...). Test: `uv run pytest`.
