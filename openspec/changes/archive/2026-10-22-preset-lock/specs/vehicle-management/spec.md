## MODIFIED Requirements

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
