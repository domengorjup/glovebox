# data-import Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
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

### Requirement: Duplicate detection
The system SHALL skip records that duplicate existing ones and SHALL count them in the preview.
- **Refuels:** same vehicle, date, odometer and litres rounded to 0.01.
- **Expenses:** same vehicle, date, category and amount. Expenses SHALL be matched one to one by count: a row is a duplicate only while the database holds more rows with the same key than were already matched, so equal expenses inside one file are all imported.

#### Scenario: Re-import is a no-op
- **WHEN** the user imports the same file twice
- **THEN** the second preview reports every record as a duplicate
- **AND** the second commit adds nothing

#### Scenario: Equal expenses in one file
- **WHEN** a file holds two expenses with the same vehicle, date, category and amount
- **THEN** both are imported
- **AND** importing the file again reports both as duplicates

### Requirement: Preset-driven import engine
All CSV imports SHALL go through one engine that applies a preset. A preset maps each standard field to a source column or to a constant, with value formats. Adding or changing a supported layout SHALL be a preset change, not a code change. The engine SHALL NOT write to the database. The pipeline SHALL keep its guarantees for every preset: preview without writing, a single-transaction commit, undo by batch, duplicate detection, vehicle mapping and price derivation.

#### Scenario: New layout without code
- **WHEN** a user saves a preset for a layout that no shipped preset covers
- **THEN** files in that layout import with preview, duplicate detection and undo like any other

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

### Requirement: Shipped presets
The system SHALL ship these presets:

| Name | Status | Usable for export |
|---|---|---|
| Glovebox standard | verified | yes |
| Fuelly (metric) | unverified | yes |
| Fuelly (US units) | unverified | no |
| Fuelly (website export) | unverified | no |
| Fuelio fill-ups | unverified | no |
| Fuelio costs | unverified | no |
| Drivvo refuelling, Drivvo services, Drivvo expenses | verified (Android export) | no |

- Each shipped preset's note SHALL say where its mapping comes from, and the preview SHALL show the note.
- The Drivvo presets SHALL say "Tested with Drivvo Android exports, October 2026." The Drivvo web export holds the same records and has no preset of its own.
- The Fuelio presets SHALL read the `## Log` and `## Costs` sections respectively.

#### Scenario: Fuelly partial and missed flags
- **WHEN** a Fuelly import-format row has `partial_fuelup` 1 and `missed_fuelup` 0 and is imported with "Fuelly (metric)"
- **THEN** the refuel is stored with full false and missed_previous false

#### Scenario: Fuelly tags become station
- **WHEN** a Fuelly row has `tags` "work, highway"
- **THEN** the station name is the whole text "work, highway"

#### Scenario: Gallons converted
- **WHEN** a "Fuelly (US units)" row has `gallons` 10.000 and `price` 3.500 (per gallon)
- **THEN** the refuel stores 37.854 L and price per litre 0.925

#### Scenario: Fuelio total versus per-litre price
- **WHEN** a Fuelio `## Log` row has `Fuel (litres)` 72.604, `Price (optional)` 3000.0 and `VolumePrice` 41.32 and is imported with "Fuelio fill-ups"
- **THEN** the refuel is stored with total 3000.00 and price per litre 41.320

#### Scenario: Fuelio template cost skipped
- **WHEN** a `## Costs` row has `isTemplate` 1 and is imported with "Fuelio costs"
- **THEN** it is not imported and is counted as skipped

#### Scenario: Drivvo preset is marked tested
- **WHEN** a file is previewed with a Drivvo preset
- **THEN** the preview shows a note starting "Tested with Drivvo Android exports, October 2026."

#### Scenario: Drivvo export with several sections
- **WHEN** a Drivvo Android export with `##Refuelling`, `##Expense` and `##Service` sections is uploaded
- **THEN** each section can be imported with its own Drivvo preset
- **AND** `%uXXXX` escapes in text are decoded

### Requirement: Preset detection and file reading
On upload the system SHALL:
- **Encoding:** read UTF-8 with or without BOM, falling back to cp1252.
- **Delimiter:** sniff it among `,`, `;` and tab.
- **ZIP:** accept a ZIP of CSV files, applying the chosen preset to each CSV except `vehicles.csv` and `stations.csv` (see "Vehicles and stations tables in an import").
- **Sections:** read only the named section when the preset names one; a section starts at a line `## <name>` or `# <name>` (with or without a space after the hashes), quoted or not.
- **Text:** decode `%uXXXX` escapes and skip spaces after a delimiter that precede a quoted field.
- **Header row:** detect it within the first 20 non-blank rows.
- **Preset:** score every preset (user presets and shipped presets) by the share of its mapped columns found in the headers, and pre-select the best one if at least half of its columns are found. When no preset qualifies, the mapping SHALL start from the standard preset, with only the columns whose headers equal standard field names assigned.

