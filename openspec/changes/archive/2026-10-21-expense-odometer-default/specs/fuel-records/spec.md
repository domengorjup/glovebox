## ADDED Requirements

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
