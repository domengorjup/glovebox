## Context

This is a greenfield project. The user runs Home Assistant OS, tracks one or more cars in Drivvo, and wants:
- refuelling (litres, price/L, total, station);
- maintenance, insurance and registration costs;
- statistics and filters, especially consumption over time and comparison between gas stations and companies;
- import of existing history and export to a common format.

Later the app should also reach users outside HA OS. Those users get a standalone Docker image now and a HACS companion integration for HA sensors in a later change.

Constraints:
- Python backend; dependencies managed with `uv`.
- Must work behind HA Ingress, which serves the app under a per-install path prefix and authenticates the HA user.
- Single household, low data volume (thousands of rows, not millions).
- Real export files contain personal data and are never committed.

## Goals / Non-Goals

**Goals:**
- One codebase and one Docker image, usable as an HA add-on or standalone.
- Correct full-to-full consumption, including partial and missed fill-ups.
- Station and brand as first-class data, so comparisons are cheap and correct.
- Importers that tolerate the locale differences in real exports (headers, decimals, dates, delimiters) and can be re-run without creating duplicates.
- A stable, versioned stats API that a future integration can rely on.

**Non-Goals:**
- HACS companion integration and HA sensors. This is the next change; only the API it will read is built now.
- Reminders and "next service due" (no API field, no sensor), trip logging, tyres, documents and attachments, receipts and photos.
- Multiple users or roles, and multiple currencies with conversion.
- Imperial storage units. Values are stored metric; importers convert.
- Electric or hybrid charging records.
- A generic interactive column-mapping importer UI. Known formats are handled by alias tables instead.
- Bidirectional sync with any other app.
- Automatic brand detection. Station brands are assigned by hand only (single or bulk on the stations page); the app never guesses a brand from a station name.
- The Fuelly/aCar Android export format. It is a future item, only if a sample becomes available.

## Decisions

### D1. Stack: FastAPI + SQLAlchemy 2 + Alembic + Jinja2 templates, vendored Chart.js
- **Server-rendered HTML** keeps the front end small: no Node build, no single-page-app framework. Forms work without JavaScript; Chart.js renders the charts from JSON embedded in the page or fetched from the same JSON endpoints the stats API uses.
- **FastAPI** gives HTML routes and the JSON API in one app, with typed request models.
- **Alembic** is required because add-on users upgrade in place; the schema must migrate automatically at startup.
- **Alternatives considered:**
  - Flask: equally viable; FastAPI was chosen for the typed API.
  - Django: too heavy.
  - A SPA (React/Vue): needs a JS build and is more work for a form- and table-heavy app.
  - Raw `sqlite3`: migrations would have to be hand-rolled.
- Front-end assets (Chart.js and a classless CSS such as Pico.css) are vendored into `static/`. Ingress and offline installs must not depend on a CDN.

### D2. Storage units and money
- **Units:** distance is stored in km, volume in litres. Money is stored as integer minor units (cents) to avoid float drift.
- **Currency:** one app-wide currency code, a setting with default `EUR`. It is used for display only.
- **Numbers per refuel:** litres (3 decimals), price per litre (3 decimals, stored as milli-units), total (cents).
- **Missing values:** a refuelling may be entered with any two of {litres, price/L, total}; the third is derived and the derivation is recorded (`derived_field`). When all three are given and disagree by more than 1 %, the form warns but saves.
- **Alternative considered:** per-vehicle units. Rejected for v1 (the user is metric); importers convert miles and gallons on the way in.

### D3. Data model
- **`vehicle`**: id, name, make, model, plate, fuel_type (free text), initial_odometer, archived flag, notes.
- **`station`**: id, name, brand (nullable), location text (nullable), unique(name, location).
  - **Brand** is what "compare across gas station companies" groups by. For example: station "Petrol Ljubljana Tržaška", brand "Petrol".
  - **Assigning brands:** by hand only, singly or in bulk on the stations page. No automatic detection from the station name (non-goal). Imports set a brand only when the source file provides one.