The user SHALL be able to override the preset, the encoding, the delimiter and the header row. Header names SHALL be compared case- and whitespace-insensitively, ignoring a trailing parenthesised part unless the preset's name contains one.

#### Scenario: Standard file detected
- **WHEN** a file with the standard header row is uploaded
- **THEN** the "Glovebox standard" preset is pre-selected

#### Scenario: Detect Fuelio backup
- **WHEN** the uploaded file contains a `## Log` section whose headers include `Data`, `Odo (km)` and `Fuel (litres)`
- **THEN** "Fuelio fill-ups" is pre-selected

#### Scenario: Fuelio file with both sections
- **WHEN** a Fuelio file has a `## Log` and a `## Costs` section and both Fuelio presets match every column
- **THEN** "Fuelio fill-ups" is pre-selected
- **AND** a tied user preset is preferred over a shipped one

#### Scenario: Drivvo file with several sections
- **WHEN** a Drivvo export has several sections and more than one Drivvo preset matches every column
- **THEN** "Drivvo refuelling" is pre-selected

#### Scenario: Unknown headers open the mapping
- **WHEN** a file's headers match no preset
- **THEN** the mapping step lists the file's headers and the unmapped required fields
- **AND** the preview cannot be committed until the required fields are mapped

### Requirement: Column mapping
In the mapping step the user SHALL be able to set, for each standard field, a source column, a constant value or nothing. A source column MAY feed several fields. The required fields SHALL be: `type`, `date`; `odometer_km` for refuels; `total` and `title` for expenses. For refuels, at least two of `fuel_l`, `price_per_l` and `total` SHALL be available on each row. The missing figure SHALL be derived and recorded as derived. The user SHALL be able to save the current mapping as an own preset.

#### Scenario: Constant record type
- **WHEN** a file has no type column and the user sets `type` to the constant "refuel"
- **THEN** every row is imported as a refuel

#### Scenario: Two of three price figures
- **WHEN** a row gives fuel 40.000 L and total 60.00 but no price per litre
- **THEN** the refuel is stored with price per litre 1.500 and the price per litre is recorded as derived

### Requirement: Value formats
A mapping SHALL support these value formats:
- **Dates and times:** a date pattern, or automatic detection that asks the user to choose day-first or month-first when every date fits both.
- **Numbers:** a decimal separator (`.`, `,` or automatic per column) and a thousands separator (none, `,`, `.`, space or `'`). With no thousands separator set, a number containing one SHALL be a row error.
- **Units:** distance in km or miles, volume in litres, US gallons or UK gallons, converted to km and litres at import. Price per volume SHALL be converted with the volume unit. With unit set to automatic, the unit SHALL be read from a parenthesised unit in the header; if there is none, the preview SHALL ask.
- **Value maps:** target value to a list of source values, for record type, category and other fields with fixed values; compared case- and whitespace-insensitively.
- **Booleans:** lists of true and false values, e.g. a "partial" column mapped to `full` with true value `0`.
- **Missing values:** source values that count as empty, e.g. `0` for "not given".
- **Default:** used for an empty cell or a value not listed in a map or boolean list. Without a default, an empty cell takes the standard field's default and an unlisted value is a row error.

#### Scenario: Decimal comma
- **WHEN** a semicolon-delimited file has decimal separator "," and contains litres "45,20" and total "65,95"
- **THEN** they are parsed as 45.20 and 65.95

#### Scenario: Stray separator is an error
- **WHEN** the decimal separator is "." with no thousands separator and a cell holds "45,20"
- **THEN** that row is listed as an error naming the value, and it is not imported

#### Scenario: Ambiguous dates
- **WHEN** the date pattern is automatic and every date in a file is consistent with both DD/MM/YYYY and MM/DD/YYYY
- **THEN** the preview asks the user which order to use

#### Scenario: Unit from header
- **WHEN** the distance unit is automatic and the odometer header is `Odo (mi)`
- **THEN** odometer values are converted from miles to km

#### Scenario: Category value map
- **WHEN** a mapping has `category` with map `maintenance = ["Oil change", "Service"]` and default `other`, and a row's value is "oil change"
- **THEN** the expense is stored with category maintenance

### Requirement: Per-row errors in the preview
The preview SHALL list each row that cannot be imported, with its line number in the file, the field, the raw value and the reason. It SHALL also give the total number of such rows. Rows with errors and rows matched by a skip rule SHALL NOT be imported. The other rows SHALL remain committable.

