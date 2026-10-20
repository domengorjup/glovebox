## ADDED Requirements

### Requirement: Record expenses
The system SHALL store expense records with the following fields.
- **Required:** vehicle, date, category, title and amount.
- **Optional:** odometer (km), notes, and coverage start and end dates.
- **Category:** exactly one of `maintenance`, `insurance`, `registration` or `other`.

#### Scenario: Record an insurance payment
- **WHEN** the user enters category insurance, title "Annual policy", amount 420.00 € on 2026-03-01
- **THEN** the expense is stored and counted in the insurance category

#### Scenario: Reject unknown category
- **WHEN** an expense is submitted with category "parking"
- **THEN** the system rejects it
- **AND** the user may instead choose `other` with title "Parking"

### Requirement: Coverage period for fixed costs
An expense of any category MAY have a coverage start date and a coverage end date, intended for insurance, registration and similar fixed costs. Both dates SHALL be set together or both left empty, and the end date SHALL NOT be before the start date (both inclusive). The stored amount SHALL always be the full price paid; coverage dates only affect how statistics allocate it.

#### Scenario: Insurance with coverage period
- **WHEN** the user enters insurance, amount 420.00 € paid on 2026-03-01, coverage 2026-03-01 to 2027-02-28
- **THEN** the expense is stored with the full amount 420.00 € and both coverage dates

#### Scenario: Reject incomplete or reversed coverage
- **WHEN** an expense has only a coverage start date, or an end date before the start date
- **THEN** the system rejects it

### Requirement: List and filter expenses
The system SHALL list expenses newest first, filterable by vehicle, date range and category, and SHALL show the filtered total.

#### Scenario: Filtered total
- **WHEN** the user filters by category maintenance for 2026
- **THEN** the list shows only 2026 maintenance expenses
- **AND** it shows their summed amount
