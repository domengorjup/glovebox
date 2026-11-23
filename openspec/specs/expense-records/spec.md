# expense-records Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Record expenses
The system SHALL store expense records with the following fields.
- **Required:** vehicle, date, category, title and amount.
- **Optional:** odometer (km), notes, location, and coverage start and end dates.
- **Location:** free text of at most 200 characters naming where the work was done or who was paid (garage, insurer, office, shop). It is available for every category. Leading and trailing spaces SHALL be removed and an empty value SHALL be stored as no location.
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

#### Scenario: Service with a location
- **WHEN** the user enters a service "Oil change", amount 120.00 €, location "Example Garage"
- **THEN** the expense is stored with that location

#### Scenario: Location for other categories
- **WHEN** the user enters an insurance expense with location "Example Insurer"
- **THEN** the expense is stored with that location

#### Scenario: Blank location
- **WHEN** an expense is submitted with a location of only spaces
- **THEN** it is stored without a location

#### Scenario: Location too long
- **WHEN** an expense is submitted with a location of 201 characters
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
The odometer SHALL stay optional on the expense and service forms, and new entries SHALL start with it filled in.
- **Last known odometer:** the highest entered odometer of the vehicle (refuels, and expenses whose odometer is not estimated) dated on or before the entry's date, or the vehicle's initial odometer when that is higher or nothing else exists.
- **Prefill:** on add forms (quick and full, not edit forms) the odometer field SHALL start with the last known odometer as an ordinary editable value. Changing the vehicle or the date SHALL update it while the user has not edited the field. Without any earlier reading it SHALL start empty.
- **Stored as entered:** a value in the field on save SHALL be stored with `odometer_estimated` false, also when the user did not change it. An empty field SHALL store no odometer and `odometer_estimated` false.
- **Hint:** under the field the form SHALL show the last known odometer and its date, for example "Last: 104,163 km on 18 Oct". When the value is higher it SHALL show the distance since that reading, for example "+337 km since the last recorded reading (18 Oct)". When the value is lower it SHALL show a red warning to check the number; saving stays possible. Without an earlier reading it SHALL say so.
- **No warning after save:** the Timeline SHALL NOT show a warning about the odometer after saving.
- **Existing estimates:** an expense with `odometer_estimated` true (older data, backups, imports) SHALL keep its Timeline marker ("≈"), SHALL be shown with an empty field and a note on the edit form, and SHALL NOT count as an odometer reading in statistics or in the last known odometer.
- **Refuelling:** the refuelling forms SHALL be unaffected.

#### Scenario: New service prefilled
- **WHEN** a vehicle's last refuel on 2026-10-18 is at 104163 km and the user opens a new service form
- **THEN** the Odometer field contains 104163
- **AND** the hint reads "Last: 104,163 km on 18 Oct"

#### Scenario: Prefilled value saved untouched
- **WHEN** the user saves that service without touching the odometer
- **THEN** it is stored with odometer 104163 and `odometer_estimated` false
- **AND** the Timeline shows no odometer warning

#### Scenario: Cleared field
- **WHEN** the user clears the field and saves
- **THEN** the expense is stored with no odometer and `odometer_estimated` false
- **AND** no warning is shown

#### Scenario: Typed odometer
- **WHEN** the user changes the field to 104500
- **THEN** the hint reads "+337 km since the last recorded reading (18 Oct)"
- **AND** the expense is stored with odometer 104500 and `odometer_estimated` false

#### Scenario: Lower value
- **WHEN** the user enters 104000
- **THEN** the hint turns red and asks to check the number, and saving is still possible

#### Scenario: Vehicle or date changes the prefill
- **WHEN** the user has not edited the field and chooses another vehicle
- **THEN** the field shows the other vehicle's last known odometer
- **AND** once the user has edited the field, changing the vehicle leaves the value alone

#### Scenario: No earlier reading
- **WHEN** the vehicle has no refuel, no entered expense odometer and no initial odometer
- **THEN** the field starts empty and the hint says there is no earlier reading

#### Scenario: Existing estimate kept
- **WHEN** an older expense has an estimated odometer
- **THEN** the Timeline row shows the "≈" marker, the edit form shows an empty field with the note that the saved value is an estimate, and a later new form's last known odometer ignores it

### Requirement: Location suggestions and display
The full expense form and the quick Service and Expense pages SHALL offer a Location field with suggestions. The suggestions SHALL be the distinct locations of earlier expenses of the same category (any vehicle), most recently used first, compared without regard to case, at most 50. The quick pages SHALL show the field always, after the Odometer. The Timeline SHALL show an expense's location in its meta line. Duplicate detection SHALL NOT use the location.

#### Scenario: Suggestions come from earlier entries
- **WHEN** earlier services have the locations "Example Garage", "example garage" and "Other Garage", and the user opens the service form
- **THEN** the suggestions are "Other Garage" and the newest spelling of "Example Garage", each once

#### Scenario: Suggestions cross vehicles
- **WHEN** a service for vehicle A has location "Example Garage" and the user adds a service for vehicle B
- **THEN** "Example Garage" is suggested

#### Scenario: Suggestions stay within the category
- **WHEN** an insurance expense has location "Example Insurer" and the user adds a service
- **THEN** "Example Insurer" is not suggested

#### Scenario: Timeline line
- **WHEN** a service has location "Example Garage"
- **THEN** its Timeline entry shows "Example Garage"

#### Scenario: Location does not affect duplicates
- **WHEN** an imported expense has the same vehicle, date, category and amount as a stored one but another location
- **THEN** it is skipped as a duplicate

### Requirement: Calculations in the amount field
The Amount field of the expense and service forms (quick and full) SHALL accept a calculation under the same rules as the cost fields of a refuelling (optional leading `=`, `+ - * /`, unary minus, parentheses, spaces ignored, at most 200 characters), evaluated exactly and rounded half up to cents. A plain number SHALL be read exactly as before. A malformed calculation SHALL be refused with "Amount: Not a valid calculation." and a division by zero with "Amount: Can't divide by zero.", the typed text kept and nothing stored. The page SHALL replace a valid calculation by its result when the field is left.

#### Scenario: Amount as a calculation
- **WHEN** the user enters the amount `=120 + 45,50 - 10`
- **THEN** the expense is stored with amount 155.50 €

#### Scenario: Parentheses
- **WHEN** the user enters the amount `=(100+20)*2`
- **THEN** the expense is stored with amount 240.00 €

#### Scenario: Division by zero
- **WHEN** the user enters the amount `=5/0`
- **THEN** the expense is rejected with "Amount: Can't divide by zero." and nothing is stored