#### Scenario: One bad row
- **WHEN** a file has ten rows and row 4 has the date "31/31/2024"
- **THEN** the preview lists line 5 (counting the header), field `date`, value "31/31/2024"
- **AND** the commit imports the other nine rows

### Requirement: Stations and price figures from imports
Imports SHALL create stations by name and location when they do not exist. They SHALL set a brand only when the file provides one and only when the station is created, and SHALL never infer a brand from a name. The price figures of every refuel SHALL be derived and checked as for manual entry.

#### Scenario: Station created once
- **WHEN** a file has three refuels at station "OMV Celje", which does not exist
- **THEN** one station "OMV Celje" is created, linked to all three, and belongs to the import batch

### Requirement: User presets
The system SHALL store user presets in the database as TOML text. A presets page SHALL list user and shipped presets, and SHALL let the user download any preset, upload a preset file (validated as on load), and delete a user preset. A preset SHALL open in a dialog that shows its full note and its steps; the note SHALL also wrap in the list. Shipped presets SHALL always be locked. A user preset SHALL have a lock, off by default, that the user can switch on and off. A locked preset SHALL NOT be edited, deleted or overwritten; its dialog SHALL show it read-only with a duplicate action, and with an unlock action when it is a user preset. The user SHALL be able to edit the note of an unlocked user preset in its dialog. Any preset SHALL be duplicable into a new, unlocked user preset. Saving a changed shipped preset SHALL create a user preset. A user preset whose name clashes with an existing preset SHALL be rejected with a message.

#### Scenario: Saved preset is detected next time
- **WHEN** the user saves a mapping as preset "My app" and later uploads another file with the same headers
- **THEN** "My app" is pre-selected

#### Scenario: Shipped preset not overwritten
- **WHEN** the user changes the "Fuelly (metric)" mapping and saves it
- **THEN** a new user preset is created and "Fuelly (metric)" is unchanged

#### Scenario: Note of an own preset edited
- **WHEN** the user changes the note of a user preset in its dialog and saves
- **THEN** the preset keeps its name and mapping and has the new note

#### Scenario: Shipped preset locked
- **WHEN** the user opens a shipped preset
- **THEN** the dialog shows its note and steps without an edit field and offers Duplicate
- **AND** a request to change, lock or delete it is refused

#### Scenario: Own preset locked
- **WHEN** the user locks a user preset
- **THEN** its dialog is read-only and says it is locked, with Unlock and Duplicate
- **AND** requests to edit or delete it are refused until it is unlocked

#### Scenario: Duplicate
- **WHEN** the user duplicates a preset named "Bank"
- **THEN** an unlocked user preset "Bank (copy)" exists with the same mapping, and "Bank" is unchanged

### Requirement: Vehicles and stations tables in an import
A normal import SHALL accept `vehicles.csv` and/or `stations.csv` next to the records, in a ZIP (with or without `datapackage.json`) or in a ZIP of several CSV files. These two tables have the fixed layout of the standard format and are read without the preset. A ZIP member is taken as one of them when its name is `vehicles` or `stations`, it has a `name` column and it has no `date` column. The preset is applied to the other CSV files. Columns of `vehicles.csv` other than `name` MAY be missing, so that files made by earlier versions are accepted.
- A vehicle in `vehicles.csv` that does not exist SHALL be created with all its details, including VIN, model year, engine, tyre size, insurance policy and the two valid-until dates.
- A station in `stations.csv` that does not exist SHALL be created with its location and brand, also when it has no refuels.
- A vehicle that exists (matched by name, after the vehicle mapping) and a station that exists (matched by name and location) SHALL only be completed: empty details are filled, and no existing value is overwritten.
- A model year or date that cannot be read SHALL be reported as a row error, and the vehicle SHALL be imported without that value.
- The preview SHALL list each vehicle and station that will be created, or filled with which details. Nothing is written before the user confirms.
- Stations created by the import belong to its batch and are removed by undo when no other record uses them. Details filled into existing vehicles and stations are not reverted by undo.
- `vehicles.csv` or `stations.csv` alone (without records) SHALL be accepted.

#### Scenario: Vehicle and station created with details
- **WHEN** a ZIP holds `records.csv`, `vehicles.csv` with "Golf" (make "VW", plate "LJ AB-123") and `stations.csv` with "Alpha" in Celje (brand "OMV"), none of which exist, and no `datapackage.json`
- **THEN** the preview lists vehicle "Golf" and station "Alpha" as created
- **AND** after the commit the vehicle has its make and plate and the station its location and brand

