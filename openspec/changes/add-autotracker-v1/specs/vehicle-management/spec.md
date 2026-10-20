## ADDED Requirements

### Requirement: Manage vehicles
The system SHALL let the user create, edit, archive and delete vehicles. Each vehicle SHALL have a name, which is required and unique among non-archived vehicles. Make, model, plate, fuel type, initial odometer (km) and notes SHALL be optional.

#### Scenario: Create a vehicle
- **WHEN** the user submits a new vehicle with name "Golf"
- **THEN** the vehicle is stored and appears in the vehicle list

#### Scenario: Reject duplicate active name
- **WHEN** the user creates a vehicle named "Golf" while a non-archived vehicle named "Golf" exists
- **THEN** the system rejects it with a validation message

### Requirement: Records belong to exactly one vehicle
Every refuelling and expense record SHALL reference exactly one vehicle. Deleting a vehicle SHALL require explicit confirmation and SHALL delete its records. Archiving SHALL keep the records but hide the vehicle from entry forms and default filters.

#### Scenario: Archive hides vehicle from forms
- **WHEN** the user archives a vehicle
- **THEN** it is not offered in new-record forms
- **AND** its records remain visible when the user explicitly filters for it

#### Scenario: Delete requires confirmation
- **WHEN** the user requests deletion of a vehicle that has records
- **THEN** the system shows how many records will be deleted
- **AND** it deletes only after confirmation
