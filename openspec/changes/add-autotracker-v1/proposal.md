## Why

The user tracks car running costs in Drivvo, a proprietary freemium app whose data export is paywalled. No maintained open-source tool both runs inside Home Assistant and imports Drivvo data. The one HA add-on that does (`miczu71/fuel_tracker`) has no licence and logs in with Drivvo credentials. glovebox v1 is a small, self-hosted replacement. It covers only the features the user actually uses and can bring existing history in from the common apps.

## What Changes

- New standalone web application (Python, SQLite) shipped as a Docker image. It runs either behind Home Assistant Ingress (under a path prefix) or on its own (at root), with an optional built-in login.
- New Home Assistant add-on wrapper and add-on repository layout, so HA OS users can install it from a repository URL. It gets a sidebar panel through Ingress and keeps its data in `/data`, which HA includes in its backups.
- Multiple vehicles, each with:
  - **refuelling records:** date, odometer, litres, price per litre, total price, gas station, full/partial fill, missed previous fill-up, notes;
  - **expense records:** maintenance/service, insurance, registration, other. Fixed costs can carry an optional coverage period (start and end date).
- Gas stations are a first-class entity with an optional brand, so prices and consumption can be compared per station and per company.
- Statistics:
  - consumption (L/100 km, full-to-full);
  - cost per km;
  - monthly and yearly costs by category;
  - price per litre and consumption by station and by brand.
- Cost statistics support two allocation modes: **spread** (default; a cost with a coverage period is split across it, proportional to days, by month) and **as paid** (full amount on the payment date). The mode is a view setting only; stored records always keep the full price.
- Filters for vehicle, date range, category and station.
- Import from Drivvo CSV, Fuelio CSV backup and Fuelly CSV, each with a preview step and duplicate detection. Native-format import too, for backup and restore.
  - The user's Drivvo app is in English, so English is the default Drivvo locale. The Drivvo column mapping is **provisional** until it is checked against a real export (the user will get the paid export later).
- Export as a native full export (ZIP of CSVs, re-importable) and a Fuelly-compatible CSV that other trackers can read.
- A small, versioned, read-only JSON stats API (`/api/v1/...`). It is the contract for a later HACS companion integration that will expose HA sensors. The integration itself is **not** part of this change.

## Non-goals

- Automatic station brand detection. Brands are assigned by hand only.
- Reminders and "next service due" (no such field in the API, no sensor).
- Fuelly/aCar Android app format. It is a possible future item, only if a sample becomes available.

## Capabilities

### New Capabilities
- `vehicle-management`: create, edit, archive and delete vehicles; each record belongs to one vehicle.
- `fuel-records`: refuelling records and gas stations (with manually assigned brand), including validation and derivation of the missing price field.
- `expense-records`: maintenance/service, insurance, registration and other cost records, with optional coverage dates.
- `statistics`: consumption, cost-per-km, cost breakdowns (spread or as paid), station/brand comparisons, and the filters over them.
- `data-import`: Drivvo, Fuelio, Fuelly and native-format importers, with preview, locale handling and duplicate detection.
- `data-export`: native full export and Fuelly-compatible export.
- `stats-api`: versioned, read-only JSON API for summaries per vehicle, intended for a future HA companion integration.
- `web-access`: serving under an Ingress path prefix or at root, plus the optional standalone login.
- `ha-addon`: Home Assistant add-on packaging, add-on repository layout and container build.

### Modified Capabilities
<!-- None: this is the first change in the project. -->

## Impact

- New codebase: Python package `glovebox` (FastAPI app, SQLAlchemy models, Alembic migrations, importers/exporters, Jinja2 templates, vendored static assets), plus `Dockerfile`, add-on folder and `repository.yaml`.
- New dependencies (via `uv add`): fastapi, uvicorn, sqlalchemy, alembic, jinja2, python-multipart, itsdangerous. Dev dependencies: pytest, httpx.
- Vendored front-end assets (no CDN, because Ingress and offline use must work): Chart.js and a small classless CSS framework.
- No external services. User data stays in the SQLite file. Real user export files are never committed; tests use anonymised fixtures.
