## Why

On the presets page a preset's note was cut off in the list and could not be read in full, and the note of an own preset could not be changed without downloading, editing and uploading the file again.

## What Changes

- **Detail dialog:** a preset row opens a dialog with the full note and the steps. The note also wraps in the list row.
- **Edit the note:** for an own preset the note is editable in that dialog. Shipped presets stay read-only.

## Capabilities

### Modified Capabilities
- `data-import`: user presets.

## Impact

- Code: `web/presets.py`, `presets/index.html`, new `presets/form.html`, `app.css`.
- Docs: `docs/user/import.md`, `docs/dev/design.md`. No data-model change.
