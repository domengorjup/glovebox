## MODIFIED Requirements

### Requirement: Vehicle mapping
The preview SHALL list each vehicle name found in the file and let the user map it to an existing vehicle or create a new one. Vehicle names come from the column mapped to `vehicle`, or, for a ZIP upload without such a column, from the name of each CSV in the ZIP. A file without vehicle names SHALL require choosing a target vehicle: an existing one, or "New vehicle..." with a name. A new target vehicle SHALL be created in the commit transaction, only if the commit writes records. Its name SHALL be required and SHALL NOT match an active vehicle. Undoing the batch SHALL keep the vehicle, as for vehicles created from vehicle names.

#### Scenario: Map imported vehicle to existing one
- **WHEN** a file contains vehicle "My Golf" and the user maps it to existing vehicle "Golf"
- **THEN** the committed records reference "Golf"

#### Scenario: File without vehicle names
- **WHEN** a file with no vehicle column, such as a Fuelly import-format file, is uploaded
- **THEN** the preview asks for a target vehicle (an existing one or a new one)
- **AND** nothing is imported until a target is chosen

#### Scenario: New vehicle at import
- **WHEN** the user picks "New vehicle..." and enters the name "Passat" for a file without vehicle names
- **THEN** the commit creates the vehicle "Passat" and attaches the imported records to it

#### Scenario: New vehicle name invalid
- **WHEN** the user picks "New vehicle..." and leaves the name empty, or enters the name of an active vehicle
- **THEN** the preview shows an error and offers no import

### Requirement: Preset file format
A preset SHALL be a TOML file that a person can read and write by hand. It describes one CSV table and contains:
- a name, a free-text note, a `verified` flag, an `export` flag and a `split_by_vehicle` flag;
- optional `steps`: a list of short instructions for the person importing (see "Preset steps");
- optional file settings: encoding, delimiter, header row, and a section name;
- value formats: date pattern, decimal separator, thousands separator, distance unit, volume unit;
- one entry per mapped standard field: either `column` (a header name, or a list of candidate names tried in order) or `value` (a constant), optionally with `map`, `true_values`, `false_values`, `missing_values` and `default`;
- optional rules to skip rows by the value of a column;
- an optional `zero_amount` (`"error"`, the default, or `"note"`; see "Zero-amount items as notes").

Loading SHALL reject unknown keys, unknown target fields and invalid values with a message that names the key.

#### Scenario: Unknown key rejected
- **WHEN** a preset file contains `[fields.litres]`, which is not a standard field
- **THEN** loading fails with a message naming `fields.litres`

#### Scenario: Hand-written preset round-trips
- **WHEN** a user preset is saved and downloaded
- **THEN** the downloaded file loads back to the same preset, including its steps

## ADDED Requirements

### Requirement: Multi-section files continue without re-upload
After a commit of one section of a file that has further sections, the result SHALL offer a primary button "Import next section: <section>" for the first section not yet imported in this sequence. The button SHALL continue with the same uploaded file, which the server keeps until the last section is imported or the upload expires. The mapping of that section SHALL start from the best-matching preset whose section is the chosen one, and the vehicle used for the previous section (including one created by it) SHALL be pre-selected in the preview. Records already imported SHALL stay skipped as duplicates. The result SHALL list the remaining sections.

#### Scenario: Three sections in turn
- **WHEN** the user imports the refuelling section of a Drivvo file into a new vehicle and presses "Import next section: Expense"
- **THEN** the mapping shows the Drivvo expenses preset and the preview has that vehicle selected
- **AND** after that commit the result offers "Import next section: Service"

#### Scenario: Last section
- **WHEN** the last section is imported
- **THEN** no further button is shown and the stored upload is removed

### Requirement: Zero-amount items as notes
A preset with `zero_amount = "note"` SHALL NOT report expense rows with an amount of 0 as errors. Such a row SHALL be added to the notes of the first expense with an amount above 0 that has the same date and odometer in the same file, as a line "Also: <title>, <title>" (titles in file order, repeats once). If the notes already have text, the line follows it on a new line. A zero-amount row without such an expense SHALL be skipped and counted with the rows skipped by the preset. Duplicate detection SHALL NOT depend on notes, so a re-import stays a no-op.

#### Scenario: Items of one visit
- **WHEN** a service file has "Oil Change" for 48 and "Oil Filter" for 0 on the same date and odometer
- **THEN** the Oil Change expense is imported with the note "Also: Oil Filter"
- **AND** no expense is created for the filter

#### Scenario: Visit without a priced item
- **WHEN** a zero-amount service row has no priced row with the same date and odometer
- **THEN** it is skipped and counted in the preview

### Requirement: Preset steps
A preset MAY have `steps`, a list of strings. The mapping page SHALL show them as an ordered list directly under the preset select, for the selected preset, whether detected or chosen. A preset whose import needs more than "upload, preview, import" (a multi-section file, a category map to extend, a special export path) SHALL have steps. Each step SHALL be short and phone-friendly (about 8 words at most) and a preset SHOULD have at most 5. The shipped Drivvo presets SHALL have steps; the `note` stays one short line. Own presets keep the `steps` of the preset file they were saved from or uploaded as.

#### Scenario: Steps follow the selected preset
- **WHEN** the mapping page opens for a Drivvo refuelling file
- **THEN** the steps of "Drivvo (refuelling)" are listed under the preset select
- **AND** choosing another preset shows that preset's steps, or none

### Requirement: Compact mapping page
The mapping page SHALL fold the File settings (encoding, delimiter, header row, section) and the Value formats into collapsed blocks that each show a one-line summary, and SHALL open the File block when the file could not be read or when the encoding, delimiter or header row is set explicitly instead of detected, and both blocks when there is an error. Each column row SHALL take little vertical space on a phone, and fields that are not mapped and have no options SHALL be folded into one collapsed block. No setting SHALL be removed.

#### Scenario: Detection worked
- **WHEN** a readable file is mapped with a preset that detects encoding, delimiter and header row
- **THEN** the File block is collapsed and its summary names the detected encoding, delimiter and section
- **AND** all File settings are still in the form and are submitted with it
