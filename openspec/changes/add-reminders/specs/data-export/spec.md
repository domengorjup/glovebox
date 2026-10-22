## MODIFIED Requirements

### Requirement: Full backup
The system SHALL export all data, or selected vehicles, as a ZIP containing:
- `records.csv` (the standard format);
- `vehicles.csv`, `stations.csv` and `reminders.csv` (the standard backup tables);
- `datapackage.json`: the format descriptor (see standard-format), extended with the app version, schema version, export time and currency.

Every stored record and every reminder of the exported vehicles SHALL appear exactly once. `reminders.csv` SHALL be present with only its header row when there are no reminders. With a vehicle selection, only stations used by the exported refuels SHALL be included. If two exported vehicles share a name, the archived one SHALL get a distinguishing suffix and the export page SHALL say so.

#### Scenario: Backup contents
- **WHEN** the user makes a full backup of all data
- **THEN** the ZIP contains the four CSVs and `datapackage.json`
- **AND** every stored refuel and expense appears exactly once in `records.csv`
- **AND** every reminder, open or done, appears exactly once in `reminders.csv`

#### Scenario: Descriptor carries metadata
- **WHEN** a full backup is made with app currency EUR
- **THEN** `datapackage.json` contains the app version, the schema version, the export time and the currency "EUR"
