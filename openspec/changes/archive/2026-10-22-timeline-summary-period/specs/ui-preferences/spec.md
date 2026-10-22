## MODIFIED Requirements

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

## ADDED Requirements

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
