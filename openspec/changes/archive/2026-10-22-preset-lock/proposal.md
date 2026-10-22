## Why

Presets can be changed or deleted by accident, and a shipped preset offers no way to start from it. Deleting a vehicle removes its records for good, but the confirmation gives no way to take a backup first.

## What Changes

- **Lock:** shipped presets are always locked. A user preset has a lock switch (default off). A locked preset cannot be edited, deleted or overwritten. Its dialog shows it read-only with Unlock (user presets) and Duplicate.
- **Duplicate:** any preset can be copied to a new, unlocked user preset ("<name> (copy)").
- **Vehicle delete:** the confirmation says the records cannot be recovered and offers "Download full backup" before the Delete button.

## Capabilities

### Modified Capabilities
- `data-import`: user presets.
- `vehicle-management`: deleting a vehicle.

## Impact

- Code: migration 0005 (`preset.locked`), `models.py`, `web/presets.py`, `presets/form.html`, `presets/index.html`, `vehicles/delete.html`, `app.js` (a download button submits natively), `app.css`.
- Docs: `docs/user/import.md`, `docs/dev/design.md`.
