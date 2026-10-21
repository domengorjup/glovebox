## ADDED Requirements

### Requirement: Imports never invent odometers
The import SHALL store an expense without an odometer with the odometer empty and `odometer_estimated` false. The preview SHALL show a warning that counts the new expenses without an odometer, for example "12 expenses have no odometer.". A file value of `odometer_estimated` true on a row without an odometer SHALL be ignored.

#### Scenario: Warning for expenses without odometer
- **WHEN** a file with 12 new expenses and no odometer values is previewed
- **THEN** the preview shows the warning "12 expenses have no odometer."
- **AND** the committed expenses have no odometer