- **`refuel`**: id, vehicle_id, date (date + optional time), odometer_km, litres, price_per_litre, total, station_id (nullable), is_full, missed_previous, notes, source, source_ref, created_at.
- **`expense`**: id, vehicle_id, date, odometer_km (nullable), category, title, amount, coverage_start (nullable date), coverage_end (nullable date), notes, source, source_ref, created_at.
  - **Coverage dates** are optional on any expense, meant for insurance, registration and similar fixed costs. Both or neither must be set, and end must not be before start (both inclusive). `amount` always holds the full price paid.
  - **`category`** is a fixed enum: `maintenance`, `insurance`, `registration`, `other`.
  - **`title`** keeps the original category or description from imports, e.g. "Oil change", "Parking", "Vinjeta".
  - **Alternative considered:** user-defined categories. Rejected because the user's scope is these four, and `title` keeps the detail.
- **`import_batch`**: id, format, filename, created_at, counts. Rows carry `source` and `source_ref` so an import can be traced and undone. Undo means deleting by batch.

### D4. Consumption algorithm (full-to-full)
- **Ordering:** for one vehicle, sort refuels by (odometer, date).
- **Segments:** a segment ends at each full fill `F_k` and starts at the previous full fill `F_j`.
  - Segment distance = `odo(F_k) − odo(F_j)`.
  - Segment fuel = sum of litres of all fills in `(F_j, F_k]`. Partial fills in between are included; the fuel in `F_j` itself is excluded.
  - Consumption = fuel / distance × 100 (L/100 km).
- **Segments are invalid (excluded from stats, shown as "n/a")** when:
  - any fill in `(F_j, F_k]` has `missed_previous = true`;
  - there is no earlier full fill;
  - distance ≤ 0.
- **Attribution:** a segment belongs to the date of `F_k`, and to the station of `F_k`.
  - **Caveat:** station attribution is only meaningful when the segment's fuel came from one station. The UI states this. Per-station consumption uses only segments where every fill in `(F_j, F_k]` is from the same station; per-station *price* uses all fills.
- **Averages:** the period average is Σfuel / Σdistance over valid segments, weighted by distance. It is not the mean of segment values.
- **Alternatives considered:** per-fill consumption that assumes every fill is full. Rejected because it is wrong with partial fills, the classic error.

### D5. Cost per km and cost breakdowns
- **Cost per km for a period:** (Σ refuel totals + Σ expenses in period) / distance driven in the period.
- **Distance driven:** max odometer − min odometer over all records in the period, including expenses with an odometer.
- **Monthly and yearly breakdowns:** sums by category, with fuel as its own category.
- **Allocation modes** for expenses:
  - **`spread`** (default): an expense with coverage dates is split across the days of its coverage period (start and end inclusive), proportional to days, and each month gets its day share. An expense without coverage dates is counted in full on its date.
  - **`paid`**: the full amount is counted on the payment date, whether or not coverage dates exist.
  - Fuel is never spread. Records without coverage dates give identical results in both modes.
- **Rounding:** spread amounts are computed in integer cents with the largest-remainder method, so the monthly parts always sum exactly to the full amount.
- **Filters and periods:** with `spread`, a period (month, year or custom range) receives only the share of a cost that falls inside it. Viewing one month in `paid` mode shows the full payment in the month of the payment date.
- **Cost per km** uses the same allocation mode as the rest of the view; the distance part (D5 odometer span) is unaffected.
- **UI-only toggle:** the mode is a view setting (`allocation` query parameter, reflected in the URL) on the charts and monthly views. Switching it never writes to the database; stored records keep the full price and coverage dates.
- **Stats API:** the endpoints that return cost figures accept `allocation=spread|paid`, default `spread`, so API and UI agree. The summary's cost fields (this month, this year, cost per km) follow it. Responses echo the mode used (`allocation`).

### D6. Importers: one pipeline, per-format adapters, locale alias tables
- **Pipeline:** `parse(file) → [CanonicalRecord] → validate → dedupe → preview → commit`.
- **Adapters:** each format is a `ImporterAdapter` with `detect(head_bytes) -> confidence` and `parse(file, options) -> ImportResult`.
  - **`ImportResult`:** records, warnings, errors, and vehicle names found in the file.
  - **The UI calls only the pipeline.** Adapters are independent modules. This is the parallel-work boundary.
