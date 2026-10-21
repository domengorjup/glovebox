## MODIFIED Requirements

### Requirement: Cost statistics
The system SHALL compute, for the active filter:
- total cost per category (fuel, maintenance, insurance, registration, other);
- monthly and yearly cost series by category;
- cost per km.

Cost per km SHALL be total cost divided by the distance driven in the period. Distance driven SHALL be the sum, over the vehicles in the filter, of each vehicle's odometer span: the maximum minus the minimum odometer over that vehicle's records in the period that have an entered odometer value. Estimated expense odometers SHALL NOT count, so they can never extend the span. The "last odometer" figure of a vehicle SHALL likewise ignore them.

#### Scenario: Cost per km
- **WHEN** a period contains 300 € fuel and 200 € maintenance, and odometer readings span 10000 to 15000 km
- **THEN** cost per km is 0.10 €/km

#### Scenario: Estimated odometer does not stretch the span
- **WHEN** a vehicle's refuels span 10000 to 15000 km and an expense dated after the last refuel carries an estimated odometer of 15000 km or a stale estimate of 9000 km
- **THEN** the distance driven stays 5000 km
