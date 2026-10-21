## How to run this change in parallel

- **Group 1** (foundation) runs first, by one agent. It freezes `standard.py`, `importers/presets.py` and the new signatures in `importers/engine.py`, `importers/pipeline.py`, `exporters/csv_export.py` and `exporters/backup.py`.
- **Groups 2–6** then run in parallel. Each owns the files listed in its heading and touches no others:
  - 2: import engine and pipeline;
  - 3: shipped presets;
  - 4: exporters;
  - 5: generated docs;
  - 6: web UI.
  Groups 3 and 6 can write their files from the frozen interfaces right away, but their tests only pass once group 2 (and group 4 for export pages) has landed. Run their full test suite last.
- **Group 7** integrates, removes the old modules, and verifies.
- **Test suite between groups:** the old adapter and exporter modules and their tests stay in place and green until 7.1. `tests/test_e2e.py` drives the web flow that group 6 changes; it may fail from group 6 until 7.2, and agents note this instead of fixing it outside their files.
- **Shared rules:** no real exports in git; committed files name no other projects as inspiration (format names as preset names are fine).

## 1. Foundation (sequential; owns `standard.py`, `importers/presets.py`, `importers/base.py`, `models.py`, `migrations/versions/0003_presets.py`)

- [x] 1.1 Write `src/glovebox/standard.py` per design D1/D2: `StandardField`, `RECORD_FIELDS`, `VEHICLE_FIELDS`, `STATION_FIELDS`, `EXAMPLE_RECORDS`, with descriptions and examples for every field.
- [x] 1.2 Implement `datapackage(meta=None)` in `standard.py` (design D3). Check the property names and the custom-property rule against the current published Table Schema / Data Package standard, and pin the profile. Add `tests/test_standard.py` (field order, required flags, the descriptor's structure).
- [x] 1.3 Write `importers/presets.py`:
  - the `Preset` dataclasses and the key table (key, type, allowed values, description);
  - `load_preset(text)` with validation that names the key path;
  - the TOML writer for the fixed shape;
  - `shipped_presets()` (from `src/glovebox/presets/*.toml`) and user preset CRUD (`list_presets(session)`, `save_user_preset`, `delete_user_preset`, `get_preset(session, id)`).
  Add `tests/test_presets.py`: validation errors, write→read round trip, name clash, shipped presets not writable.
- [x] 1.4 Add the `Preset` model to `models.py` and migration `0003_presets.py`: the `preset` table, and widen `import_batch.format`, `refuel.source` and `expense.source` to 50 characters, with a downgrade.
- [x] 1.5 Change `importers/base.py`:
  - keep the canonical records and the locale helpers;
  - add `RowError`, `Question`, `Answers`, and the optional `station_location`, `derived` and `source` fields on the canonical records;
  - add `row_errors`, `questions` and `skipped` to `ImportResult`;
  - keep `ImporterAdapter`, `AliasTable`, `load_aliases`, `HeaderMismatch` and `ImportOptions` for now, marked deprecated, so the old adapters and their tests stay green until task 7.1 deletes them.
- [x] 1.6 Write the stub signatures with docstrings:
  - `importers/engine.py`: `read_file`, `score`, `apply`, `SourceFile`;
  - `importers/pipeline.py`: `detect_preset`, plus `preview_import` and `commit_import` taking `preset` and `answers`;
  - `exporters/csv_export.py`: `export_csv`;
  - `exporters/backup.py`: `export_backup`.
  Commit (checkpoint).

## 2. Import engine and pipeline (needs 1; owns `importers/engine.py`, `importers/pipeline.py`, `tests/test_import_engine.py`, `tests/test_import_pipeline.py`, new fixtures `tests/fixtures/standard_*.csv`)

- [x] 2.1 Implement `read_file`:
  - encoding and delimiter detection (re-using the base helpers);
  - ZIP members, with the member stem as the default vehicle name;
  - `## Section` extraction;
  - header-row detection within the first 20 non-blank rows;
  - header matching with the parenthesis rule (design D4).
- [x] 2.2 Implement `score` and `detect_preset` (user presets first, then shipped; threshold 0.5; fall back to the standard preset with exact-name matches).
- [x] 2.3 Implement `apply`:
  - skip rules, constants, missing values, value maps, booleans and defaults;
  - strict number parsing, date patterns and automatic date order;
  - units from settings or headers, and unit conversion;
  - row errors with line numbers, and questions for date order and units.
- [x] 2.4 Update `pipeline.py` to take a `Preset` and `Answers`:
  - keep `_map_and_dedupe`, duplicate keys, station creation, undo and the single transaction;
  - replace the `getattr` extras with the explicit optional fields;
  - store the preset id as the batch format and the record source.
- [x] 2.5 Implement backup restore in the pipeline: a ZIP with `datapackage.json` creates vehicles from `vehicles.csv` and stations from `stations.csv`, then applies the `glovebox` preset to `records.csv`.
- [x] 2.6 Add hand-made fixtures:
  - `standard_records.csv` (every field, both types);
  - `standard_semicolon_comma.csv` (as saved by a spreadsheet in a decimal-comma locale);
  - `standard_bad_rows.csv` (per-row errors, including a stray thousands separator).
- [x] 2.7 Write `tests/test_import_engine.py` for every value-format scenario in the data-import spec. Rewrite `tests/test_import_pipeline.py` for the new signatures: preview writes nothing, duplicates, the vehicle choice, undo removes batch-only stations, two-of-three derivation, row errors are skipped and the rest commits.

## 3. Shipped presets (needs 1; owns `src/glovebox/presets/*.toml`, `tests/test_presets_shipped.py`)

- [x] 3.1 Write `glovebox.toml` (identity mapping, fixed formats, export on).
- [x] 3.2 Write `fuelly-metric.toml` (export on, split by vehicle), `fuelly-us.toml` and `fuelly-website.toml`, converted from `importers/aliases/fuelly.toml` and the rules in `importers/fuelly.py`, each with a comment header and note.
- [x] 3.3 Write `fuelio-fillups.toml` and `fuelio-costs.toml` from `aliases/fuelio.toml` and `fuelio.py` (sections, units `auto`, `Full` and `Missed` booleans, zero prices as missing, template/income skip rules, category map on `CostTitle`).
- [x] 3.4 Write `drivvo-refuelling.toml`, `drivvo-services.toml` and `drivvo-expenses.toml` from `aliases/drivvo.toml`, with `verified = false` and the note "Best effort, untested: not checked against a real export."
- [x] 3.5 Write `tests/test_presets_shipped.py`:
  - every shipped preset loads;
  - every existing fixture is detected as its preset and imports with the values asserted by the v1 tests;
  - port the expectations from `tests/test_import_fuelly.py`, `test_import_fuelio.py` and `test_import_drivvo.py`, minus the behaviours dropped in design D9;
  - `drivvo_unknown_headers.csv` now selects no preset and reports unmapped required fields.

## 4. Exporters (needs 1; owns `exporters/csv_export.py`, `exporters/backup.py`, `tests/test_export_csv.py`, `tests/test_export_backup.py`)

- [x] 4.1 Implement `export_csv`:
  - column order from the preset, first-listed values for maps and booleans, constant `type` as a filter;
  - unit conversion and the export precision from `standard.py`;
  - `split_by_vehicle` ZIP;
  - RFC 4180 output without BOM.
- [x] 4.2 Implement `export_backup`: `records.csv` via the `glovebox` preset, `vehicles.csv`, `stations.csv` (all stations, or only used ones with a vehicle selection), `datapackage.json` with the `glovebox` metadata, and the archived-name suffix rule (design D7).
- [x] 4.3 Write `tests/test_export_csv.py`: the Fuelly scenarios kept verbatim from `tests/test_export_fuelly.py`, the standard refuel row, the custom semicolon export, export in miles.
- [x] 4.4 Write `tests/test_export_backup.py`, replacing `tests/test_export_native.py`: contents, every record exactly once, metadata, and the round trip through restore (needs group 2).

## 5. Generated documentation (needs 1; owns `src/glovebox/formatdocs.py`, `docs/user/standard-format.md`, `docs/user/standard-format.datapackage.json`, `docs/user/presets.md`, `tests/test_format_docs.py`, `mkdocs.yml`)

- [x] 5.1 Implement `formatdocs.py` with `render_standard_markdown()`, `render_presets_markdown()` and a `__main__` that writes the three files, with `--check` (design D11). The standard page includes the conventions, the field tables, the example CSV and the "convert your own export" section (spreadsheet steps and a short `csv`-only Python example).
- [x] 5.2 Generate and commit the three files. Add them to the mkdocs nav under the user guide ("Standard CSV format", "Presets").
- [x] 5.3 Write `tests/test_format_docs.py`: committed files equal the rendered output (the failure names the command); the docs example CSV imports with the standard preset without errors (needs group 2); the descriptor fields match `RECORD_FIELDS`.
- [x] 5.4 Check that `mkdocs build --strict` passes.

## 6. Web UI (needs 1; owns `web/imports.py`, `web/exports.py`, `web/presets.py`, `templates/import/*`, `templates/export.html`, `templates/presets/*`, `templates/manage.html`, `tests/test_web_ui.py`)

- [x] 6.1 Import flow, following `docs/dev/design.md`:
  - upload, keeping the existing stored-upload token;
  - a mapping step showing the detected preset, encoding, delimiter and header row, with one row per standard field (source column or constant, plus per-field options for maps, booleans, missing values and default) and the file-level value formats;
  - a preview with counts, the preset note, questions and per-row errors (first 50 listed, total count);
  - confirm; "save as preset". The edited mapping is carried between steps as form fields.
- [x] 6.2 Export page: preset choice and vehicles; a "customise" form (include/rename columns, delimiter, decimal separator, date pattern, units, save as preset); full backup; a link to download the format description; the note that Fuelly exports have no expenses.
- [x] 6.3 Presets page (`/presets`, linked from Manage): list shipped and user presets with their verified status and note; download, upload, delete.
- [x] 6.4 Update `templates/manage.html` item texts (import: "CSV files with presets", export: "Standard CSV, Fuelly-compatible CSV or full backup").
- [x] 6.5 Update `tests/test_web_ui.py` for the new pages. Capture screenshots (desktop 1400x900, phone 390x844, light and dark) of the mapping, preview, export and presets pages.

## 7. Integration and verification (needs 2–6)

- [x] 7.1 Delete the superseded files and names: the deprecated names in `importers/base.py` and their tests in `tests/test_import_base.py`, `importers/drivvo.py`, `fuelio.py`, `fuelly.py`, `native.py`, `importers/aliases/`, `exporters/native.py`, `exporters/fuelly.py`, `tests/test_import_drivvo.py`, `test_import_fuelio.py`, `test_import_fuelly.py`, `test_export_native.py`, `test_export_fuelly.py`.
- [x] 7.2 Update `tests/test_e2e.py`:
  - imports through the web flow pick a preset instead of a format;
  - `test_native_export_reimports_identically` becomes a backup round trip;
  - `test_native_manifest_uses_app_settings` checks `datapackage.json`;
  - add an end-to-end run through the mapping step that saves a user preset and has it detected on the next upload.
- [x] 7.3 Rewrite the hand-written docs: `docs/user/import.md` (mapping flow, presets, link to the standard format), `docs/user/export.md` (standard, Fuelly, custom, backup), `docs/dev/importers.md` (engine and preset files instead of adapters and aliases), plus the import/export mentions in `docs/user/overview.md`, `docs/user/faq.md`, `docs/index.md`, `README.md`, `addon/glovebox/DOCS.md`, `docs/dev/architecture.md`, `docs/dev/layout.md` and `docs/dev/testing.md`. Update `tests/fixtures/README.md` (fixtures belong to presets).
- [x] 7.4 Update `CLAUDE.md`:
  - Key constraints: import is presets plus the standard format; export is standard, Fuelly-compatible, custom, and full backup;
  - Structure;
  - Next steps: Drivvo is now a preset, no longer blocked.
- [ ] 7.5 Add a CHANGELOG entry: v1 native backups cannot be imported; make a new full backup after upgrading; Fuelio imports run once per section.
  (Not written to `addon/glovebox/CHANGELOG.md`: the release script inserts the version heading above the first `## ` heading, so an `## Unreleased` section would end up below it. The text goes into the release message instead.)
- [x] 7.6 Run the full test suite, `mkdocs build --strict` and `uv run python -m glovebox.formatdocs --check`. Check that no file names other projects as inspiration and that no fixture holds personal data.
- [ ] 7.7 Release and deploy to the test HA per the project loop. Run an import through the mapping step and a backup round trip inside HA, and take screenshots.
