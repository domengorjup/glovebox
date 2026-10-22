## MODIFIED Requirements

### Requirement: Import with preview and explicit commit
The system SHALL import a file in three steps:
1. **Upload:** the file is read and the best-matching preset is selected.
2. **Review:** one page shows the preset (with its steps and a select to switch it), the vehicle choice for a file without vehicle names, record counts per type, vehicles found in the file, the vehicles and stations that will be created or filled, duplicates, skipped rows, per-row errors, warnings, the preset's note and the questions to answer. The Import button is on this page, above the counts. Changing the preset, the vehicle or an answer SHALL update the page in place when JavaScript is available. The review changes no data. The column mapping and value formats are adjusted in a secondary step ("Adjust mapping") that returns to the review.
3. **Commit:** writes the records only after the user confirms.

The upload SHALL open the review directly when a preset is detected or the file is a standard or backup file, and the mapping when no preset fits or the preset reads the file with errors (required fields unmapped, or rows with errors).

All records of one commit SHALL be written in a single transaction and tagged with an import batch, so that the batch can later be undone. The batch SHALL record the id of the preset used.

#### Scenario: Preview does not write
- **WHEN** the user uploads a file and stops at the review or the mapping
- **THEN** no records are added

#### Scenario: Known file opens the review
- **WHEN** the user uploads a Drivvo Android export
- **THEN** the review page opens with "Drivvo (refuelling)" selected, its steps listed and no column mapping shown
- **AND** choosing the vehicle (or a new one) makes the Import button appear

#### Scenario: Unknown file opens the mapping
- **WHEN** the user uploads a file that no preset fits
- **THEN** the mapping page opens with a notice that no preset fits
- **AND** its primary button "Back to review" is at the top and at the bottom

#### Scenario: Undo an import batch
- **WHEN** the user undoes an import batch
- **THEN** all records created by that batch are deleted
- **AND** stations created only by that batch are deleted as well

### Requirement: Multi-section files continue without re-upload
After a commit of one section of a file that has further sections, the result SHALL offer a primary button "Import next section: <section>" for the first section not yet imported in this sequence. The button SHALL continue with the same uploaded file, which the server keeps until the last section is imported or the upload expires. It SHALL open the review of that section with the best-matching preset whose section is the chosen one, and with the vehicle used for the previous section (including one created by it) pre-selected. Records already imported SHALL stay skipped as duplicates. The result SHALL list the remaining sections.

#### Scenario: Three sections in turn
- **WHEN** the user imports the refuelling section of a Drivvo file into a new vehicle and presses "Import next section: Expense"
- **THEN** the review shows the Drivvo expenses preset and has that vehicle selected
- **AND** after that commit the result offers "Import next section: Service"

#### Scenario: Last section
- **WHEN** the last section is imported
- **THEN** no further button is shown and the stored upload is removed

### Requirement: Preset steps
A preset MAY have `steps`, a list of strings. The review page and the mapping page SHALL show them as an ordered list directly under the preset select, for the selected preset, whether detected or chosen. A preset whose import needs more than "upload, review, import" (a multi-section file, a category map to extend, a special export path) SHALL have steps. Each step SHALL be short and phone-friendly (about 8 words at most) and a preset SHOULD have at most 5. The shipped Drivvo presets SHALL have steps; the `note` stays one short line. Own presets keep the `steps` of the preset file they were saved from or uploaded as.

#### Scenario: Steps follow the selected preset
- **WHEN** the review page opens for a Drivvo refuelling file
- **THEN** the steps of "Drivvo (refuelling)" are listed under the preset select
- **AND** choosing another preset shows that preset's steps, or none

### Requirement: Compact mapping page
The mapping page SHALL fold the File settings (encoding, delimiter, header row, section) and the Value formats into collapsed blocks that each show a one-line summary, and SHALL open the File block when the file could not be read or when the encoding, delimiter or header row is set explicitly instead of detected, and both blocks when there is an error. Each column row SHALL show a human label with the standard field key as small secondary text and the chosen column; options stay folded. Fields that are not mapped and have no options SHALL be folded into one collapsed block. The page SHALL list what is wrong with the current mapping (rows with errors, required fields unmapped). No setting SHALL be removed.

#### Scenario: Detection worked
- **WHEN** a readable file is mapped with a preset that detects encoding, delimiter and header row
- **THEN** the File block is collapsed and its summary names the detected encoding, delimiter and section
- **AND** all File settings are still in the form and are submitted with it

#### Scenario: Labelled rows
- **WHEN** the mapping page lists the field `odometer_km`
- **THEN** its row shows the label "Odometer" with `odometer_km` as secondary text
