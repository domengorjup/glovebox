# ui-preferences Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Server-side UI preferences
The system SHALL store UI preferences server-side in a small key/value settings table, so that they are the same on every device that opens the app.

#### Scenario: Preference shared across devices
- **WHEN** the user changes a preference on one device
- **THEN** the same preference is in effect when the app is opened on another device

### Requirement: Remember the selected vehicle
The system SHALL remember the vehicle selected in the app bar, either a specific vehicle or "All vehicles", and SHALL also remember the last specific vehicle. Selecting "All vehicles" SHALL NOT overwrite the last specific vehicle. A remembered vehicle that no longer exists or has been archived SHALL fall back to "All vehicles".

#### Scenario: Selection is remembered
- **WHEN** the user selects the vehicle "Golf" in the app bar and reopens the app
- **THEN** "Golf" is still selected

#### Scenario: All vehicles keeps the last specific vehicle
- **WHEN** the user selects "Golf" and then selects "All vehicles"
- **THEN** the selection is "All vehicles"
- **AND** the last specific vehicle is still "Golf"

#### Scenario: Remembered vehicle was deleted
- **WHEN** the remembered vehicle no longer exists
- **THEN** the app bar shows "All vehicles"

#### Scenario: Remembered vehicle was archived
- **WHEN** the remembered vehicle has been archived
- **THEN** the app bar shows "All vehicles"

### Requirement: Configurable Timeline summary cards
The system SHALL let the user choose which summary cards the Timeline shows, from a fixed set: cost this month, average consumption, last refuel, cost per km, average price per litre and odometer. The choice SHALL be stored server-side. The default SHALL be four cards: cost this month, average consumption, last refuel and cost per km. Unknown card names in the stored choice SHALL be ignored.

#### Scenario: Default cards
- **WHEN** no choice has been stored
- **THEN** the Timeline shows cost this month, average consumption, last refuel and cost per km

#### Scenario: Custom choice
- **WHEN** the user selects only odometer and average price per litre
- **THEN** the Timeline shows those two cards on every device

#### Scenario: Unknown card name
- **WHEN** the stored choice contains a card name that is not in the fixed set
- **THEN** that name is ignored and the known cards are shown

### Requirement: Vehicle dropdown in entry forms
Every add and edit form for a refuelling, service or expense SHALL have a vehicle dropdown. Its default SHALL be the vehicle selected in the app bar, or the last specific vehicle when "All vehicles" is selected.

#### Scenario: Default from app bar
- **WHEN** the user opens the add form with "Golf" selected in the app bar
- **THEN** the vehicle dropdown defaults to "Golf"

#### Scenario: Default with All vehicles
- **WHEN** the user opens the add form with "All vehicles" selected and the last specific vehicle is "Golf"
- **THEN** the vehicle dropdown defaults to "Golf"

### Requirement: Combined Timeline summary for all vehicles
With "All vehicles" selected, the Timeline SHALL show combined summary cards plus one compact summary row per vehicle.

#### Scenario: All vehicles summary
- **WHEN** the user opens the Timeline with "All vehicles" selected and two vehicles exist
- **THEN** the combined summary cards are shown
- **AND** two compact summary rows are shown, one per vehicle

