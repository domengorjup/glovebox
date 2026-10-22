## MODIFIED Requirements

### Requirement: Backup tables
The standard format SHALL also define `vehicles.csv` (`name`, `make`, `model`, `plate`, `fuel_type`, `initial_odometer_km`, `archived`, `notes`), `stations.csv` (`name`, `location`, `brand`) and `reminders.csv` (`uid`, `vehicle`, `title`, `category`, `due_date`, `lead_days`, `status`, `done_date`, `vehicle_field`, `notes`), with the same file and value conventions. Records and reminders SHALL refer to vehicles by name, and records to stations by name and location. In `reminders.csv`:
- `category` SHALL be one of the expense categories;
- `status` SHALL be `open` or `done`;
- `done_date` SHALL be set only for done reminders;
- `vehicle_field` SHALL be empty or the name of the vehicle date the reminder follows.

The link to an expense and the calendar sync state SHALL NOT be part of the table.

#### Scenario: Unused station listed
- **WHEN** a station has no refuels and a full backup is made
- **THEN** `stations.csv` contains it

#### Scenario: Reminder row
- **WHEN** an open reminder "Registration" for "Golf", category registration, due 2027-03-01, 14 days before, is backed up
- **THEN** its `reminders.csv` row has its uid, `vehicle` "Golf", `due_date` "2027-03-01", `lead_days` "14", `status` "open" and an empty `done_date`

### Requirement: Generated format documentation
A command (`uv run python -m glovebox.formatdocs`) SHALL generate, from the definition:
- `docs/user/standard-format.md`: the conventions, a table per CSV (name, type, unit, required, description, example), an example records file, and instructions for converting another export with a spreadsheet or a short script;
- `docs/user/standard-format.datapackage.json`: a Data Package descriptor with a Table Schema for each of the four tables (records, vehicles, stations, reminders);
- `docs/user/presets.md`: every preset key (type, allowed values, description) and the list of shipped presets with their verified status and note.

#### Scenario: Example in the docs is valid
- **WHEN** the example records file from the generated docs page is imported with the standard preset
- **THEN** the preview shows no errors and the expected numbers of refuels and expenses

#### Scenario: Descriptor fields match the definition
- **WHEN** the generated Data Package descriptor is read
- **THEN** its `records` schema lists exactly the standard record columns in order, with types, `description` and `example`, and `constraints.required` set only on `type`, `vehicle` and `date`

#### Scenario: Reminders table described
- **WHEN** the generated Data Package descriptor is read
- **THEN** it has a `reminders` resource whose schema lists the `reminders.csv` columns in order
