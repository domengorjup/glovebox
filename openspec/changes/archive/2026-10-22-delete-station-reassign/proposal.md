## Why

Stations can be merged, but there is no way to delete one from the web UI. A station that was entered by mistake or is no longer wanted should be removable, and its refuellings should not silently lose their station. The user wants to be asked which other station takes over.

## What Changes

- **Delete station (web):** the station edit dialog gets a Delete button that opens a confirmation dialog.
- **Used station:** the dialog states how many refuellings use it and offers a select "Move them to". Default is "No station"; then the other stations, same brand first, then by name.
- **Unused station:** the dialog only confirms the deletion.
- **One transaction:** the refuellings are reassigned and the station deleted together. The chosen station must exist and differ from the deleted one.
- **Imports:** unchanged. Undo only deletes stations that no refuel uses, and duplicate detection does not look at stations, so both stay consistent.

## Capabilities

### Modified Capabilities
- `fuel-records`: deleting a station with reassignment of its refuellings.

## Impact

- Code: `services/records.py` (`delete_station`, two small helpers), `web/stations.py`, `stations/form.html`, new `stations/delete.html`.
- Docs: `docs/user/stations.md`. Mockup: `.mockups/ui-v2/`.
- No data-model change, no new dependencies.
