## How to run this change in parallel

- **Group 1** (Foundation) must be finished first. It freezes the shared interfaces: `models.py`, `importers/base.py`, and the signatures in `services/stats.py` and `services/records.py`.
- **Groups 2–8** are independent and can run in parallel:
  - records and stats services;
  - importers, with Drivvo split out;
  - exporters;
  - web UI;
  - API and authentication;
  - add-on packaging.
- **Group 9** integrates and verifies.
- **Group 10** (GHCR build workflow) is a later, optional step.
- **Shared rule:** no real user export files in git. Fixtures under `tests/fixtures/` are hand-made or anonymised.

## 1. Foundation (sequential, blocks everything else)

- [x] 1.1 Create `pyproject.toml` with a `src/glovebox` package. Add dependencies with `uv add fastapi uvicorn sqlalchemy alembic jinja2 python-multipart itsdangerous` and dev dependencies `pytest httpx`.
- [x] 1.2 Implement `config.py`. Read settings from env vars, plus `/data/options.json` in add-on mode:
  - `GLOVEBOX_MODE` (`standalone`|`addon`), `BASE_PATH`, `DATA_DIR`
  - `GLOVEBOX_PASSWORD`, `GLOVEBOX_API_TOKEN`, `GLOVEBOX_SECRET`
  - `CURRENCY` (default `EUR`)
- [x] 1.3 Implement `db.py`: SQLite engine under `DATA_DIR`, WAL mode, session factory.
- [x] 1.4 Implement `models.py` per design D3: vehicle, station, refuel, expense (with nullable `coverage_start` and `coverage_end`), import_batch. Money is stored as integer cents and price per litre as integer milli-units; category is an enum. Add the indexes that the duplicate-detection keys need.
- [x] 1.5 Set up Alembic and an initial migration. Run `upgrade head` automatically at app startup.
- [x] 1.6 Write `importers/base.py` (interface only, with docstrings):
  - `CanonicalVehicleRef`, `CanonicalRefuel`, `CanonicalExpense`, `ImportResult`
  - the `ImporterAdapter` protocol: `detect(head: bytes) -> float`, `parse(data: bytes, options) -> ImportResult`
- [x] 1.7 Write the stub signatures for `services/stats.py`:
  - `segments(refuels) -> list[Segment]`
  - `avg_consumption(segments)`
  - `cost_breakdown(filter, allocation)` and `cost_per_km(filter, allocation)`, with `allocation` as `spread` (default) or `paid`
  - `station_stats(filter, group_by)`
  - `vehicle_summary(vehicle_id, today, allocation)`
  - a `StatsFilter` dataclass (vehicles, date_from, date_to, categories, stations, brands)
- [x] 1.8 Write the stub signatures for `services/records.py`: CRUD for vehicles, stations (including merge and bulk brand), refuels and expenses.
- [x] 1.9 Create the FastAPI app skeleton (`app.py`):
  - router mounting for `web/` and `api/`;
  - a base-path helper `url(request, path)` honouring `X-Ingress-Path`, then `BASE_PATH`, then `/`;
  - a base Jinja2 layout that uses the helper.
- [x] 1.10 Set up the pytest scaffold: in-memory SQLite fixture, app test client, and the `tests/fixtures/` README stating the anonymisation rule.

## 2. Records and statistics services (needs 1)

- [x] 2.1 Implement vehicle CRUD:
  - archiving;
  - delete with record count and confirmation flag;
  - name uniqueness among active vehicles.
- [x] 2.2 Implement refuel CRUD:
  - two-of-three price derivation, with `derived_field` recorded;
  - a warning when the three figures are inconsistent by more than 1 %;
  - odometer-order warnings.
- [x] 2.3 Implement station CRUD, merge and bulk brand assignment (manual only, no brand detection). Implement expense CRUD with category validation and coverage-date validation (both or neither, end not before start).
- [x] 2.4 Implement `segments()` per design D4 (full-to-full, partial fills included, missed flag invalidates) and the distance-weighted `avg_consumption()`.
- [x] 2.5 Implement `cost_breakdown()` (totals, monthly and yearly series by category) and `cost_per_km()`, using the odometer span over all records in the period.
  - Support both allocation modes per design D5: `spread` (default; daily proportional, by month, largest-remainder rounding in cents, only the in-period share counted) and `paid`.
  - Records without coverage dates, and fuel, are identical in both modes. The functions never write to the database.
- [x] 2.6 Implement `station_stats()` grouped by station or brand:
  - litre-weighted, minimum and maximum price per litre;
  - consumption from single-source segments only, with segment counts and n/a below 2.
- [x] 2.7 Implement `vehicle_summary()` per the stats-api spec (cost fields follow `allocation`; no reminder fields), with nulls for values that cannot be computed.
- [x] 2.8 Write unit tests for every scenario in the fuel-records, expense-records, vehicle-management and statistics specs, including all four allocation scenarios (12-month spread, no coverage dates, year-boundary split, toggle leaves data unchanged).

