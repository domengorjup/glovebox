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
The system SHALL let the user choose which summary cards the Timeline shows, from a fixed set: cost, average consumption, last refuel, cost per km, average price per litre and odometer. The choice SHALL be stored server-side. The default SHALL be four cards: cost, average consumption, last refuel and cost per km. Unknown card names in the stored choice SHALL be ignored. Cost, average consumption, cost per km and average price per litre SHALL cover the summary's period; last refuel and odometer SHALL NOT depend on it.

#### Scenario: Default cards
- **WHEN** no choice has been stored
- **THEN** the Timeline shows cost, average consumption, last refuel and cost per km

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

### Requirement: Timeline summary period
Each Timeline summary (the single vehicle, the combined "All vehicles" summary and each vehicle's summary in the all-vehicles view) SHALL have a period with the choices This month, Last 30 days, This year, Last 12 months, All time and Custom range (from and to dates). The default SHALL be Last 12 months. The period SHALL be stored server-side per vehicle and once for the combined summary, so a vehicle keeps its period whether it is viewed alone or within All vehicles. Choosing a period SHALL work with a plain form post and redirect. The hint of each period card SHALL show the date range. The stats API SHALL NOT change.

The cost card SHALL be titled "Cost" ("Cost this month" for This month) and SHALL compare with a previous period: for This month the same days of the previous month, for This year the same days of the previous year (a shorter month ends the comparison at its last day), for Last 30 days, Last 12 months and Custom range the range of equal length just before, and none for All time (the hint then shows the range). The comparison SHALL be made only when the earliest record of the shown vehicles (of all vehicles for the combined summary) lies on or before the first day of the previous period; otherwise the hint SHALL read "No full earlier period to compare". When the period has no refuelling, average consumption, cost per km and average price per litre SHALL show a dash with "No refuelling in period".

#### Scenario: Default period
- **WHEN** no period has been stored for a summary
- **THEN** its chip reads "Last 12 months"

#### Scenario: Period remembered per vehicle
- **WHEN** the user picks Last 30 days for "Golf" and then selects "All vehicles"
- **THEN** the Golf summary in the all-vehicles view shows Last 30 days
- **AND** the combined summary and the other vehicles keep their own periods

#### Scenario: Same days of the previous month
- **WHEN** the period is This month and today is 31 March
- **THEN** the cost is compared with 1 to 28 February (29 in a leap year)

#### Scenario: Previous period only partly covered by data
- **WHEN** the earliest record lies inside the previous period
- **THEN** the cost card shows no comparison and its hint reads "No full earlier period to compare"

#### Scenario: Custom range
- **WHEN** the user enters from 1 March to 31 May
- **THEN** the cards cover those dates and the cost is compared with the 92 days before 1 March

#### Scenario: No refuelling in the period
- **WHEN** the period contains no refuelling
- **THEN** average consumption, cost per km and average price per litre show a dash and "No refuelling in period"
- **AND** last refuel and odometer are unchanged

