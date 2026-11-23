## MODIFIED Requirements

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

## ADDED Requirements

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
