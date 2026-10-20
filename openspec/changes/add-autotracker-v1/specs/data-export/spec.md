## ADDED Requirements

### Requirement: Native full export
The system SHALL export all data, or a selected vehicle, as a ZIP containing `vehicles.csv`, `stations.csv`, `refuels.csv`, `expenses.csv` and `manifest.json`. The manifest SHALL hold the app version, schema version, export timestamp and currency. The CSVs SHALL be UTF-8, comma-delimited, with ISO 8601 dates and `.` as decimal separator.

#### Scenario: Export contents
- **WHEN** the user exports all data
- **THEN** the ZIP contains the four CSVs and the manifest
- **AND** every stored record appears exactly once

### Requirement: Fuelly-compatible export
The system SHALL export refuellings in the Fuelly import format, one CSV per vehicle (zipped if more than one), with header `fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags`. In it:
- `price` SHALL be the price per litre;
- the fill flags SHALL be `0` or `1`;
- the station name SHALL be included in `tags` (the Fuelly importer reads it back as the station, see data-import).

Expenses SHALL NOT be included, and the UI SHALL say so.

#### Scenario: Fuelly export row
- **WHEN** a partial refuel of 20.5 L at 1.459 €/L at station "OMV Celje" on 2026-05-02 at 98000 km is exported
- **THEN** the row reads `2026-05-02,98000,20.500,1.459,1,0,,OMV Celje`

#### Scenario: Readable by LubeLogger header mapping
- **WHEN** the export header is checked against LubeLogger's documented import aliases
- **THEN** each of `fuelup_date`, `odometer`, `litres`, `price`, `partial_fuelup`, `missed_fuelup`, `notes`, `tags` is a recognised alias
