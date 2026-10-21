# expense-records Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Record expenses
The system SHALL store expense records with the following fields.
- **Required:** vehicle, date, category, title and amount.
- **Optional:** odometer (km), notes, and coverage start and end dates.
- **Estimated flag:** a boolean `odometer_estimated`, false by default, true only when the odometer was filled in by the app and not entered.
- **Category:** exactly one of `maintenance`, `insurance`, `registration` or `other`.

#### Scenario: Record an insurance payment
- **WHEN** the user enters category insurance, title "Annual policy", amount 420.00 € on 2026-03-01
- **THEN** the expense is stored and counted in the insurance category

#### Scenario: Reject unknown category
- **WHEN** an expense is submitted with category "parking"
- **THEN** the system rejects it
- **AND** the user may instead choose `other` with title "Parking"

#### Scenario: Reject expense without title
- **WHEN** an expense is submitted with an empty or blank title
- **THEN** the system rejects it and stores nothing

### Requirement: Coverage period for fixed costs
An expense of any category MAY have a coverage start date and a coverage end date, intended for insurance, registration and similar fixed costs. Both dates SHALL be set together or both left empty, and the end date SHALL NOT be before the start date (both inclusive). The stored amount SHALL always be the full price paid; coverage dates only affect how statistics allocate it.

#### Scenario: Insurance with coverage period
- **WHEN** the user enters insurance, amount 420.00 € paid on 2026-03-01, coverage 2026-03-01 to 2027-02-28
- **THEN** the expense is stored with the full amount 420.00 € and both coverage dates

#### Scenario: Reject incomplete or reversed coverage
- **WHEN** an expense has only a coverage start date, or an end date before the start date
- **THEN** the system rejects it

### Requirement: List and filter expenses
The Timeline SHALL list expenses newest first, filtered by the vehicle selected in the app bar and by the type chips, grouped by month with a total per month. Category and date-range filters SHALL be available on the Stats page, which SHALL show the filtered total.

#### Scenario: Filtered total
- **WHEN** the user filters the Stats page by category maintenance for 2026
- **THEN** the statistics cover only 2026 maintenance expenses
- **AND** the page shows their summed amount

### Requirement: Odometer default on the expense and service forms
The odometer SHALL stay optional on the expense and service forms, but the forms SHALL encourage it.
- **Last known odometer:** the highest entered odometer of the vehicle (refuels, and expenses whose odometer is not estimated) dated on or before the entry's date, or the vehicle's initial odometer when that is higher or nothing else exists.
- **Hint:** the form SHALL show the last known odometer and its date, for example "Last recorded: 104,163 km (18 Oct)", and say that it is used when the field is left empty. Without any earlier reading it SHALL say that entering the odometer is recommended.
- **Empty field on save:** the system SHALL store the last known odometer with `odometer_estimated` true.
- **No earlier reading:** the odometer SHALL stay empty.
- **Typed value:** the value SHALL be stored with `odometer_estimated` false.
- **Warning after save:** the Timeline SHALL show, once, a warning at the top. With an estimate it names the used value and tells the user to edit the entry if it is wrong. Without one it says the odometer was left empty and is recommended.
- **Timeline marker:** a row with an estimated odometer SHALL show it with a leading "≈".

#### Scenario: Empty odometer takes the last reading
- **WHEN** a vehicle's last refuel on 2026-10-18 is at 104163 km and the user saves a service on 2026-10-20 with an empty odometer
- **THEN** the service is stored with odometer 104163 and `odometer_estimated` true
- **AND** the Timeline shows "Odometer not entered — used the last recorded 104,163 km. Edit the entry if that's wrong."
- **AND** the service row shows "≈ 104,163 km"

#### Scenario: Typed odometer is a real reading
- **WHEN** the user saves a service with odometer 104500
- **THEN** it is stored with `odometer_estimated` false and no warning is shown

#### Scenario: No earlier reading
- **WHEN** the vehicle has no refuel, no entered expense odometer and no initial odometer, and the user saves an expense with an empty odometer
- **THEN** the odometer stays empty and the Timeline shows a warning that entering it is recommended

#### Scenario: Estimates do not feed estimates
- **WHEN** an expense was saved with an estimated odometer and another is saved later with an empty one
- **THEN** the later one uses the last entered reading, not the earlier estimate

