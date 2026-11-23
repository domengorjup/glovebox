## MODIFIED Requirements

### Requirement: Odometer default on the expense and service forms
The odometer SHALL stay optional on the expense and service forms, and new entries SHALL show the last known reading in grey.
- **Last known odometer:** the highest entered odometer of the vehicle (refuels, and expenses whose odometer is not estimated) dated on or before the entry's date, or the vehicle's initial odometer when that is higher or nothing else exists.
- **Grey reading:** on add forms (quick and full, not edit forms) the odometer field SHALL start empty and show the last known odometer as its placeholder (grey). Changing the vehicle or the date SHALL update the placeholder. Without any earlier reading the field SHALL show no reading.
- **Stored as entered:** a typed value SHALL be stored as typed with `odometer_estimated` false. An empty field on a new entry SHALL store the last known odometer of the vehicle on the entry's date, as a normal reading with `odometer_estimated` false; when there is no earlier reading it SHALL store no odometer. An empty field therefore means "use the shown reading"; there is no way to save no reading when an earlier one exists. The rule applies on the server, so it also holds without the page script. Edit forms are unchanged: an empty field stores no odometer.
- **Hint:** under the field the form SHALL show the last known odometer and its date, for example "Last: 104,163 km on 18 Oct". When the typed value is higher it SHALL show the distance since that reading, for example "+337 km since the last recorded reading (18 Oct)". When the typed value is lower it SHALL show a red warning to check the number; saving stays possible. Without an earlier reading it SHALL say so.
- **No warning after save:** the Timeline SHALL NOT show a warning about the odometer after saving.
- **Existing estimates:** an expense with `odometer_estimated` true (older data, backups, imports) SHALL keep its Timeline marker ("≈"), SHALL be shown with an empty field and a note on the edit form, and SHALL NOT count as an odometer reading in statistics or in the last known odometer.
- **Refuelling:** the refuelling forms SHALL be unaffected.

#### Scenario: New service shows the grey reading
- **WHEN** a vehicle's last refuel on 2026-10-18 is at 104163 km and the user opens a new service form
- **THEN** the Odometer field is empty and shows 104163 in grey
- **AND** the hint reads "Last: 104,163 km on 18 Oct"

#### Scenario: Empty field saved
- **WHEN** the user saves that service without typing an odometer
- **THEN** it is stored with odometer 104163 and `odometer_estimated` false
- **AND** the Timeline shows no odometer warning

#### Scenario: Typed odometer
- **WHEN** the user types 104500
- **THEN** the hint reads "+337 km since the last recorded reading (18 Oct)"
- **AND** the expense is stored with odometer 104500 and `odometer_estimated` false

#### Scenario: Lower value
- **WHEN** the user types 104000
- **THEN** the hint turns red and asks to check the number, and saving is still possible

#### Scenario: Vehicle or date changes the grey reading
- **WHEN** the user chooses another vehicle or date
- **THEN** the grey reading becomes that vehicle's last known odometer on that date

#### Scenario: No earlier reading
- **WHEN** the vehicle has no refuel, no entered expense odometer and no initial odometer
- **THEN** the field shows no reading, the hint says there is no earlier reading, and an empty field stores no odometer

#### Scenario: Existing estimate kept
- **WHEN** an older expense has an estimated odometer
- **THEN** the Timeline row shows the "≈" marker, the edit form shows an empty field with the note that the saved value is an estimate, and a later new form's last known odometer ignores it
