## ADDED Requirements

### Requirement: Import with preview and explicit commit
The system SHALL import a file in two steps.
- **Preview:** shows the detected format, record counts per type, vehicles found in the file, duplicates, warnings and errors, and changes no data.
- **Commit:** writes the records only after the user confirms.

All records of one commit SHALL be written in a single transaction and tagged with an import batch, so that the batch can later be undone.

#### Scenario: Preview does not write
- **WHEN** the user uploads a file and stops at the preview
- **THEN** no records are added

#### Scenario: Undo an import batch
- **WHEN** the user undoes an import batch
- **THEN** all records created by that batch are deleted
- **AND** stations created only by that batch are deleted as well

### Requirement: Format detection
The system SHALL detect the format of an uploaded file (Drivvo, Fuelio, Fuelly, native) from its content. The user SHALL be able to override the detected format.

#### Scenario: Detect Fuelio backup
- **WHEN** the uploaded file contains a line starting with `## Log` (quoted or not)
- **THEN** it is detected as Fuelio

### Requirement: Vehicle mapping
The preview SHALL list each vehicle name found in the file and let the user map it to an existing vehicle or create a new one. A file without vehicle names, such as a single-vehicle export, SHALL require choosing a target vehicle.

#### Scenario: Map imported vehicle to existing one
- **WHEN** a file contains vehicle "My Golf" and the user maps it to existing vehicle "Golf"
- **THEN** the committed records reference "Golf"

### Requirement: Locale-tolerant parsing
Importers SHALL handle the following:
- **Encoding:** UTF-8 with or without BOM, falling back to cp1252.
- **Delimiters:** `,`, `;` and tab.
- **Number formats:** decimal comma or point, with or without thousands separators.
- **Dates:** multiple formats. When a file's dates are ambiguous between day-first and month-first, the preview SHALL ask the user to choose.

Header names SHALL be matched through per-format alias tables, case- and whitespace-insensitively. If required headers are missing, the preview SHALL list the headers found and the headers expected, and SHALL NOT import.

#### Scenario: Decimal comma
- **WHEN** a semicolon-delimited file contains litres "45,20" and total "65,95"
- **THEN** they are parsed as 45.20 and 65.95

#### Scenario: Ambiguous dates
- **WHEN** every date in a file is consistent with both DD/MM/YYYY and MM/DD/YYYY
- **THEN** the preview asks the user which order to use

#### Scenario: Unknown headers reported
- **WHEN** a Drivvo file has headers that match no alias
- **THEN** the preview fails with the list of found and expected headers

### Requirement: Duplicate detection
The system SHALL skip records that duplicate existing ones and SHALL count them in the preview.
- **Refuels:** same vehicle, date, odometer and litres rounded to 0.01.
- **Expenses:** same vehicle, date, category and amount.

#### Scenario: Re-import is a no-op
- **WHEN** the user imports the same file twice
- **THEN** the second preview reports every record as a duplicate
- **AND** the second commit adds nothing

### Requirement: Fuelio import
The system SHALL import Fuelio CSV backups (a single CSV, or a ZIP containing one CSV per vehicle).

The `## Log` section SHALL map as follows:
- **Date:** `Data` (date and time).
- **Odometer:** the column whose header starts with `Odo`, converted to km if the header names miles.
- **Litres:** the column whose header starts with `Fuel`, converted to litres if the header names gallons.
- **Fill flags:** `Full` (`0` = partial, any other value = full) and `Missed`.
- **Prices:** `VolumePrice` is the price per litre; `Price (optional)` is the total.
- **Station name:** from `City (optional)`; when `StationID (optional)` references `## FavStations`, its `NameBrand` takes precedence.
- **Notes:** from `Notes (optional)`.

The `## Costs` section SHALL be imported as expenses. Each category SHALL be resolved through `## CostCategories` and mapped to our categories by an alias table, keeping the Fuelio category name in the title. Rows flagged as template or income, and rows with cost ≤ 0, SHALL be skipped.

#### Scenario: Total versus per-litre price
- **WHEN** a Fuelio log row has `Fuel (litres)` 72.604, `Price (optional)` 3000.0 and `VolumePrice` 41.32
- **THEN** the refuel is stored with total 3000.00 and price per litre 41.320

#### Scenario: Template cost skipped
- **WHEN** a `## Costs` row has `isTemplate` 1
- **THEN** it is not imported

### Requirement: Fuelly import
The system SHALL import Fuelly CSV files in the fuelly.com import format and in the fuelly.com export format. The format SHALL be detected by its headers. Miles and gallons SHALL be converted to km and litres. When a file's units cannot be determined from its headers, the preview SHALL ask the user.
- **Import format:** `fuelup_date`, `odometer`, `litres`/`gallons`, `price`, `partial_fuelup`, `missed_fuelup`, `notes`, `tags`.
- **Export format:** `Name`, `Model`, `MPG`, `Odometer`, `Miles`, `Gallons`, `Price`, `Fuelup Date`, `Date Added`, `Tags`, `Notes`.

#### Scenario: Fuelly partial and missed flags
- **WHEN** a Fuelly import-format row has `partial_fuelup` 1 and `missed_fuelup` 0
- **THEN** the refuel is stored with is_full false and missed_previous false

#### Scenario: Gallons converted
- **WHEN** a Fuelly row has `gallons` 10.000 and `price` 3.500 (per gallon)
- **THEN** the refuel stores 37.854 L and price per litre 0.925

### Requirement: Drivvo import
The system SHALL import Drivvo CSV exports of refuelling, service and expense records. English SHALL be the first and default locale of the Drivvo alias table. Until a real Drivvo export has been checked, the English mapping is PROVISIONAL and SHALL be marked as such in the alias file. Finalising it SHALL use at least one real export, anonymised into a test fixture. Aliases for further languages SHALL be addable as data, without changing code.

#### Scenario: Provisional English mapping
- **WHEN** the user imports a hand-made file using the provisional English Drivvo headers
- **THEN** its rows are imported through the shared pipeline with preview and duplicate detection

#### Scenario: Drivvo refuelling export (blocked on real sample)
- **WHEN** the user imports an anonymised fixture of a real Drivvo refuelling export
- **THEN** every refuel row is imported with date, odometer, litres, price per litre, total and station matching the fixture's expected values

### Requirement: Native import
The system SHALL import the native export ZIP (see data-export) and restore its vehicles, stations, refuels and expenses with identical values.

#### Scenario: Round trip
- **WHEN** data is exported natively and imported into an empty database
- **THEN** a second native export is identical to the first, apart from the export timestamp
