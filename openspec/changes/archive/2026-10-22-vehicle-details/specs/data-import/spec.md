## MODIFIED Requirements

### Requirement: Vehicles and stations tables in an import
A normal import SHALL accept `vehicles.csv` and/or `stations.csv` next to the records, in a ZIP (with or without `datapackage.json`) or in a ZIP of several CSV files. These two tables have the fixed layout of the standard format and are read without the preset. A ZIP member is taken as one of them when its name is `vehicles` or `stations`, it has a `name` column and it has no `date` column. The preset is applied to the other CSV files. Columns of `vehicles.csv` other than `name` MAY be missing, so that files made by earlier versions are accepted.
- A vehicle in `vehicles.csv` that does not exist SHALL be created with all its details, including VIN, model year, engine, tyre size, insurance policy and the two valid-until dates.
- A station in `stations.csv` that does not exist SHALL be created with its location and brand, also when it has no refuels.
- A vehicle that exists (matched by name, after the vehicle mapping) and a station that exists (matched by name and location) SHALL only be completed: empty details are filled, and no existing value is overwritten.
- A model year or date that cannot be read SHALL be reported as a row error, and the vehicle SHALL be imported without that value.
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

#### Scenario: Backup from an earlier version
- **WHEN** a full backup made before vehicle details existed (no detail columns in `vehicles.csv`) is imported
- **THEN** it is restored with the vehicles' basic details and no error

#### Scenario: Vehicle details restored
- **WHEN** a backup whose `vehicles.csv` has a VIN, a model year and an insurance date is imported into an empty database
- **THEN** the vehicle has them after the commit

#### Scenario: Unreadable detail
- **WHEN** `vehicles.csv` gives model year "abcd" for "Golf"
- **THEN** the preview lists a row error for it and "Golf" is imported without a model year

#### Scenario: Station without refuels
- **WHEN** `stations.csv` lists a station that no record uses
- **THEN** the station is created

#### Scenario: A table with dates is not a companion table
- **WHEN** a ZIP member is named `stations.csv` but has a `date` column
- **THEN** it is read as a records table with the preset
