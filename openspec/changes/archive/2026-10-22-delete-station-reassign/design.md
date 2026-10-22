## Decisions

- **Service:** `delete_station(session, station_id, move_to_id=None)`. With a target, all refuels of the station move to it first; without, they get `station_id` NULL (the previous behaviour). A target equal to the deleted station or not existing raises `ValidationError`/`NotFoundError` before anything changes.
- **Candidate order:** `station_move_targets` returns the other stations, those with the same brand first (only when the brand is set), then by name.
- **Import undo:** a refuel moved to another station stays in its batch; undoing that batch deletes the refuel, and a station created by the batch is only deleted when no refuel uses it. No change needed.
- **Duplicate detection** keys do not include the station, so a deleted station does not make a re-import look new.
