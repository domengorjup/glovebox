## MODIFIED Requirements

### Requirement: Vehicles and stations tables in an import
A normal import SHALL accept `vehicles.csv` and/or `stations.csv` next to the records, in a ZIP (with or without `datapackage.json`) or in a ZIP of several CSV files. These two tables have the fixed layout of the standard format and are read without the preset. A ZIP member is taken as one of them when its name is `vehicles` or `stations`, it has a `name` column and it has no `date` column. A ZIP member named `reminders` with a `due_date` column is the reminders table (see "Reminders table in an import"). The preset is applied to the other CSV files.
- A vehicle in `vehicles.csv` that does not exist SHALL be created with all its details.
- A station in `stations.csv` that does not exist SHALL be created with its location and brand, also when it has no refuels.
- A vehicle that exists (matched by name, after the vehicle mapping) and a station that exists (matched by name and location) SHALL only be completed: empty details are filled, and no existing value is overwritten.
- The preview SHALL list each vehicle and station that will be created, or filled with which details. Nothing is written before the user confirms.
- Stations created by the import belong to its batch and are removed by undo when no other record uses them. Details filled into existing vehicles and stations are not reverted by undo.
- `vehicles.csv` or `stations.csv` alone (without records) SHALL be accepted.

#### Scenario: Vehicle and station created with details
- **WHEN** a ZIP holds `records.csv`, `vehicles.csv` with "Golf" (make "VW", plate "LJ AB-123") and `stations.csv` with "Alpha" in Celje (brand "OMV"), none of which exist, and no `datapackage.json`
- **THEN** the preview lists vehicle "Golf" and station "Alpha" as created
- **AND** after the commit the vehicle has its make and plate and the station its location and brand

#### Scenario: Existing vehicle is only completed
- **WHEN** vehicle "Golf" exists with make "Seat" and no plate, and `vehicles.csv` gives "Golf" with make "VW" and plate "LJ AB-123"
- **THEN** the preview lists vehicle "Golf" as filled with the plate
- **AND** after the commit the make is still "Seat" and the plate is "LJ AB-123"

#### Scenario: Existing station keeps its brand
- **WHEN** station "A" in X has brand "Old" and `stations.csv` gives it brand "New"
- **THEN** the brand stays "Old"
- **AND** the station is not listed in the preview

#### Scenario: Station without refuels
- **WHEN** `stations.csv` lists a station that no record uses
- **THEN** the station is created

#### Scenario: A table with dates is not a companion table
- **WHEN** a ZIP member is named `stations.csv` but has a `date` column
- **THEN** it is read as a records table with the preset

## ADDED Requirements

### Requirement: Reminders table in an import
An import SHALL accept `reminders.csv` in the standard layout next to the records, or alone, in a ZIP with or without `datapackage.json`. A full backup restore SHALL restore it.
- **Vehicles:** the vehicle mapping SHALL apply to its `vehicle` column.
- **Duplicates:** a reminder whose `uid` already exists SHALL be skipped as a duplicate.
- **Errors:** rows with an unknown category or status, a missing title or due date, or negative lead days SHALL be listed as errors and not imported.
- **Preview:** the preview SHALL show how many reminders will be created and skipped.
- **Undo:** imported reminders SHALL belong to the import batch, and undo SHALL remove them.
- **Calendar:** in add-on mode with a calendar chosen, the imported open reminders SHALL then be synced as new reminders, reusing events already in the calendar by their marker (see reminder-delivery).

#### Scenario: Backup round trip with reminders
- **WHEN** a full backup with one open and one done reminder is restored into an empty database and a second full backup is made
- **THEN** both backups have identical `reminders.csv` files

#### Scenario: Restore twice
- **WHEN** the same backup is imported a second time
- **THEN** its reminders are listed as duplicates and not created again

#### Scenario: Undo
- **WHEN** an import that created 3 reminders is undone
- **THEN** those 3 reminders are deleted
