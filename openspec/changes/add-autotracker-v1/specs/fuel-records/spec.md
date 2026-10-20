## ADDED Requirements

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
The system SHALL list refuellings newest first, filterable by vehicle, date range and station or brand. Each row SHALL show the computed consumption for segments ending at that fill, or "n/a" when the segment is invalid.

#### Scenario: Filter by brand
- **WHEN** the user filters refuellings by brand "MOL"
- **THEN** only refuels at stations with brand "MOL" are listed
