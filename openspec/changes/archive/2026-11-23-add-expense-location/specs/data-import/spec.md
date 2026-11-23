## ADDED Requirements

### Requirement: Expense location in imports
`location` SHALL be an import mapping target for expense rows. The text SHALL be stored as the expense's location, truncated to 200 characters, an empty cell meaning no location. It SHALL NOT be part of duplicate detection, and an existing expense SHALL NOT be changed by an import.
- The "Drivvo (services)" preset SHALL map the "Service location" column.
- The "Drivvo (expenses)" preset SHALL map the "Expense location" column.
- The Fuelio and Fuelly presets SHALL NOT map a location: the Fuelio `## Costs` section has no place column, and the Fuelly presets read refuellings only.

#### Scenario: Drivvo service location
- **WHEN** a Drivvo `##Service` row with "Service location" "Example Garage" is imported with "Drivvo (services)"
- **THEN** the expense is stored with location "Example Garage"

#### Scenario: Drivvo expense location
- **WHEN** a Drivvo `##Expense` row with "Expense location" "Example Insurer" is imported with "Drivvo (expenses)"
- **THEN** the expense is stored with location "Example Insurer"

#### Scenario: Standard round trip keeps the location
- **WHEN** expenses with locations are exported in the standard format and imported into an empty database with the standard preset
- **THEN** the locations are identical

#### Scenario: Duplicate with another location
- **WHEN** a row has the same vehicle, date, category and amount as a stored expense but another location
- **THEN** it is skipped as a duplicate and the stored location is kept

#### Scenario: Long location
- **WHEN** an imported location has 250 characters
- **THEN** the first 200 are stored and the import does not fail
