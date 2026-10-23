## MODIFIED Requirements

### Requirement: Vehicle dropdown in entry forms
Every add and edit form for a refuelling, service or expense SHALL have a vehicle dropdown. Its default SHALL be the vehicle selected in the app bar, or the last specific vehicle when "All vehicles" is selected. The quick-add refuelling page SHALL instead offer a segmented vehicle choice, shown only when more than one active vehicle exists, with the same default.

#### Scenario: Default from app bar
- **WHEN** the user opens the add form with "Golf" selected in the app bar
- **THEN** the vehicle dropdown defaults to "Golf"

#### Scenario: Default with All vehicles
- **WHEN** the user opens the add form with "All vehicles" selected and the last specific vehicle is "Golf"
- **THEN** the vehicle dropdown defaults to "Golf"

#### Scenario: Quick page with one vehicle
- **WHEN** the user opens the quick-add page and only one vehicle is active
- **THEN** no vehicle choice is shown and that vehicle is used
