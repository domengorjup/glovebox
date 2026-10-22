## MODIFIED Requirements

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
