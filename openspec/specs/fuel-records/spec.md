# fuel-records Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Record refuellings
The system SHALL store refuelling records with the following fields.
- **Required:** vehicle, date (optional time) and odometer (km).
- **Fuel figures:** litres, price per litre and total price, as described in "Derive the missing price figure".
- **Optional:** gas station, a full/partial fill flag (default full), a "missed previous fill-up" flag (default false) and notes.

#### Scenario: Save a full refuelling
- **WHEN** the user enters date 2026-10-01, odometer 120500, 45.20 L, 1.459 €/L and station "Petrol Tržaška"
- **THEN** the record is stored with total 65.95 € and is_full true

### Requirement: Derive the missing price figure
The user SHALL provide at least two of {litres, price per litre, total}. The system SHALL derive the third and mark it as derived. If all three are given and total differs from litres × price per litre by more than 1 %, the system SHALL warn but still allow saving.

#### Scenario: Derive price per litre
- **WHEN** the user enters 40.00 L and total 60.00 € without a price per litre
- **THEN** price per litre 1.500 is stored and marked as derived

#### Scenario: Inconsistent figures warn
- **WHEN** the user enters 40.00 L, 1.500 €/L and total 70.00 €
- **THEN** the system shows an inconsistency warning before saving

### Requirement: Odometer plausibility
The system SHALL warn when a refuelling's odometer is lower than that of an earlier-dated refuelling of the same vehicle, or higher than that of a later-dated one.

#### Scenario: Out-of-order odometer warns
- **WHEN** a vehicle has a refuel on 2026-09-01 at 120000 km and the user enters a refuel on 2026-09-15 at 119000 km
- **THEN** the system warns about the odometer order

### Requirement: Gas stations with brand
The system SHALL store gas stations as separate entities with a name, an optional brand and an optional location text. Refuelling forms SHALL offer existing stations and allow creating a new one inline. The user SHALL be able to rename stations, set brands (including for several stations at once) and merge duplicate stations. Brands SHALL be assigned by hand only; the system SHALL NOT infer a brand from a station name.

#### Scenario: Merge duplicate stations
- **WHEN** the user merges station "PETROL Trzaska" into "Petrol Tržaška"
- **THEN** all refuels of the first station reference the second
- **AND** the first station is removed

#### Scenario: Bulk-assign brand
- **WHEN** the user selects three stations and sets brand "OMV"
- **THEN** all three stations have brand "OMV"

### Requirement: List and filter refuellings
The Timeline SHALL list refuellings newest first, filtered by the vehicle selected in the app bar and by the type chips, grouped by month with a total per month. Station, brand, category and date-range filters SHALL be available on the Stats page. Each row SHALL show the computed consumption for segments ending at that fill, or "n/a" when the segment is invalid.

#### Scenario: Filter by vehicle and type
- **WHEN** the user selects the vehicle "Golf" in the app bar and the refuelling chip on the Timeline
- **THEN** only refuels of "Golf" are listed, grouped by month with month totals

#### Scenario: Filter by brand on the Stats page
- **WHEN** the user filters the Stats page by brand "MOL"
- **THEN** the statistics cover only refuels at stations with brand "MOL"

### Requirement: Refuel odometer is mandatory
A refuelling SHALL NOT be saved or imported without an odometer.

#### Scenario: Form requires the odometer
- **WHEN** the refuel form is shown
- **THEN** the odometer field is marked required

#### Scenario: Server rejects a missing odometer
- **WHEN** a refuel is submitted with an empty odometer
- **THEN** nothing is stored and the form shows the message "Odometer is required"

#### Scenario: Import row without odometer
- **WHEN** an imported file has a refuel row with an empty odometer
- **THEN** the preview lists that row as an error and it is not imported

### Requirement: Delete a gas station and reassign its refuellings
The user SHALL be able to delete a gas station. When refuellings use it, the confirmation SHALL state how many and ask which other station they move to, defaulting to "No station". The other stations SHALL be listed with those of the same brand first, then by name. Reassigning and deleting SHALL happen in one transaction.

#### Scenario: Move refuellings to another station
- **WHEN** the user deletes station "Petrol A", used by three refuellings, and chooses station "Petrol B"
- **THEN** the three refuellings reference "Petrol B"
- **AND** "Petrol A" is removed

#### Scenario: Keep no station
- **WHEN** the user deletes a used station and leaves "No station" selected
- **THEN** its refuellings remain with no station and the station is removed

#### Scenario: Unused station
- **WHEN** the user deletes a station that no refuelling uses
- **THEN** the dialog shows no station select and the station is removed

#### Scenario: Invalid target
- **WHEN** a delete request names the station itself or a missing station as the target
- **THEN** nothing changes and an error is shown

### Requirement: Calculations in the cost fields of a refuelling
The Total and Price per litre fields of the refuelling forms (quick and full) SHALL accept, besides a number, a simple calculation: an optional leading `=`; numbers with a decimal comma or point; `+ - * /` with the usual precedence; unary minus; parentheses; spaces ignored; at most 200 characters. It SHALL be evaluated exactly and rounded half up to the field's decimals (cents for the total, thousandths for the price per litre). A plain number SHALL be read exactly as before; a calculation has no limit on decimals. Litres and odometer SHALL NOT accept calculations. A malformed calculation SHALL be refused with "<Field>: Not a valid calculation." and a division by zero with "<Field>: Can't divide by zero.", the typed text kept and nothing stored. The page SHALL replace a valid calculation by its result when the field is left, and the two-of-three calculation SHALL use that result.

#### Scenario: Total as a calculation
- **WHEN** the user enters 40 L and the total `=30.5+30.5*2`
- **THEN** the record is stored with total 91.50 € and the price per litre derived from it

#### Scenario: Price per litre with a decimal comma
- **WHEN** the user enters 40 L and the price per litre `1,5+0.05`
- **THEN** the record is stored with price 1.550 €/L and total 62.00 €

#### Scenario: Calculation rounds to cents
- **WHEN** the user enters the total `1,299*0,75` (0.97425)
- **THEN** the total is stored as 0.97 €

#### Scenario: Division by zero
- **WHEN** the total is `10/0`
- **THEN** nothing is stored and the field shows "Total: Can't divide by zero." with the typed text kept

#### Scenario: Malformed calculation
- **WHEN** the total is `1+` or `(1+2`
- **THEN** nothing is stored and the field shows "Total: Not a valid calculation."

#### Scenario: Page replaces the calculation
- **WHEN** the user types `12+3` in Total and leaves the field
- **THEN** the field shows 15.00 and the two-of-three calculation uses 15

