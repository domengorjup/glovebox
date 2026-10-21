# standard-format Specification

## Purpose
TBD - created by archiving change configurable-csv-import-export. Update Purpose after archive.
## Requirements
### Requirement: Standard records format
The system SHALL define a standard CSV format for records with one row per refuel or expense and these columns, in this order:
`type`, `vehicle`, `date`, `time`, `odometer_km`, `fuel_l`, `price_per_l`, `total`, `currency`, `full`, `missed_previous`, `station`, `station_location`, `station_brand`, `category`, `title`, `coverage_start`, `coverage_end`, `notes`, `derived`, `source`, `source_ref`.

- **File conventions:**
  - RFC 4180 CSV: comma delimiter, `"` quoting, CRLF line ends, one header row.
  - UTF-8: written without BOM; a BOM SHALL be accepted on import.
- **Value conventions:**
  - Dates `YYYY-MM-DD`; times `HH:MM` (`HH:MM:SS` accepted on import).
  - Dot as decimal separator, no thousands separator.
  - Booleans `true` or `false`; an empty cell means no value.
- **Units and money:** distances in km, volumes in litres, money as a decimal number in the currency named by `currency`. The unit SHALL be part of the column name where the column has one.
- **Per-type rules:**
  - `type` is `refuel` or `expense`. `vehicle`, `date` and `type` are required on every row.
  - A refuel requires `odometer_km` and at least two of `fuel_l`, `price_per_l` and `total`.
  - An expense requires `title` and a positive `total`. `category` is one of `maintenance`, `insurance`, `registration`, `other` and defaults to `other`. `coverage_start` and `coverage_end` are set both or neither.
  - Columns that do not apply to a row's type SHALL be empty.
- **`currency`:** a non-empty value that differs from the app currency SHALL make that row an error on import.
- **Export precision:** `fuel_l` and `price_per_l` with 3 decimals, `total` with 2 decimals, `odometer_km` without trailing zeros.

#### Scenario: Refuel row
- **WHEN** a full refuel of 45.2 L at 1.459 EUR/L, total 65.95, at 98000 km on 2026-05-02 at station "OMV Celje" for vehicle "Golf" is exported in the standard format
- **THEN** its row has `type` "refuel", `vehicle` "Golf", `date` "2026-05-02", `odometer_km` "98000", `fuel_l` "45.200", `price_per_l` "1.459", `total` "65.95", `currency` "EUR", `full` "true", `station` "OMV Celje"
- **AND** the expense-only columns are empty

#### Scenario: Wrong currency
- **WHEN** a standard file row has `currency` "USD" and the app currency is EUR
- **THEN** the preview lists that row as an error and it is not imported

### Requirement: Lossless standard round trip
Exporting all records in the standard format and importing that file into an empty database with the standard preset SHALL recreate every refuel and expense with identical values, including `derived` and `source`. The vehicles and stations SHALL be recreated by name, and stations also by location.

#### Scenario: Round trip
- **WHEN** all records are exported in the standard format, imported into an empty database with the standard preset, and exported again
- **THEN** the two standard files are identical

### Requirement: Backup tables
The standard format SHALL also define `vehicles.csv` (`name`, `make`, `model`, `plate`, `fuel_type`, `initial_odometer_km`, `archived`, `notes`) and `stations.csv` (`name`, `location`, `brand`), with the same file and value conventions. Records SHALL refer to vehicles by name and to stations by name and location.

#### Scenario: Unused station listed
- **WHEN** a station has no refuels and a full backup is made
- **THEN** `stations.csv` contains it

### Requirement: Single definition of the standard format
The standard format SHALL be defined once in code. For each field the definition SHALL give the name, type, unit, which record types it applies to, whether it is required, the default, allowed values, the export precision, a description and an example. The import mapping targets, the export columns, the generated documentation and the machine-readable description SHALL all be derived from this definition.

#### Scenario: New field appears everywhere
- **WHEN** a field is added to the definition and the documentation is regenerated
- **THEN** it appears as a mapping target, as an export column, in the user docs page and in the machine-readable description

### Requirement: Generated format documentation
A command (`uv run python -m glovebox.formatdocs`) SHALL generate, from the definition:
- `docs/user/standard-format.md`: the conventions, a table per CSV (name, type, unit, required, description, example), an example records file, and instructions for converting another export with a spreadsheet or a short script;
- `docs/user/standard-format.datapackage.json`: a Data Package descriptor with a Table Schema for each of the three tables;
- `docs/user/presets.md`: every preset key (type, allowed values, description) and the list of shipped presets with their verified status and note.

#### Scenario: Example in the docs is valid
- **WHEN** the example records file from the generated docs page is imported with the standard preset
- **THEN** the preview shows no errors and the expected numbers of refuels and expenses

#### Scenario: Descriptor fields match the definition
- **WHEN** the generated Data Package descriptor is read
- **THEN** its `records` schema lists exactly the standard record columns in order, with types, `description` and `example`, and `constraints.required` set only on `type`, `vehicle` and `date`

### Requirement: Stale documentation fails the tests
The test suite SHALL fail when the committed generated files differ from what the generator produces now. The failure message SHALL name the command that regenerates them.

#### Scenario: Definition changed without regenerating
- **WHEN** a field description is changed in code and the generated docs are not regenerated
- **THEN** the test suite fails, naming `uv run python -m glovebox.formatdocs`

