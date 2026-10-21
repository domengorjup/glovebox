## Context

v1 (change `add-autotracker-v1`, archived into `openspec/specs/`) imports through `importers/pipeline.py`:

```text
detect -> adapter.parse -> map vehicles -> derive figures -> dedupe -> preview -> commit (one batch) -> undo
```

Four adapters (`drivvo.py`, `fuelio.py`, `fuelly.py`, `native.py`) turn bytes into `CanonicalRefuel` / `CanonicalExpense` records. They use shared locale helpers in `importers/base.py` and alias tables in `importers/aliases/*.toml`. Two exporters write the native ZIP and the Fuelly import-format CSV.

The user has decided not to keep up with other apps' formats. This change replaces the per-app code with one engine driven by presets. A documented standard format is the target that people convert to on their own.

Constraints that still hold:
- Single household, thousands of rows.
- No new runtime dependencies unless clearly justified.
- No real exports in git.
- UI layout follows `docs/dev/design.md`.
- Committed files name no other projects as inspiration. Format names (Drivvo, Fuelio, Fuelly) as preset names are fine.

## Goals / Non-Goals

**Goals:**
- One import engine and one export engine; every file layout is a preset file.
- A standard format that is flat, boring, lossless for user-entered data, and easy to produce from a spreadsheet.
- Docs and a machine-readable description generated from one code-level definition, with a test that catches stale docs.
- Keep every v1 pipeline guarantee: preview writes nothing, one transaction per commit, undo by batch, duplicate keys, derived price figures, station creation by name, vehicle mapping.

**Non-Goals:**
- Keeping up with other apps. Shipped non-standard presets are best effort; their accuracy is not a release criterion.
- Formulas, computed columns, joining columns, or lookups across tables in presets (see D9).
- Excel/ODS files, JSON or XML input. CSV (optionally inside a ZIP) only.
- Import of v1 native ZIPs (see Q1).
- Date-range filters on export, scheduled exports, export to other apps' multi-table formats.
- Renaming or editing shipped presets in place. Users copy them into their own presets.

## Decisions

### D1. The standard format: one tidy records table plus two small tables for the backup

`records.csv` has one row per record and a `type` column (`refuel` or `expense`). Column names are the field names and carry the unit where there is one. These columns are the same targets that every preset maps to.

| Column | Type | Applies to | Required | Notes |
|---|---|---|---|---|
| `type` | `refuel` \| `expense` | all | yes | |
| `vehicle` | text | all | yes | Vehicle name |
| `date` | date `YYYY-MM-DD` | all | yes | |
| `time` | time `HH:MM` | refuel | no | `HH:MM:SS` also accepted |
| `odometer_km` | number, km | all | refuel: yes; expense: no | |
| `fuel_l` | number, litres | refuel | two of `fuel_l`, `price_per_l`, `total` | The third one is derived |
| `price_per_l` | number, currency per litre | refuel | (see above) | |
| `total` | number, currency | all | expense: yes, > 0 | Refuel total or expense amount |
| `currency` | ISO 4217 code | all | no | Must equal the app currency when given |
| `full` | `true` \| `false` | refuel | no, default `true` | Full tank |
| `missed_previous` | `true` \| `false` | refuel | no, default `false` | A fill-up before this one was not recorded |
| `station` | text | refuel | no | Station name |
| `station_location` | text | refuel | no | Together with the name, identifies the station |
| `station_brand` | text | refuel | no | Used only when the station is created |
| `category` | `maintenance` \| `insurance` \| `registration` \| `other` | expense | no, default `other` | |
| `title` | text | expense | yes | |
| `coverage_start`, `coverage_end` | date | expense | both or neither | |
| `notes` | text | all | no | |
| `derived` | `fuel_l` \| `price_per_l` \| `total` | refuel | no | Written by Glovebox; which figure was derived (maps to the stored `DerivedField` values) |
| `source`, `source_ref` | text | all | no | Written by Glovebox; where the record came from |

