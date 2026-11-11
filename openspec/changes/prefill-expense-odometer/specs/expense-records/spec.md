## MODIFIED Requirements

### Requirement: Odometer default on the expense and service forms
The odometer SHALL stay optional on the expense and service forms, and new entries SHALL start with it filled in.
- **Last known odometer:** the highest entered odometer of the vehicle (refuels, and expenses whose odometer is not estimated) dated on or before the entry's date, or the vehicle's initial odometer when that is higher or nothing else exists.
- **Prefill:** on add forms (quick and full, not edit forms) the odometer field SHALL start with the last known odometer as an ordinary editable value. Changing the vehicle or the date SHALL update it while the user has not edited the field. Without any earlier reading it SHALL start empty.
- **Stored as entered:** a value in the field on save SHALL be stored with `odometer_estimated` false, also when the user did not change it. An empty field SHALL store no odometer and `odometer_estimated` false.
- **Hint:** under the field the form SHALL show the last known odometer and its date, for example "Last: 104,163 km on 18 Oct". When the value is higher it SHALL show the distance since that reading, for example "+337 km since the last recorded reading (18 Oct)". When the value is lower it SHALL show a red warning to check the number; saving stays possible. Without an earlier reading it SHALL say so.
- **No warning after save:** the Timeline SHALL NOT show a warning about the odometer after saving.
- **Existing estimates:** an expense with `odometer_estimated` true (older data, backups, imports) SHALL keep its Timeline marker ("≈"), SHALL be shown with an empty field and a note on the edit form, and SHALL NOT count as an odometer reading in statistics or in the last known odometer.
- **Refuelling:** the refuelling forms SHALL be unaffected.

#### Scenario: New service prefilled
- **WHEN** a vehicle's last refuel on 2026-10-18 is at 104163 km and the user opens a new service form
- **THEN** the Odometer field contains 104163
- **AND** the hint reads "Last: 104,163 km on 18 Oct"

#### Scenario: Prefilled value saved untouched
- **WHEN** the user saves that service without touching the odometer
- **THEN** it is stored with odometer 104163 and `odometer_estimated` false
- **AND** the Timeline shows no odometer warning

#### Scenario: Cleared field
- **WHEN** the user clears the field and saves
- **THEN** the expense is stored with no odometer and `odometer_estimated` false
- **AND** no warning is shown

#### Scenario: Typed odometer
- **WHEN** the user changes the field to 104500
- **THEN** the hint reads "+337 km since the last recorded reading (18 Oct)"
- **AND** the expense is stored with odometer 104500 and `odometer_estimated` false

#### Scenario: Lower value
- **WHEN** the user enters 104000
- **THEN** the hint turns red and asks to check the number, and saving is still possible

#### Scenario: Vehicle or date changes the prefill
- **WHEN** the user has not edited the field and chooses another vehicle
- **THEN** the field shows the other vehicle's last known odometer
- **AND** once the user has edited the field, changing the vehicle leaves the value alone

#### Scenario: No earlier reading
- **WHEN** the vehicle has no refuel, no entered expense odometer and no initial odometer
- **THEN** the field starts empty and the hint says there is no earlier reading

#### Scenario: Existing estimate kept
- **WHEN** an older expense has an estimated odometer
- **THEN** the Timeline row shows the "≈" marker, the edit form shows an empty field with the note that the saved value is an estimate, and a later new form's last known odometer ignores it
