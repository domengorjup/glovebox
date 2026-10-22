# vehicle-management Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Manage vehicles
The system SHALL let the user create, edit, archive and delete vehicles. Each vehicle SHALL have a name, which is required and unique among non-archived vehicles. Make, model, plate, fuel type, initial odometer (km) and notes SHALL be optional. The system SHALL also keep these optional details: VIN, model year, engine (free text), tyre size (free text), insurance policy number, the date insurance is valid until and the date registration is valid until. The details SHALL be shown in the vehicle form in a folded "More details" section that is collapsed by default and that opens by itself only when one of its fields has a validation error. The collapsed section SHALL state how many details are filled. The VIN field SHALL offer a copy button. The vehicle list SHALL show the filled details compactly. The system SHALL only store and show the two dates; it SHALL NOT send notifications.

#### Scenario: Create a vehicle
- **WHEN** the user submits a new vehicle with name "Golf"
- **THEN** the vehicle is stored and appears in the vehicle list

#### Scenario: Reject duplicate active name
- **WHEN** the user creates a vehicle named "Golf" while a non-archived vehicle named "Golf" exists
- **THEN** the system rejects it with a validation message

#### Scenario: Details stored and shown
- **WHEN** the user saves a vehicle with VIN "WVWZZZ1KZ6W000001", tyre size "205/55 R16" and insurance valid until 2027-03-14
- **THEN** the edit form shows them again inside the "More details" section, which is collapsed and says "3 filled"
- **AND** the vehicle list row shows the tyre size and the insurance date

#### Scenario: Details are optional
- **WHEN** the user saves a vehicle without filling the "More details" section
- **THEN** the vehicle is stored with no details

#### Scenario: Invalid detail
- **WHEN** the user enters model year "19xx" or an impossible date
- **THEN** the system rejects the form with a message and shows the "More details" section open with the entered values

### Requirement: Records belong to exactly one vehicle
Every refuelling and expense record SHALL reference exactly one vehicle. Deleting a vehicle SHALL require explicit confirmation and SHALL delete its records. The confirmation SHALL state that this cannot be undone and offer a full backup download before the delete action. Archiving SHALL keep the records but hide the vehicle from entry forms and default filters.

#### Scenario: Archive hides vehicle from forms
- **WHEN** the user archives a vehicle
- **THEN** it is not offered in new-record forms
- **AND** its records remain visible when the user explicitly filters for it

#### Scenario: Archived vehicle was selected
- **WHEN** the vehicle selected in the app bar is archived
- **THEN** the selection falls back to "All vehicles", as for a deleted vehicle

#### Scenario: Delete requires confirmation
- **WHEN** the user requests deletion of a vehicle that has records
- **THEN** the system shows how many records will be deleted
- **AND** it says this cannot be undone and offers "Download full backup"
- **AND** it deletes only after confirmation