- **Locale handling, shared by all adapters:**
  - **Encoding:** UTF-8 with or without BOM, falling back to cp1252.
  - **Delimiter:** sniffed among `,` `;` `\t`.
  - **Decimal separator:** detected per column (`1.234,56` vs `1,234.56`).
  - **Dates:** parsed from a list of candidate formats, chosen per file by majority success. When ambiguous (e.g. `03/04/2024`), the importer asks in the preview.
- **Headers:** matched through alias tables (`importers/aliases/<format>.toml`). These map canonical field → list of header strings per language, compared case- and whitespace-insensitively. A new locale is a data change, not a code change.
- **Unrecognised required headers:** the preview fails with a clear list of the headers found and the headers expected. The user's file is never guessed at silently.
- **Vehicle mapping:** the preview lists the vehicle names found in the file and lets the user map each to an existing vehicle or create a new one.
- **Duplicate detection:**
  - **Refuel key:** (vehicle, date, odometer, litres rounded to 0.01).
  - **Expense key:** (vehicle, date, category, amount).
  - Duplicates are skipped and counted, so re-importing the same file is a no-op.
- **Stations from imports:** created by name on import. Brand is left empty unless the source provides one (never inferred from the name).
- **Alternative considered:** a generic column-mapping UI. Rejected for v1 scope; alias tables cover the three known formats and are easy to extend.

