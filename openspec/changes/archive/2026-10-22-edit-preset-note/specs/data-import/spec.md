## MODIFIED Requirements

### Requirement: User presets
The system SHALL store user presets in the database as TOML text. A presets page SHALL list user and shipped presets, and SHALL let the user download any preset, upload a preset file (validated as on load), and delete a user preset. A preset SHALL open in a dialog that shows its full note and its steps; the note SHALL also wrap in the list. The user SHALL be able to edit the note of a user preset in that dialog. Shipped presets SHALL NOT be changeable in place; saving a changed shipped preset SHALL create a user preset. A user preset whose name clashes with an existing preset SHALL be rejected with a message.

#### Scenario: Saved preset is detected next time
- **WHEN** the user saves a mapping as preset "My app" and later uploads another file with the same headers
- **THEN** "My app" is pre-selected

#### Scenario: Shipped preset not overwritten
- **WHEN** the user changes the "Fuelly (metric)" mapping and saves it
- **THEN** a new user preset is created and "Fuelly (metric)" is unchanged

#### Scenario: Note of an own preset edited
- **WHEN** the user changes the note of a user preset in its dialog and saves
- **THEN** the preset keeps its name and mapping and has the new note

#### Scenario: Shipped preset read-only
- **WHEN** the user opens a shipped preset
- **THEN** the dialog shows its note and steps without an edit field, and a request to change it is refused