## 3. Importers: pipeline, Fuelio, Fuelly, native (needs 1)

- [x] 3.1 Write the shared locale helpers in `importers/base.py`:
  - encoding detection (UTF-8, UTF-8 with BOM, cp1252 fallback);
  - delimiter sniffing;
  - per-column decimal detection;
  - date-format detection with an "ambiguous" result;
  - a TOML alias loader with case- and whitespace-insensitive matching.
- [x] 3.2 Implement `importers/pipeline.py`:
  - format detection with user override;
  - the preview object: counts, vehicles found, duplicates, warnings, errors, and the date-order question;
  - vehicle mapping;
  - duplicate keys;
  - transactional commit with an `import_batch`;
  - undo of a batch, including stations created only by that batch.
- [x] 3.3 Implement the Fuelio adapter:
  - single CSV or ZIP of CSVs;
  - section splitting on `## `, with the delimiter sniffed per section;
  - **`## Log` mapping:** `Data`; `Odo…` and `Fuel…` with unit conversion; `Full` (0 means partial); `Missed`; `VolumePrice` as price per litre and `Price (optional)` as total; station from `City (optional)` or FavStations `NameBrand`.
  - **`## Costs` mapping:** categories via CostCategories plus an alias table; skip template rows, income rows, and rows with cost ≤ 0.
- [x] 3.4 Build Fuelio fixtures by hand: comma and semicolon variants, km and miles headers, a ZIP with 2 vehicles. Write tests for every Fuelio scenario.
- [x] 3.5 Implement the Fuelly adapter:
  - header-based detection of the fuelly.com import format and export format;
  - miles/gallons conversion, asking for units when they are ambiguous;
  - mapping of the partial and missed flags;
  - total derived from litres × price.
- [x] 3.6 Build Fuelly fixtures (one per format) and write tests for every Fuelly scenario.
- [x] 3.7 Implement the native importer (reads the data-export ZIP) and the round-trip test (export, import into an empty DB, export again, compare).
- [x] 3.8 Write the end-to-end pipeline tests: preview writes nothing; re-import is a no-op; undo removes the batch; unknown headers are reported with the found and expected lists.

## 4. Drivvo importer (needs 1 and 3.1–3.2; 4.1 and 4.2 are doable now, 4.3 onwards BLOCKED on the user's real Drivvo export)

- [x] 4.1 Create the Drivvo adapter on the shared machinery (3.1–3.2), with detection and the unknown-headers error path.
- [x] 4.2 Write `aliases/drivvo.toml` with an English mapping for refuel, service and expense rows, marked PROVISIONAL in the file (best-guess headers, not from a real file). Map Drivvo service and expense types to our categories, keeping the original type as the title. Add a hand-made English fixture and tests for the provisional-mapping scenario.
- [ ] 4.3 **BLOCKED on real sample.** Analyse the user's real English Drivvo export (kept outside the repo): delimiter, header set per record type, date and number formats, station and brand fields, full/partial and missed flags.
- [ ] 4.4 **BLOCKED on real sample.** Correct `aliases/drivvo.toml` against the real export and remove the PROVISIONAL mark. Add other locales only if needed.
- [ ] 4.5 **BLOCKED on real sample.** Create an anonymised fixture from the real export (randomised station names, odometer offsets, no plates or VINs) and write the Drivvo refuelling-export scenario test.

## 5. Exporters (needs 1; for tests, 3.7 provides the round trip)

- [x] 5.1 Implement the native export ZIP (`vehicles.csv`, `stations.csv`, `refuels.csv`, `expenses.csv`, `manifest.json`). It covers all vehicles or a selected vehicle, in UTF-8 with ISO dates and `.` decimals.
- [x] 5.2 Implement the Fuelly-compatible export:
  - one CSV per vehicle, zipped if there is more than one;
  - header `fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags`;
  - station name in `tags`.
- [x] 5.3 Write tests: the export-contents scenario; the exact Fuelly row scenario; a header check against LubeLogger's alias list (taken from `MapProfile/ImportMappers.cs` and recorded in the test as a constant with its source URL).

## 6. Web UI (needs 1; uses 2's service signatures, can start against stubs)

- [x] 6.1 Vendor Chart.js and a classless CSS (e.g. Pico.css) into `static/`, with their licence files. Add a test that asserts that rendered pages reference no external hosts.
- [x] 6.2 Build the vehicles pages: list, create/edit, archive, delete confirmation that shows record counts.
- [x] 6.3 Build the refuel pages (brand is never auto-suggested):
  - list with filters (vehicle, date range, station/brand) and per-row consumption or n/a;
  - entry form with two-of-three price entry, inline station creation, and the full and missed checkboxes;
  - warnings shown before save.