### D7. Format knowledge (research status)
- **Fuelio** (third-party reverse-engineered; two independent open-source parsers agree on the core columns; Fuelio's own docs not consulted):
  - **Container:** the backup is a CSV per vehicle, possibly inside a `.zip`. It has sections whose first field starts with `## `: `## Vehicle`, `## Log`, `## CostCategories`, `## Costs`, `## FavStations`, `## Pictures`. Every value is quoted, and the delimiter may be `,` or `;`.
  - **`## Log` columns:**
    - **`Data`:** the date column. It holds `yyyy-MM-dd HH:mm` and is spelled "Data" in the file.
    - **Odometer and fuel:** `Odo (km)`, `Fuel (litres)`. The headers carry the unit and change with it, e.g. `Odo(km)` in older files, miles in others.
    - **`Full`:** `0` means partial; any other value means full.
    - **`Price (optional)`** is the **total**. **`VolumePrice`** is the **price per litre**.
    - **`City (optional)`** holds the station or place display name. `StationID (optional)` refers to `## FavStations.StationID`, and FavStations has `NameBrand`.
    - **`Missed`:** missed previous fill-up flag.
    - Also present: `Notes (optional)`, `FuelType` (numeric code), `UniqueId`.
  - **`## Costs` columns:** `CostTitle`, `Date` (`yyyy-MM-dd HH:mm`), `Odo`, `CostTypeID` (resolved through `## CostCategories` `CostTypeID`→`Name`), `Notes`, `Cost`, `isTemplate`, `isIncome`.
    - **Skipped:** template rows, income rows, and rows with Cost ≤ 0.
    - **Category mapping:** CostTypeID names are matched to our categories by an alias table (e.g. Service/Maintenance→maintenance, Insurance→insurance, Registration→registration, anything else→other, with the Fuelio category name kept as `title`).
- **Fuelly:** v1 supports **two different formats**, (a) and (b); (c) is noted for the future. The importer detects which one it has by its headers.
  - **(a) fuelly.com import format,** per the Fuelly CSV-import help page, read only through a search summary because the page returned 403 (**unverified verbatim**):
    - `odometer` or `miles`/`km`;
    - `gallons` or `litres`;
    - `price` (per unit);
    - `fuelup_date` (`YYYY-MM-DD`, `M/D/YY`, or `YYYY-MM-DD HH:MM:SS`);
    - `missed_fuelup` (0/1), `partial_fuelup` (0/1);
    - optional `city_percentage`, `tags`, `notes`.
  - **(b) fuelly.com export format** (per the Fuelly FAQ summary and May's test fixture, **unverified against a real file**): `Name, Model, MPG, Odometer, Miles, Gallons, Price, Fuelup Date, Date Added, Tags, Notes`.
    - **Units:** Gallons/Miles may hold the user's configured units. Whether the header changes is unknown, so the preview asks for units when the headers are ambiguous.
  - **(c) Fuelly/aCar Android app export (future, not in v1),** as consumed by Hammond's importer (`server/service/importService.go`):
    - **Column order:** 0 type (`Gas`/`Service`), 1 MPG, 2 date, 3 time, 4 vehicle, 5 odometer, 6 fill (`Full`/partial), 7 price per unit, 8 quantity, 9 total cost, 10 octane, 11 gas brand, 12 location, 13 tags, 14 payment type, 15 tire pressure, 16 notes, 17 services.
    - **Support:** not in v1. Added in a later change only if a sample becomes available (see Non-Goals).
- **Drivvo:** **real format unknown; English mapping provisional.** The user's Drivvo app is in English, so English is the first and default locale.
  - **Known so far:** export is per vehicle from the app's History tab and follows the active filter; it needs a paid plan; headers are translated into the app language (a Danish export with translated headers was reported in Hammond issue #21).
  - **Plan:** the adapter uses the shared machinery (D6) and ships an English alias table in `aliases/drivvo.toml`, marked provisional and based on a best guess of English header names, not on a real file. The preview reports unknown headers rather than guessing. Finalising the mapping, adding a fixture and other locales is blocked until the user gets the paid export (O1).
- **Fuelly-compatible export (our output):** follows format (a) with metric headers: `fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags`.
  - **Readable by LubeLogger, verified from its source** (`MapProfile/ImportMappers.cs`): it recognises `fuelup_date`, `odometer`, `litres`, `price`, `partial_fuelup`, `missed_fuelup`, `notes`, `tags`. It derives total cost as quantity × price when no `cost` column is present.
  - **Station:** goes into `tags` as well as into notes, so it survives in tools without a station field. The Fuelly importer reads the whole `tags` cell, trimmed, back as the station name (no splitting, no brand).
  - **Import preview:** files without vehicle names (Fuelly import format) ask for a target vehicle. A header-only Fuelly file produces the warning "The file has no data rows."

### D8. Exports
- **Native export:** a ZIP containing `vehicles.csv`, `stations.csv`, `refuels.csv`, `expenses.csv`, plus `manifest.json` (app version, schema version, export date, currency).
  - **Format:** UTF-8, comma delimiter, ISO dates, `.` decimals. It round-trips exactly through the native importer, including each record's `derived_field` and `source`.
- **Fuelly-compatible export:** one CSV per vehicle, zipped if there is more than one vehicle. Expenses are not part of that format and are omitted; the UI says so.

### D9. Web access: Ingress prefix, root, and optional login
- **Path prefix:** the app reads the `X-Ingress-Path` request header (set by the HA Supervisor) or a `BASE_PATH` env var, and uses it as the root path.
  - All templates build URLs through a single `url_for`-style helper. No absolute paths are hard-coded; static assets and API calls use the same helper.
- **Ingress mode** (`GLOVEBOX_MODE=addon`):
  - No app-level login; HA has already authenticated the user.
  - The server listens on the ingress port and accepts requests only from the Supervisor ingress proxy address (`172.30.32.2`). **Unverified detail:** confirm against current HA developer docs during implementation.
- **Standalone mode** (default):
  - If `GLOVEBOX_PASSWORD` is set, a single-password login with a signed session cookie (itsdangerous) protects HTML routes.
  - If unset, there is no login, and a startup log warning recommends a reverse proxy.
  - The stats API also accepts `Authorization: Bearer <GLOVEBOX_API_TOKEN>` when that variable is set. This is what the future integration will use.
- **Alternatives considered:**
  - Full user accounts: out of scope for single-household use.
  - Relying only on a reverse proxy: a password is cheap and safer by default.

### D10. Stats API contract (`/api/v1`)
- **Endpoints:** read-only JSON.
  - `GET /api/v1/vehicles`
  - `GET /api/v1/vehicles/{id}/summary?allocation=spread|paid`
  - `GET /api/v1/vehicles/{id}/consumption?from&to`
  - `GET /api/v1/stations/stats?vehicle&from&to`
- **Allocation parameter:** `allocation=spread|paid`, default `spread`, accepted by endpoints that return costs (currently the summary). An invalid value returns HTTP 422. The response includes the `allocation` used.
- **Summary fields:** last odometer, last refuel (date, litres, price per litre, station), last valid consumption, average consumption over the last 12 months, cost this month, cost this year, cost per km over the last 12 months, currency. No reminder or "next service due" field.
- **Versioning:** field names are stable within v1. Additions are allowed; removals require `/api/v2`. Tests pin the response shape.
- **Shared code:** HTML pages and the API call the same stats service functions, so numbers cannot diverge.

### D11. HA add-on packaging
- **Repository layout:** `repository.yaml` at the repo root and an add-on folder `glovebox/` containing:
  - `config.yaml` (name, slug, version, arch `[amd64, aarch64]`, `ingress: true`, `ingress_port`, `panel_icon: mdi:car-wrench`, `panel_title`, `init: false`);
  - `Dockerfile` (FROM the add-on base Python image, or `python:3.12-slim`);
  - `DOCS.md`, `CHANGELOG.md`, icon and logo.
- **Data:** the database lives at `/data/glovebox.db`, which HA includes in its add-on backups.
- **Build:** v1 builds locally on the HA host from the Dockerfile; no registry is needed. A GitHub Actions workflow that builds multi-arch images and publishes them to GHCR is a separate, later task group.
- **Unverified details to check against current HA developer docs:** the exact `config.yaml` keys, the base-image names, and whether `build.yaml` is still needed.
- **Standalone image:** the same Dockerfile, run with `GLOVEBOX_MODE=standalone`, `DATA_DIR=/data` and port 8080.

### D12. Code layout and parallel-work interfaces

```
src/glovebox/
  config.py            # settings from env/options (mode, base path, data dir, password, token, currency)
  db.py, models.py     # SQLAlchemy models (D3); Alembic in migrations/
  services/
    records.py         # CRUD + validation + price derivation (fuel-records, expense-records, vehicles)
    stats.py           # consumption, cost, station/brand stats (D4, D5) - pure functions over rows
  importers/
    base.py            # CanonicalRefuel, CanonicalExpense, ImportResult, ImporterAdapter protocol,
                       # locale helpers (number/date/delimiter detection), alias loader
    pipeline.py        # detect → parse → dedupe → preview → commit
    drivvo.py, fuelio.py, fuelly.py, native.py, aliases/*.toml
  exporters/native.py, exporters/fuelly.py
  web/                 # HTML routes, templates/, static/ (vendored)
  api/v1.py            # stats API
  auth.py              # D9
addon/glovebox/     # HA add-on folder; repository.yaml at repo root
tests/fixtures/        # anonymised samples only
```

- **Frozen interfaces:** `models.py`, `importers/base.py` and the function signatures in `services/stats.py` are written first, as task group 1, and then frozen.
- **Parallel work:** after that, importers, exporters, web UI, the API and add-on packaging can be built in parallel.

## Risks / Trade-offs

- **The Drivvo format is unknown and locale-dependent.** → English is the default locale with a provisional alias table, finalising is blocked on a real sample, and the preview reports exactly which headers did not match.
- **Fuelly has several formats, and its docs could not be fetched verbatim.** → The importer detects the format by its headers, tests cover each known header set, and formats are marked unverified until a real file is checked.
- **Fuelio headers embed units (`Odo (km)` vs miles), and the delimiter varies.** → Headers are matched by prefix plus a unit suffix, the delimiter is sniffed per section, and miles/gallons are converted.
- **Per-station consumption is misleading when tanks mix stations.** → Only single-station segments are used for it, the sample size is shown, and the UI notes the caveat.
- **Ingress source-IP restriction details may differ between HA versions.** → Verify during implementation, and keep it behind a config switch.
- **SQLite on an SD card (some HA hosts):** low write volume makes this acceptable. WAL mode is used.
- **Annual costs spike monthly charts when shown as paid.** → The default view is spread across the coverage period; the as-paid view is one toggle away. Expenses without coverage dates cannot be spread and stay on their payment date.

## Migration Plan

- Greenfield, so there is no data migration. Alembic runs `upgrade head` at startup, which covers future upgrades.
- **Rollback:** HA add-on backups snapshot `/data`, and the native export gives a format-independent backup.

## Open Questions

- **O1. Drivvo export (blocked on the user's paid export):** confirm the real English headers, the delimiter, date and number formats, and whether filtered exports split by record type. Until then the English mapping is provisional.

Resolved: Fuelly/aCar Android (not in v1, future item if a sample appears), spreading annual costs (spread by default, as-paid toggle), automatic brands (non-goal), reminders (non-goal).
