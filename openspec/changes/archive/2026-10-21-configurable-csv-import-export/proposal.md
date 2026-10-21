## Why

v1 has one hand-written importer per app (Drivvo, Fuelio, Fuelly) plus a native one, and two hand-written exporters. Each importer encodes guesses about a format that its vendor can change at any time, and the Drivvo one has never seen a real file. The user has decided that keeping up with other apps' export formats is not worth the effort.

Instead, Glovebox gets one configurable CSV engine. File layouts become data (presets) that the user can adjust in the app or write by hand. The centre of it is a plain, documented standard format that anyone can produce from any readable export with a spreadsheet or a short script, even for apps Glovebox has no preset for.

## What Changes

- **One CSV import engine; mappings are data.** A preset (a small TOML file) says which source column, or which constant, feeds each standard field, plus the value formats: date pattern, decimal and thousands separator, units, value maps, true/false values, missing values, rows to skip, and an optional `## Section` of a multi-table file.
- **Shipped presets:** `Glovebox standard`, `Fuelly (metric)`, `Fuelly (US units)`, `Fuelly (website export)`, `Fuelio fill-ups`, `Fuelio costs`, and three `Drivvo` presets (refuelling, services, expenses) marked "best effort, untested". They are converted from the v1 alias tables and adapter rules.
- **BREAKING (internal):** the per-app importer modules (`importers/drivvo.py`, `fuelio.py`, `fuelly.py`, `native.py`), the alias tables (`importers/aliases/`) and the per-app exporters (`exporters/native.py`, `exporters/fuelly.py`) are removed. The detect → preview → commit → undo-batch pipeline stays, with its guarantees: derived price figures, duplicate detection, station creation and vehicle choice.
- **Mapping step in the import flow:**
  1. Upload. Encoding, delimiter, header row and the best-matching preset are detected.
  2. The user adjusts the mapping and value formats.
  3. Preview with per-row errors.
  4. Commit.
  The mapping can be saved as the user's own preset (stored in the database, downloadable and uploadable as a TOML file).
- **Export through the same presets:** the standard CSV and the Fuelly-compatible CSV, plus custom column selection and format options, savable as a preset.
- **Standard format:** one tidy CSV, one row per record, with `type` and `vehicle` columns. It follows RFC 4180, UTF-8, ISO 8601 dates, a dot decimal, metric units named in the column names, and money as a decimal in a stated currency. It is lossless for everything a user enters, so standard export → import round-trips.
- **BREAKING (file format):** the native ZIP backup is replaced by a **full backup ZIP built from the standard format**: `records.csv` (the standard file) plus `vehicles.csv`, `stations.csv` and a `datapackage.json` descriptor. v1 native ZIPs can no longer be imported (see design, open question Q1).
- **Mechanical documentation:** one code-level definition of the standard format is the single source of truth. A generator writes the user docs page and a machine-readable description that follows the Table Schema / Data Package standard. A test fails when the committed docs are stale. The preset file reference is generated the same way from the preset loader's key definitions.
- No new runtime dependencies.

## Capabilities

### New Capabilities
- `standard-format`: the Glovebox standard CSV format (records, vehicles, stations), its single code-level definition, and the generated human and machine-readable documentation with its staleness check.

### Modified Capabilities
- `data-import`: per-app importers and alias tables are replaced by one preset-driven engine with a mapping step, value-format options, per-row errors, shipped and user presets, and backup restore. The pipeline guarantees (preview, single-transaction commit, undo, duplicates, vehicle mapping) are kept.
- `data-export`: the native ZIP is replaced by a standard-format full backup. The Fuelly-compatible export becomes a preset. Standard CSV export and custom column/format export are added.

## Impact

- **Code:**
  - New: `src/glovebox/standard.py`, `importers/presets.py`, `importers/engine.py`, `exporters/csv_export.py`, `exporters/backup.py`, `formatdocs.py`, `src/glovebox/presets/*.toml`.
  - Changed: `importers/base.py` (adapter protocol and alias loader go; locale helpers stay), `importers/pipeline.py`, `web/imports.py`, `web/exports.py`, a new `web/presets.py`, and the import/export templates.
  - Removed: the per-app importer and exporter modules and `importers/aliases/`.
- **Data model:** new `preset` table. `import_batch.format`, `refuel.source` and `expense.source` are widened to hold preset ids. One Alembic migration.
- **Docs:**
  - Generated: `docs/user/standard-format.md`, `docs/user/standard-format.datapackage.json`, `docs/user/presets.md`.
  - Rewritten: `docs/user/import.md`, `docs/user/export.md`, `docs/dev/importers.md`.
  - mkdocs nav updated.
- **Tests:** the per-app importer tests and the native/Fuelly exporter tests are replaced by preset, engine, export and backup tests. All existing fixtures are kept and re-used as preset fixtures.
- **Users:** v1 native backups need to be re-made after upgrading (the database itself migrates in place). The Fuelio import loses three cross-table lookups (see design D9).
