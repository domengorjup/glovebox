## MODIFIED Requirements

### Requirement: Fuelly-compatible export
The system SHALL export refuellings with the shipped "Fuelly (metric)" preset in the Fuelly import format, one CSV per vehicle (zipped if more than one), with header `fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags`. In it:
- `price` SHALL be the price per litre;
- the fill flags SHALL be `0` or `1`;
- the station name SHALL be written to `tags` (the "Fuelly (metric)" import preset reads it back as the station, see data-import).

Expenses SHALL NOT be included, and the UI SHALL say so.

#### Scenario: Fuelly export row
- **WHEN** a partial refuel of 20.5 L at 1.459 €/L at station "OMV Celje" on 2026-05-02 at 98000 km is exported
- **THEN** the row reads `2026-05-02,98000,20.500,1.459,1,0,,OMV Celje`

#### Scenario: Fuelly column names
- **WHEN** the export header is read
- **THEN** the columns are exactly `fuelup_date`, `odometer`, `litres`, `price`, `partial_fuelup`, `missed_fuelup`, `notes`, `tags`, in that order

## REMOVED Requirements

### Requirement: Native full export
**Reason**: Replaced by a full backup built from the standard format, so there is one documented format instead of two.
**Migration**: Use "Full backup". It contains the standard `records.csv` plus `vehicles.csv`, `stations.csv` and `datapackage.json`.

## ADDED Requirements

### Requirement: Standard CSV export
The system SHALL export the records of all vehicles, or of selected vehicles, as one CSV in the standard format (see standard-format), with all standard columns.

#### Scenario: Both record types in one file
- **WHEN** a vehicle has 3 refuels and 2 expenses and its records are exported in the standard format
- **THEN** the file has a header row and 5 data rows, 3 with `type` "refuel" and 2 with `type` "expense"

### Requirement: Full backup
The system SHALL export all data, or selected vehicles, as a ZIP containing:
- `records.csv` (the standard format);
- `vehicles.csv` and `stations.csv` (the standard backup tables);
- `datapackage.json`: the format descriptor (see standard-format), extended with the app version, schema version, export time and currency.

Every stored record SHALL appear exactly once. With a vehicle selection, only stations used by the exported refuels SHALL be included. If two exported vehicles share a name, the archived one SHALL get a distinguishing suffix and the export page SHALL say so.

#### Scenario: Backup contents
- **WHEN** the user makes a full backup of all data
- **THEN** the ZIP contains the three CSVs and `datapackage.json`
- **AND** every stored refuel and expense appears exactly once in `records.csv`

#### Scenario: Descriptor carries metadata
- **WHEN** a full backup is made with app currency EUR
- **THEN** `datapackage.json` contains the app version, the schema version, the export time and the currency "EUR"

### Requirement: Preset-driven export with custom columns and format options
The export page SHALL offer every preset that is usable for export: shipped presets marked for export, and user presets that are marked for export and have no skip rules. For each such preset:
- columns SHALL be written in the preset's field order;
- a value map or boolean list SHALL write its first listed source value;
- a constant `type` SHALL limit the export to that record type;
- values SHALL be converted to the preset's units.

The user SHALL be able to customise an export:
- choose which standard columns to include and rename their headers;
- set the delimiter, decimal separator, date pattern, distance unit and volume unit;
- save the result as an own preset that can then also be used for import.

#### Scenario: Custom semicolon export
- **WHEN** the user customises an export with delimiter ";", decimal separator "," and only the columns `date`, `fuel_l`, `total`
- **THEN** a refuel of 45.2 L, total 65.95 on 2026-05-02 is written as `2026-05-02;45,200;65,95`

#### Scenario: Export in miles
- **WHEN** a custom export sets the distance unit to miles
- **THEN** an odometer of 160.9344 km is written as 100