- [x] 6.4 Build the expense pages: list with filters (vehicle, date range, category) and the filtered total; entry form with optional coverage start and end dates.
- [x] 6.5 Build the stations page: rename, bulk brand assignment, merge.
- [x] 6.6 Build the statistics dashboard. It contains:
  - a consumption-over-time chart (segments plus a monthly weighted average);
  - monthly and yearly cost-by-category charts, with a spread / as-paid toggle (`allocation` URL parameter, default spread, view-only);
  - cost per km;
  - a station/brand comparison table with segment counts and the mixed-station caveat;
  - all filters encoded in the URL query.
- [x] 6.7 Build the import page (upload, format override, preview showing vehicle mapping, the date-order question and duplicates, confirm, batch list with undo) and the export page (native and Fuelly, with the expenses-omitted note).
- [x] 6.8 Write template tests: every page renders under the root path and under an `X-Ingress-Path` prefix with all URLs prefixed; a bookmarked filter URL renders with its filters applied.

## 7. Stats API and access control (needs 1; uses 2's service signatures)

- [x] 7.1 Implement `api/v1.py`: `/vehicles`, `/vehicles/{id}/summary` (with `allocation=spread|paid`, default spread, 422 otherwise, echoed in the response), `/vehicles/{id}/consumption`, `/stations/stats`, with JSON 404 errors. Add response-shape snapshot tests that pin the v1 fields.
- [x] 7.2 Implement `auth.py` for standalone mode: optional single-password login with an itsdangerous-signed session cookie, plus a login page and logout. Log a startup warning when no password is set.
- [x] 7.3 Add Bearer-token checking for `/api/v1` in standalone mode when `GLOVEBOX_API_TOKEN` is set, returning 401 otherwise.
- [x] 7.4 Add the add-on mode source-address check (the ingress proxy only, otherwise 403). Verify the current proxy address and header behaviour against the HA developer docs, and record the source in a code comment.
- [x] 7.5 Write tests for every scenario in the web-access and stats-api specs, including the UI/API consistency check.

## 8. Add-on packaging and container (needs 1; can run in parallel with 2–7)

- [x] 8.1 Write the `Dockerfile`: Python 3.12 base, install with `uv` from the lockfile, non-root user where HA allows it. It serves on the ingress port in add-on mode and on 8080 in standalone mode, with an entrypoint that reads the mode.
- [x] 8.2 Create `repository.yaml` at the repo root and `addon/glovebox/`:
  - `config.yaml`: ingress, panel title "Glovebox", `mdi:car-wrench`, arch `amd64` and `aarch64`, options schema;
  - `DOCS.md`, `CHANGELOG.md`, `icon.png`, `logo.png`.
- [x] 8.3 Verify the `config.yaml` keys, base image and any `build.yaml` requirement against the current HA add-on developer docs. Note the doc URLs in the repo README.
- [x] 8.4 Write the README: install as an HA add-on (repository URL), run standalone (`docker run -p 8080:8080 -v ./data:/data …`), environment variables, backup and restore via the native export.

## 9. Integration and verification (after 2–8)

- [x] 9.1 Run the full pytest suite and fix any integration gaps between the groups.
- [x] 9.2 Build the image locally. Run it standalone, then smoke-test: create a vehicle, add refuels and an expense, view stats, export natively, import the export into a fresh volume.
- [ ] 9.3 Install as a local add-on on the user's HA OS. The user does this step, or it is done with their permission. Smoke-test the Ingress panel, then a backup and restore.
- [ ] 9.4 (BLOCKED on real sample) Import the user's real Drivvo export locally, without committing it. Compare the totals and the consumption against Drivvo's own reports, and record any differences.
- [x] 9.5 Run `openspec validate add-autotracker-v1 --strict` and update the artifacts to match what was built.

## 9a. Optional API listener in add-on mode (design D9a)

- [x] 9a.1 Settings: `api_port` (`GLOVEBOX_API_PORT`), minimum token length of 16 in add-on mode, clear error at startup.
- [x] 9a.2 `create_api_app` (only `/api/v1`, Bearer, 404 elsewhere) and `main()` running both uvicorn servers; no token means no listener plus a warning.
- [x] 9a.3 `config.yaml` `ports: {8100/tcp: null}` and `ports_description`; entrypoint default `GLOVEBOX_API_PORT=8100` in add-on mode.
- [x] 9a.4 DOCS.md and README: how to enable it and a `rest:` sensor example.
- [x] 9a.5 Tests for each scenario in the web-access spec, then a docker smoke test of both ports.

## 10. Later (optional in this change)

- [ ] 10.2 Future, only if a sample becomes available: Fuelly/aCar Android app export importer (column order in design D7 (c)). Not part of v1.
- [ ] 10.1 Add a GitHub Actions workflow that builds the multi-arch images (amd64, aarch64) and publishes them to GHCR. Point `config.yaml` `image:` at it so installs don't build locally.
