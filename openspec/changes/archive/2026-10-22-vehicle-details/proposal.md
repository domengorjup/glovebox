## Why

A vehicle holds only name, make, model, plate, fuel type and odometer. The user wants a few more facts at hand in the same place (VIN, tyre size, insurance policy number, when insurance and registration run out) instead of in a notes field or a drawer.

## What Changes

- **Seven optional vehicle fields:** `vin`, `model_year`, `engine` (free text), `tyre_size` (free text), `insurance_policy`, `insurance_valid_until` (date), `registration_valid_until` (date).
- **Vehicle form:** the new fields sit in a folded "More details" card, collapsed by default (also when a vehicle already has details; the header says "N filled"). It opens by itself only when one of its fields has a validation error. The VIN field has a copy button.
- **Vehicle list:** a row shows the filled details on one extra compact line.
- **Standard format:** `vehicles.csv` gains the seven columns, so full backup, restore and import carry them. Files without the columns (older backups) still import.
- **Not included:** reminders. The two dates are only stored and shown; they are named so that a later reminders feature can use them.

## Capabilities

### Modified Capabilities
- `vehicle-management`: optional vehicle details.
- `standard-format`: backup table `vehicles.csv`.
- `data-import`: reading the new `vehicles.csv` columns.

## Impact

- Code: migration 0006, `models.py`, `standard.py`, `services/records.py`, `web/vehicles.py`, `vehicles/form.html`, `vehicles/list.html`, `exporters/backup.py`, `importers/pipeline.py`, `icons.svg` (copy icon), `app.js` (copy button), `app.css`.
- Docs: generated `standard-format.md` and `datapackage.json`, `docs/user/first-steps.md`, `docs/dev/design.md`.
