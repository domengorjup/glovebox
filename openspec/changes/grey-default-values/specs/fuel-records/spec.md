## ADDED Requirements

### Requirement: Default price per litre on new refuellings
On new refuelling forms (quick and full, not edit) the Price / litre field SHALL show the vehicle's last price per litre in grey, following vehicle changes. A vehicle without an earlier refuelling shows no default. When the price field is empty and exactly one of litres and total is given, the system SHALL use that default price to derive the other figure, in the page and again on save. When litres and total are both given the price SHALL be derived from them and the default ignored. A typed price always wins. Edit forms are unchanged.

#### Scenario: Grey price shown
- **WHEN** a vehicle's last refuel had 1.459 €/L and the user opens a new refuelling form for it
- **THEN** the Price / litre field is empty and shows 1.459 in grey

#### Scenario: Only the total typed
- **WHEN** the user enters 50.00 € as the total and no litres and no price
- **THEN** litres are calculated with 1.459 €/L (34.270 L) and shown as calculated
- **AND** saving stores price 1.459 and total 50.00 €

#### Scenario: Only litres, server without the page script
- **WHEN** a new refuelling is submitted with 40 L, no price and no total
- **THEN** it is stored with price 1.459 €/L and total 58.36 €

#### Scenario: Litres and total typed
- **WHEN** the user enters 40 L and 60.00 €
- **THEN** the price 1.500 is calculated and the default is ignored

#### Scenario: Typed price
- **WHEN** the user enters 40 L and the price 1.399
- **THEN** the total is 55.96 € and the default is not used

#### Scenario: No earlier refuelling
- **WHEN** the vehicle has no refuelling and only the total is given
- **THEN** saving fails with the message to enter at least two figures