- **Conventions:**
  - RFC 4180: comma delimiter, `"` quoting, CRLF line ends, a header row.
  - UTF-8 without BOM on export; a BOM is accepted on import.
  - Dates ISO 8601; dot decimal; no thousands separator; booleans `true`/`false`.
  - Money is a decimal number in the currency named in `currency` (the app's single currency).
  - Empty cell means "no value".
  - Export precision follows storage: `fuel_l` and `price_per_l` 3 decimals, `total` 2 decimals, `odometer_km` without trailing zeros.
- **Why units in column names:** a file opened in a spreadsheet explains itself, and a conversion script cannot mix units by accident. Presets still convert from miles and gallons (D4).
- **Why one table with a `type` column, rather than separate refuel and expense files:** one file is easier to produce and to filter, and it is the shape a spreadsheet user would build. Columns that do not apply to a type are left empty.
- **Why `derived`, `source`, `source_ref` are in the standard file:** without them standard export → import would not be exact. They are optional and documented as "leave empty"; people converting by hand never need them.
- **Backup tables** (only inside the full backup, D7):
  - `vehicles.csv`: `name`, `make`, `model`, `plate`, `fuel_type`, `initial_odometer_km`, `archived`, `notes`.
  - `stations.csv`: `name`, `location`, `brand`. All stations are listed, including those with no refuels.
  - Records refer to vehicles by `name` and to stations by (`station`, `station_location`).
- **Alternatives considered:**
  - Separate refuel and expense files. Rejected: two schemas to learn instead of one.
  - Unitless column names with units only in the docs. Rejected: easy to misread in a spreadsheet.
  - Ids instead of names for vehicle and station references. Rejected: not something a person converting by hand can fill in.

### D2. One code-level definition of the standard format

`src/glovebox/standard.py` holds frozen dataclasses:
- `StandardField`: `name`, `type` (`string`, `number`, `date`, `time`, `boolean`, `enum`), `unit`, `applies_to`, `required` (`always`, `refuel`, `expense`, `no`, plus a rule text for the "two of three" and "both or neither" cases), `enum` values, `default`, `export_decimals`, `description`, `example`.
- Three tuples, `RECORD_FIELDS`, `VEHICLE_FIELDS` and `STATION_FIELDS`.
- `EXAMPLE_RECORDS`: one refuel and one expense, used for the docs example.
- `datapackage(meta: dict | None) -> dict`, which builds the machine-readable descriptor (D3).

Everything else reads these definitions: the engine's list of mapping targets, the export column order, the standard preset's checks, the docs generator, the backup descriptor. Nothing else lists the columns.

### D3. Machine-readable description: Table Schema inside a Data Package descriptor

- **Evaluated:**
  - **Table Schema / Data Package**: a JSON description of a CSV's fields (`name`, `type`, `format`, `description`, `example`, `constraints.required`, `constraints.enum`, `trueValues`/`falseValues`, `missingValues`, `decimalChar`, `groupChar`). A Data Package lists several CSV resources with their schemas. Simple JSON, readable by hand, with validators available in several languages for people who want them.
  - **CSV on the Web (W3C)**: more expressive (JSON-LD metadata, URI templates, RDF conversion) but heavier, and its extra power (linked data) is not needed here.
- **Decision:** generate a Data Package descriptor with one Table Schema per table (`records`, `vehicles`, `stations`), using the standard's own property names.
  - Units go into the field `description`, plus a `unit` custom property. The standard allows extra properties on descriptors. Verify this, and the exact v1/v2 property names, against the current published standard at implementation time.
  - Conditional rules ("two of three", "applies to refuels") cannot be expressed in Table Schema; they are stated in `description`, and only always-required columns get `constraints.required`.
- **No dependency:** the descriptor is plain JSON built with `json` from the stdlib. The validation library is not added, not even as a dev dependency. Tests check the descriptor's structure directly.
- **Where it appears:**
  - `docs/user/standard-format.datapackage.json` (committed, generated, published with the docs site);
  - as `datapackage.json` in every full backup ZIP, with a `glovebox` property added (app version, schema version, export time, currency);
  - as a download link on the export page.

### D4. Presets are TOML files with one table mapping

A preset describes one CSV table (one section of a multi-table file). Example, the shipped `fuelly-metric.toml`:

```toml
name = "Fuelly (metric)"
note = "Fuelly import-format CSV with litres. Based on public descriptions of the format."
verified = false          # true only when checked against a real file
export = true             # offered on the export page
split_by_vehicle = true   # export: one file per vehicle; import: file has no vehicle column

[format]
date_format = "auto"      # or a strftime pattern such as "%d.%m.%Y %H:%M"
decimal_char = "auto"     # ".", "," or "auto"
group_char = ""           # thousands separator: "", ",", ".", " ", "'"
distance_unit = "km"      # km | mi | auto | ask
volume_unit = "l"         # l | gal_us | gal_uk | auto | ask

[fields]
type = { value = "refuel" }
date = { column = "fuelup_date" }
odometer_km = { column = ["odometer", "km"] }
fuel_l = { column = ["litres", "liters"] }
price_per_l = { column = "price" }
full = { column = "partial_fuelup", true_values = ["0"], false_values = ["1"] }
missed_previous = { column = "missed_fuelup", true_values = ["1"], false_values = ["0"] }
notes = { column = "notes" }
station = { column = "tags" }
```

- **Top-level keys:** `name`, `note`, `verified`, `export`, `split_by_vehicle`.
- **`[file]`** (optional): `encoding`, `delimiter`, `header_row`, `section`. Unset means auto-detect (D6).
- **`[format]`**: the keys shown above, with defaults `auto`, `auto`, `""`, `auto`, `auto`.
  - `auto` units come from a unit in parentheses in the matched header, e.g. `Odo (km)`, `Fuel (US gal)`. If the header has none, the preview asks (same as `ask`).
  - Units apply to `odometer_km`, `fuel_l` and `price_per_l` (price per source volume unit).
- **`[fields.<standard field>]`**: exactly one of `column` (a header name, or a list of candidates tried in order) or `value` (a constant). Optional keys:
  - `map`: `{ <target value> = [source values] }`, compared case- and whitespace-insensitively. Used for `type`, `category` and any enum field.
  - `true_values` / `false_values`: for boolean fields.
  - `missing_values`: values that count as empty, e.g. `["0"]` where an app writes 0 for "not given".
  - `default`: used when the cell is empty, or when a value is not listed in `map` or in `true_values`/`false_values`. Without `default`, an empty cell takes the standard field's default and an unlisted value is a row error.
  - The same source column may feed several fields, e.g. `title` and `category`.
- **`[[skip_rows]]`**: `column` and `values`. Rows whose cell matches are skipped and counted.
- **Header matching:** case- and whitespace-insensitive. A trailing `(...)` is ignored on both sides unless the candidate itself contains one, so `Odo` matches `Odo (km)` but `Price (optional)` only matches itself.
- **One table per preset** keeps the file format and engine simple. A multi-table source (Fuelio) gets one preset per section, and the user imports the same file once per preset. Duplicate detection makes this safe.
- **Ids:** a shipped preset's id is its file stem (e.g. `fuelly-metric`); a user preset's id is `user-<slug of name>`. The id is stored as `import_batch.format` and as the records' `source`.
- **Validation:** `importers/presets.py` holds one table of allowed keys (key, type, allowed values, description). It drives the loader's validation and the generated `docs/user/presets.md`. Unknown keys, unknown target fields and invalid values are errors with the key path, e.g. `fields.full.true_values: expected a list of strings`.
- **Reading and writing:** `tomllib` (stdlib) reads presets. Writing user presets uses a small writer in `presets.py` for this fixed shape. Strings are written as TOML basic strings, and a test checks that every saved preset reads back equal. TOML is chosen over JSON because hand-written presets need comments.
- **Alternatives considered:**
  - Keep the alias tables and add a mapping UI on top. Rejected: two mechanisms for one job.
  - A preset with several tables. Rejected: it only serves Fuelio, and it doubles the file format.
  - A TOML writer dependency. Rejected for now: the shape is fixed and small (see Q3).

### D5. Shipped presets

They live in `src/glovebox/presets/`, one file per preset, each with a comment header that says where its knowledge comes from.

| Id | Converted from | Verified | Export |
|---|---|---|---|
| `glovebox` | the standard definition (identity mapping, fixed formats: `.` decimal, ISO dates, km, l) | yes (round-trip tests) | yes |
| `fuelly-metric` | `aliases/fuelly.toml` `[import]`, litres | no | yes (replaces `exporters/fuelly.py`) |
| `fuelly-us` | same, gallons and miles | no | no |
| `fuelly-website` | `[export]` section; units `ask`; note: no partial/missed flags, all fills are full | no | no |
| `fuelio-fillups` | `fuelio.toml` `[log]`, `section = "Log"`, units `auto`, `Full` with `false_values = ["0"]` and `default = true`, prices with `missing_values = ["0"]` | no | no |
| `fuelio-costs` | `[costs]`, `section = "Costs"`, skip `isTemplate`/`isIncome` = 1, category mapped from `CostTitle` | no | no |
| `drivvo-refuelling`, `drivvo-services`, `drivvo-expenses` | `drivvo.toml`; `type` and the default category as constants | no; note "Best effort, untested: not checked against a real export" | no |

A test loads every shipped preset, and each existing fixture imports through its preset with the same expected values as the v1 tests.

### D6. The import engine

`importers/engine.py`, pure (no database):

```python
read_file(data: bytes, preset: Preset | None) -> SourceFile
    # tables (one per CSV, or one per ZIP member), detected encoding, delimiter, header row
score(preset: Preset, source: SourceFile) -> float
apply(preset: Preset, source: SourceFile, answers: Answers) -> ImportResult
```

- **Reading:**
  - **Encoding:** UTF-8 with or without BOM, then cp1252 (the v1 helper).
  - **Delimiter:** sniffed among `,` `;` tab from the header row.
  - **ZIP upload:** every `.csv` member is a table, and the member's file stem serves as the default vehicle name when the preset has no `vehicle` field. A ZIP with `datapackage.json` is a full backup, and `vehicles.csv` / `stations.csv` members are companion tables (D7).
  - **Sections:** if the preset names a `section`, only the lines after `## <section>` (quoted or not) up to the next `## ` line are read.
  - **Header row:** the first row, within the first 20 non-blank rows, that contains the most of the preset's candidate headers. Without a preset, the first non-blank row. The user can override it.
- **Detection:**
  - Each preset (user presets first, then shipped, in a fixed order) is scored as the fraction of its `column` fields whose header is found. A preset scores 0 if its `date` column or its `section` is missing.
  - The best score above 0.5 is pre-selected. Otherwise the mapping starts from the standard preset, with only the columns whose headers match standard names exactly assigned.
- **Applying:**
  - **Per row:** skip rules → per field: cell or constant → missing values → map or booleans → parse with the value formats → unit conversion → storage units → `CanonicalRefuel` / `CanonicalExpense` (kept from `base.py`).
  - **Numbers are strict:** with `group_char = ""`, a `,` in a `.`-decimal number is a row error, not a silently dropped separator. `decimal_char = "auto"` uses the v1 per-column detection.
  - **`date_format = "auto"`** uses the v1 date-order detection. An ambiguous file asks day-first or month-first.
  - **Row errors** carry the file line number, the target field, the raw value and a message. The row is skipped.
  - **Blocking errors:** an unmapped required field (`type`, `date`; for refuels `odometer_km`; for expenses `total` and `title`) and unanswered questions block the preview.
- **`ImportResult` changes:** `row_errors: list[RowError]` replaces the "Row N skipped" warnings, and `questions` replaces `ambiguities`. The latter keep the same two kinds: date order and units. `header_mismatch` goes: an unmatched file now opens the mapping editor instead of failing.
- **Pipeline:** `preview_import` and `commit_import` take a `Preset` (shipped, user, or edited in the form) and `Answers` instead of `format` and `ImportOptions`. `_map_and_dedupe` and `_write` stay as they are. The `getattr` extras for native records are replaced by explicit optional fields on the canonical records (`station_location`, `derived`, `source`).
- **Removed:** the `ImporterAdapter` protocol, `AliasTable`, `load_aliases`, `HeaderMismatch`, the four adapter modules and `importers/aliases/`.
- **Alternative considered:** keep adapters for "special" formats (Fuelio sections, the native ZIP). Rejected: sections are a small generic feature, and the backup is now the standard format.

### D7. Full backup replaces the native ZIP

- **Contents:** `records.csv` (the standard format, all fields), `vehicles.csv`, `stations.csv`, `datapackage.json` (D3, with the `glovebox` metadata).
- **Restore** goes through the same pipeline, and is the general "companion tables" import plus `datapackage.json`:
  - any ZIP may hold `vehicles.csv` and/or `stations.csv` next to the records (a ZIP member counts as one when its stem is `vehicles` or `stations`, it has a `name` column and no `date` column); they are read without the preset, because their layout is fixed;
  - a missing vehicle or station is created with its details; an existing one (vehicle by name, station by name and location) only has empty details filled, so a normal import can never overwrite what the user entered. The preview lists both, and undo removes created stations but does not revert filled details;
  - the vehicle mapping is still offered, and a fill goes to whichever existing vehicle the name resolves to;
  - `datapackage.json` only changes two things: the records are read with the `glovebox` preset whatever preset was chosen (so the upload skips the mapping step), and a missing `records.csv` is an error;
  - `derived` and `source` are restored as written.
- **Why replace rather than keep the native ZIP:**
  - one format to define, document and test instead of two;
  - the backup is readable with the same docs as the CSV;
  - the native ZIP's ids carried no information that names do not.
  - HA add-on backups of `/data` remain the exact-state backup, so nothing is lost operationally.
- **What is not kept:** database ids, `created_at`, and the import batch link (restored records belong to the restore batch). v1 did not keep these on restore either.
- **Known limit:** vehicle names are unique only among active vehicles. If an archived vehicle shares its name with another exported vehicle, the export appends ` (archived)` (then ` (2)`, ...) to the archived one's name and the export page says so. This is the one case where a restore is not identical.

### D8. Export through presets

- **Preset rules:** a preset is exportable when `export = true` and it has no `skip_rows`.
  - Columns are written in the order of `[fields]`. A `column` list writes its first entry; `map` and booleans write the first listed source value; `missing_values` and `default` are ignored.
  - A constant `type` value filters the export to that type (Fuelly: refuels only). Other constants are not written.
  - `split_by_vehicle = true` writes one CSV per vehicle, zipped if there is more than one.
  - Values are converted to the preset's units.
- **Export page:**
  - Choices: a preset (standard, Fuelly (metric), or the user's exportable presets) and the vehicles.
  - **Customise:** include/exclude and rename each standard column, delimiter, decimal character, date pattern, distance and volume unit. The result can be saved as a user preset; it is the same object the import editor saves.
  - The page offers the full backup and the format description download.
- **Fuelly-compatible output stays byte-compatible with v1:** the existing v1 scenarios (`2026-05-02,98000,20.500,1.459,1,0,,OMV Celje`) are kept as tests.
- **Module:** `exporters/csv_export.py` (`export_csv(session, settings, preset, vehicle_ids) -> tuple[bytes, str]`, returning the content and the media type). `exporters/backup.py` (`export_backup(...) -> bytes`) re-uses it with the `glovebox` preset.

### D9. What the Fuelio and Drivvo presets lose

Lookups across sections and combined columns are left out (see Non-Goals). The Fuelio presets therefore no longer:
- take the station name from `## FavStations` (they use `City (optional)`);
- take the vehicle name from `## Vehicle` (the user picks or creates the vehicle; in a ZIP the member name is proposed);
- resolve `CostTypeID` through `## CostCategories` (category is mapped from `CostTitle`, default `other`);
- join the cost title into the notes.

The cost of this is small: Fuelio is not the user's own app and its format was never checked against a real file.

### D10. User presets are stored in the database

- **Table:** `preset` (`id`, `slug` unique, `name`, `body` TOML text, `created_at`, `updated_at`).
- **Why the database:** it is already in `/data` and in HA backups, and Alembic manages it. Add-on users cannot reach files under `/data` easily anyway.
- **Stored as TOML text,** so a download gives back exactly the file format the user can hand-edit, and an upload is validated with the same loader.
- **Management page:** list, download, upload, delete. A name that clashes with an existing preset is rejected with a message.
- **Migration `0003`:** creates `preset` and widens `import_batch.format`, `refuel.source` and `expense.source` from 20 to 50 characters.

### D11. Generated documentation

- **`src/glovebox/formatdocs.py`** renders, from `standard.py` and the preset key table:
  - `docs/user/standard-format.md`: conventions, one table per CSV (name, type, unit, required, description, example), an example `records.csv` built from `EXAMPLE_RECORDS`, and a short "convert your own export" section (spreadsheet steps and a ten-line Python example using only `csv`);
  - `docs/user/standard-format.datapackage.json`;
  - `docs/user/presets.md`: every preset key with type, allowed values and description, plus a table of shipped presets (id, name, verified, export, note) read from the shipped files.
- **Run:** `uv run python -m glovebox.formatdocs` writes the files. `--check` exits non-zero if they differ.
- **Tests:**
  - `tests/test_format_docs.py` fails when the committed files differ from the rendered output, with a message that names the command to run.
  - The example CSV in the docs is imported through the `glovebox` preset in a test, so the docs example is always valid.
- **Hand-written docs** (`import.md`, `export.md`) describe the UI flow and link to the generated pages. They do not repeat column lists.
- **Alternative considered:** an mkdocs plugin that renders at build time. Rejected: it adds a docs dependency, and the committed files would not be readable on GitHub.

### D12. Module layout and parallel-work boundaries

```text
src/glovebox/
  standard.py              # D2 definitions + datapackage()        (frozen after group 1)
  formatdocs.py            # D11 generator
  presets/*.toml           # D5 shipped presets
  importers/
    base.py                # canonical records, RowError, Question, Answers, locale helpers
    presets.py             # Preset model, key table, load/validate/write, shipped + user CRUD   (frozen after group 1)
    engine.py              # D6 read/score/apply
    pipeline.py            # preview/commit/undo with Preset + Answers
  exporters/csv_export.py, exporters/backup.py
  web/imports.py, web/exports.py, web/presets.py, templates/import/*, templates/export.html, templates/presets/*
  migrations/versions/0003_presets.py
```

## Risks / Trade-offs

- [Shipped Fuelly/Fuelio/Drivvo presets are wrong for real files] → They are marked unverified or untested, the preview shows the preset note, and the user fixes the mapping in the editor and saves it. Correcting a preset is a data change.
- [Fuelio users import twice (fill-ups, costs)] → The import page says so after the first commit when the file has a `## Costs` section. Duplicate detection makes a repeat harmless.
- [Strict number parsing rejects files v1 accepted silently] → The row errors name the value and the setting to change. v1's behaviour (dropping a stray `,`) could corrupt values, so strictness is the safer default.
- [Generated docs drift from hand-written docs] → Hand-written pages link to the generated ones instead of repeating columns.
- [The Table Schema details (v1 vs v2 property names, custom properties) are taken from memory] → Verify against the published standard during task 1.2 and pin the profile in the descriptor.
- [Unit conversion on export is not exact on round trip] → Documented; only the standard preset (metric) promises an exact round trip.
- [Vehicle name collision with archived vehicles in the backup] → See D7. Rare, visible, and documented.

## Migration Plan

- **Database:** migration `0003` runs at startup (new table, widened columns). There is no data conversion; existing `source` values (`drivvo`, `fuelio`, `fuelly`, `native`, `manual`) stay valid as free text.
- **Files:** v1 native ZIPs cannot be imported after the upgrade (unless Q1 decides otherwise). The CHANGELOG and the release notes tell users to make a new full backup after upgrading. The database itself is untouched, so no user data is at risk.
- **Rollback:** downgrading the add-on restores the v1 code. The migration's downgrade drops `preset` and narrows the columns (values longer than 20 characters are truncated; only user-preset ids can be that long).

## Open Questions

- **Q1. v1 native ZIP import.** Drop it (recommended: v1 was used briefly, the database migrates in place, and keeping it means keeping a second format), or keep a read-only legacy reader for one release?
- **Q2. Fuelio as two presets without lookups (D9),** or a multi-table preset with cross-section lookups? Recommended: two presets; Fuelio is not the user's app.
- **Q3. TOML writer:** a small in-house writer for the fixed preset shape (recommended; no dependency, round-trip tested), or the small, pure-Python `tomli-w` package as one new runtime dependency?
- **Q4. Rows with errors:** skip them and commit the rest, as v1 does (recommended, the counts are in the preview), or block the commit until the file is clean?
