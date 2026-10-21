## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Shipped preset documentation
Every shipped preset file SHALL start with an `# Export:` comment saying how to produce the file it reads. A preset that was not checked against a real export SHALL say "Never tested against a real export" in its note and keep `verified = false`.

#### Scenario: Export comment present
- **WHEN** the shipped preset files are checked
- **THEN** each has an `# Export:` header comment
