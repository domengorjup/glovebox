## ADDED Requirements

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