#### Scenario: Existing vehicle is only completed
- **WHEN** vehicle "Golf" exists with make "Seat" and no plate, and `vehicles.csv` gives "Golf" with make "VW" and plate "LJ AB-123"
- **THEN** the preview lists vehicle "Golf" as filled with the plate
- **AND** after the commit the make is still "Seat" and the plate is "LJ AB-123"

#### Scenario: Existing station keeps its brand
- **WHEN** station "A" in X has brand "Old" and `stations.csv` gives it brand "New"
- **THEN** the brand stays "Old"
- **AND** the station is not listed in the preview

#### Scenario: Backup from an earlier version
- **WHEN** a full backup made before vehicle details existed (no detail columns in `vehicles.csv`) is imported
- **THEN** it is restored with the vehicles' basic details and no error

#### Scenario: Vehicle details restored
- **WHEN** a backup whose `vehicles.csv` has a VIN, a model year and an insurance date is imported into an empty database
- **THEN** the vehicle has them after the commit

#### Scenario: Unreadable detail
- **WHEN** `vehicles.csv` gives model year "abcd" for "Golf"
- **THEN** the preview lists a row error for it and "Golf" is imported without a model year

#### Scenario: Station without refuels
- **WHEN** `stations.csv` lists a station that no record uses
- **THEN** the station is created

#### Scenario: A table with dates is not a companion table
- **WHEN** a ZIP member is named `stations.csv` but has a `date` column
- **THEN** it is read as a records table with the preset

### Requirement: Backup restore
A full backup ZIP (see data-export) SHALL be imported as the case above plus `datapackage.json`, through the same code path and with the same preview. Its presence makes the system read `records.csv` with the standard preset whatever preset was chosen, so the upload goes straight to the preview without a mapping step. It SHALL restore `derived` and `source` as written, and vehicles marked archived stay archived. A backup without `records.csv` SHALL be rejected with a message. The vehicle mapping and duplicate detection SHALL apply as for any import.

#### Scenario: Backup round trip
- **WHEN** a full backup is restored into an empty database and a second full backup is made
- **THEN** the two ZIPs have identical CSV files and `datapackage.json` differs only in the export time

#### Scenario: Derived field and source preserved
- **WHEN** a refuel with derived `price_per_l` and source "drivvo-refuelling" is backed up and restored into an empty database
- **THEN** the restored refuel has the same derived field and source

#### Scenario: Same result without the descriptor
- **WHEN** the same ZIP is uploaded once with and once without `datapackage.json`
- **THEN** both previews list the same records, vehicles and station and vehicle changes

### Requirement: Imports never invent odometers
The import SHALL store an expense without an odometer with the odometer empty and `odometer_estimated` false. The preview SHALL show a warning that counts the new expenses without an odometer, for example "12 expenses have no odometer.". A file value of `odometer_estimated` true on a row without an odometer SHALL be ignored.

#### Scenario: Warning for expenses without odometer
- **WHEN** a file with 12 new expenses and no odometer values is previewed
- **THEN** the preview shows the warning "12 expenses have no odometer."
- **AND** the committed expenses have no odometer

### Requirement: Shipped preset documentation
Every shipped preset file SHALL start with an `# Export:` comment saying how to produce the file it reads. A preset that was not checked against a real export SHALL say "Never tested against a real export" in its note and keep `verified = false`.

#### Scenario: Export comment present
- **WHEN** the shipped preset files are checked
- **THEN** each has an `# Export:` header comment

### Requirement: Multi-section files continue without re-upload
After a commit of one section of a file that has further sections, the result SHALL offer a primary button "Import next section: <section>" for the first section not yet imported in this sequence. The button SHALL continue with the same uploaded file, which the server keeps until the last section is imported or the upload expires. It SHALL open the review of that section with the best-matching preset whose section is the chosen one, and with the vehicle used for the previous section (including one created by it) pre-selected. Records already imported SHALL stay skipped as duplicates. The result SHALL list the remaining sections.

#### Scenario: Three sections in turn
- **WHEN** the user imports the refuelling section of a Drivvo file into a new vehicle and presses "Import next section: Expense"
- **THEN** the review shows the Drivvo expenses preset and has that vehicle selected
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
A preset MAY have `steps`, a list of strings. The review page SHALL show them as an ordered list directly under the preset select, for the selected preset, whether detected or chosen. A preset whose import needs more than "upload, review, import" (a multi-section file, a category map to extend, a special export path) SHALL have steps. Each step SHALL be short and phone-friendly (about 8 words at most) and a preset SHOULD have at most 5. The shipped Drivvo presets SHALL have steps; the `note` stays one short line. Own presets keep the `steps` of the preset file they were saved from or uploaded as.

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

