## ADDED Requirements

### Requirement: Location in exports
The standard CSV export and the `records.csv` of the full backup SHALL write each expense's location in the `location` column. A custom export SHALL offer `location` among the standard columns. The Fuelly-compatible export SHALL be unchanged: it contains refuellings only and has no location column.

#### Scenario: Location in the standard export
- **WHEN** a service with location "Example Garage" is exported in the standard format
- **THEN** its row has "Example Garage" in `location`

#### Scenario: Location in a backup
- **WHEN** a full backup is made and restored into an empty database
- **THEN** every expense has its location again

#### Scenario: Custom export without the column
- **WHEN** the user exports with only the columns `date`, `title` and `total`
- **THEN** no location is written

#### Scenario: Fuelly export unchanged
- **WHEN** the Fuelly-compatible export is made for a vehicle that has services with locations
- **THEN** the file holds the refuelling rows only, with the same header as before
