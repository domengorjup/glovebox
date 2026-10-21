## ADDED Requirements

### Requirement: Full-to-full consumption
The system SHALL compute fuel consumption in L/100 km per segment, between consecutive full fills of one vehicle ordered by odometer.
- **Segment distance:** the odometer difference.
- **Segment fuel:** the litres of all fills after the starting full fill, up to and including the ending full fill.

A segment SHALL be invalid, and excluded from statistics, if any fill in it is flagged "missed previous fill-up", if there is no earlier full fill, or if its distance is not positive.

#### Scenario: Partial fill included in segment
- **WHEN** a vehicle has full fill at 1000 km, partial fill of 10 L at 1200 km, full fill of 30 L at 1600 km
- **THEN** the segment ending at 1600 km has consumption (10 + 30) / 600 × 100 = 6.67 L/100 km

#### Scenario: Missed fill invalidates segment
- **WHEN** the fill ending a segment is flagged "missed previous fill-up"
- **THEN** that segment is shown as n/a
- **AND** it is excluded from averages

#### Scenario: First fill has no consumption
- **WHEN** a vehicle has only one full fill
- **THEN** no consumption value is produced

### Requirement: Distance-weighted averages
Average consumption over any filter SHALL be the total fuel of the valid segments divided by their total distance, × 100. It SHALL NOT be the mean of the per-segment values.

#### Scenario: Weighted average
- **WHEN** valid segments are (20 L, 200 km) and (60 L, 1000 km)
- **THEN** average consumption is 80 / 1200 × 100 = 6.67 L/100 km

### Requirement: Consumption over time
The system SHALL show a chart of per-segment consumption over time for the selected vehicle(s), together with a monthly distance-weighted average series.

#### Scenario: Chart respects date filter
- **WHEN** the user selects 2025-01-01 to 2025-12-31
- **THEN** the chart shows only segments whose ending fill falls in 2025

#### Scenario: Monthly average
- **WHEN** two valid segments end in March 2026, 400 km using 24 L and 600 km using 42 L
- **THEN** the monthly series shows 6.6 L/100 km for March 2026 (66 L over 1000 km), not the mean of 6.0 and 7.0

### Requirement: Cost statistics
The system SHALL compute, for the active filter:
- total cost per category (fuel, maintenance, insurance, registration, other);
- monthly and yearly cost series by category;
- cost per km.

Cost per km SHALL be total cost divided by the distance driven in the period. Distance driven SHALL be the sum, over the vehicles in the filter, of each vehicle's odometer span: the maximum minus the minimum odometer over that vehicle's records in the period that have an odometer value.

#### Scenario: Cost per km
- **WHEN** a period contains 300 € fuel and 200 € maintenance, and odometer readings span 10000 to 15000 km
- **THEN** cost per km is 0.10 €/km

### Requirement: Cost allocation modes
Cost statistics SHALL support two allocation modes for expenses, selected by a view setting reflected in the URL:
- **spread** (default): an expense with coverage dates is allocated across its coverage period, proportional to the number of days (start and end inclusive), and each month receives the share of the days that fall in it. A period shows only the share that falls inside it.
- **as paid**: the full amount is counted on the payment date.

An expense without coverage dates SHALL be counted in full on its date in both modes. Fuel SHALL never be spread. Allocated monthly parts SHALL be computed in cents and SHALL sum exactly to the full amount. Cost per km SHALL use the selected mode. The mode SHALL be a view setting only: switching it SHALL NOT change any stored record.

#### Scenario: Yearly insurance spread over 12 months
- **WHEN** an insurance expense of 365.00 € paid on 2026-03-01 has coverage 2026-03-01 to 2027-02-28 (365 days) and the view is in spread mode
- **THEN** March 2026 shows 31.00 € (31 days), April 2026 shows 30.00 €, and so on through February 2027 with 28.00 €
- **AND** the twelve monthly parts sum to 365.00 €

#### Scenario: Payment without coverage dates
- **WHEN** a registration expense of 120.00 € dated 2026-05-10 has no coverage dates
- **THEN** the full 120.00 € appears in May 2026 in both spread and as-paid mode

#### Scenario: Coverage crossing a year boundary
- **WHEN** an insurance expense of 365.00 € has coverage 2026-07-01 to 2027-06-30 and the yearly series is viewed in spread mode
- **THEN** 2026 receives the share for 2026-07-01 to 2026-12-31 (184 days, 184.00 €)
- **AND** 2027 receives the share for 2027-01-01 to 2027-06-30 (181 days, 181.00 €)

#### Scenario: As-paid view shows the full payment
- **WHEN** the user views March 2026 in as-paid mode and an insurance expense of 420.00 € is dated 2026-03-01
- **THEN** the full 420.00 € appears in March 2026
- **AND** no part of it appears in other months

#### Scenario: Toggle does not alter stored data
- **WHEN** the user switches between spread and as-paid mode
- **THEN** every expense keeps its full amount and coverage dates unchanged in the database
- **AND** the default view after reload is spread unless the URL says otherwise

### Requirement: Station and brand comparison
The system SHALL show, per station and per brand, for the active filter:
- number of fills;
- total litres;
- average price per litre, weighted by litres;
- minimum and maximum price per litre;
- average consumption.

Average consumption SHALL use only valid segments in which every fill came from that station or brand, and SHALL show how many segments it is based on. A station or brand with fewer than 2 qualifying segments SHALL show consumption as n/a.

#### Scenario: Litre-weighted price
- **WHEN** a station has fills of 10 L at 1.50 and 30 L at 1.40
- **THEN** its average price per litre is 1.425

#### Scenario: Mixed-station segment excluded from station consumption
- **WHEN** a segment contains a partial fill at station A and ends with a full fill at station B
- **THEN** that segment counts toward neither A's nor B's consumption

### Requirement: Common filters
All statistics views SHALL support filtering by vehicle (one or all), date range, expense category and station or brand. The vehicle SHALL come from the remembered app-bar selection (a server-side preference) and SHALL NOT be in the URL. The other filters SHALL be reflected in the URL so a view can be bookmarked.

#### Scenario: Bookmarked filter
- **WHEN** the user opens a statistics URL containing date-range parameters
- **THEN** the view renders with those filters applied to the vehicle selected in the app bar
