## MODIFIED Requirements

### Requirement: Odometer default on the expense and service forms
The odometer SHALL stay optional on the expense and service forms, but the forms SHALL encourage it.
- **Last known odometer:** the highest entered odometer of the vehicle (refuels, and expenses whose odometer is not estimated) dated on or before the entry's date, or the vehicle's initial odometer when that is higher or nothing else exists.
- **Suggestion, not a value:** on add forms (not edit forms) the odometer field SHALL start empty and show the last known odometer as its placeholder; it SHALL NOT be prefilled.
- **Hint:** the form SHALL show the last known odometer and its date, for example "Last recorded: 104,163 km (18 Oct)", and say that it is used when the field is left empty. Without any earlier reading it SHALL say that entering the odometer is recommended.
- **Empty field on save:** the system SHALL store the last known odometer with `odometer_estimated` true.
- **No earlier reading:** the odometer SHALL stay empty.
- **Typed value:** the value SHALL be stored with `odometer_estimated` false.
- **Warning after save:** the Timeline SHALL show, once, a warning at the top. With an estimate it names the used value and tells the user to edit the entry if it is wrong. Without one it says the odometer was left empty and is recommended.
- **Timeline marker:** a row with an estimated odometer SHALL show it with a leading "≈".

#### Scenario: Empty odometer takes the last reading
- **WHEN** a vehicle's last refuel on 2026-10-18 is at 104163 km and the user saves a service on 2026-10-20 with an empty odometer
- **THEN** the service is stored with odometer 104163 and `odometer_estimated` true
- **AND** the Timeline shows "Odometer not entered — used the last recorded 104,163 km. Edit the entry if that's wrong."
- **AND** the service row shows "≈ 104,163 km"

#### Scenario: Typed odometer is a real reading
- **WHEN** the user saves a service with odometer 104500
- **THEN** it is stored with `odometer_estimated` false and no warning is shown

#### Scenario: No earlier reading
- **WHEN** the vehicle has no refuel, no entered expense odometer and no initial odometer, and the user saves an expense with an empty odometer
- **THEN** the odometer stays empty and the Timeline shows a warning that entering it is recommended

#### Scenario: Estimates do not feed estimates
- **WHEN** an expense was saved with an estimated odometer and another is saved later with an empty one
- **THEN** the later one uses the last entered reading, not the earlier estimate
