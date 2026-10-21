## Why

Cost per km, the odometer card and the consumption figures depend on odometer readings. Refuels already require one, but services and expenses are often saved without it, which leaves gaps. The user wants the odometer strongly encouraged for them: pre-filled from the last known reading, with a visible warning when it is missing.

## What Changes

- **Refuels:** the odometer stays required. The change only adds tests that pin this down (form field, server error, import row error).
- **Expense and service form (web only):** the odometer stays optional. The form shows a hint with the vehicle's last known odometer. Saving with the field empty stores that last known odometer, marked as estimated, and the Timeline shows a warning at the top. With no earlier reading, the odometer stays empty and a gentler warning says it is recommended.
- **Data model:** `expense.odometer_estimated` (boolean, default false), migration 0004.
- **Timeline row:** an estimated odometer is shown with a leading "≈".
- **Statistics:** estimated odometers are left out of the odometer span (cost per km) and of the "last odometer" figure, so they can never stretch a vehicle's distance. They are also not used as the source of the next estimate.
- **Import:** odometers are never invented. The preview warns how many new expenses have no odometer.
- **Standard format:** optional `odometer_estimated` column (expense rows) so exports and backups round-trip it.

## Capabilities

### Modified Capabilities
- `expense-records`: estimated odometer, form hint, warning, Timeline marker.
- `fuel-records`: the required odometer is stated as a scenario set.
- `data-import`: warning for expenses without an odometer.
- `standard-format`: new column `odometer_estimated`.
- `statistics`: estimated odometers do not count as readings.

## Impact

- Code: `models.py`, migration 0004, `services/records.py`, `services/stats.py`, `services/preferences.py` (one-time notice), `web/expenses.py`, `web/timeline.py`, templates, `standard.py`, `presets/glovebox.toml`, importer `base`/`engine`/`pipeline`, `exporters/csv_export.py`.
- Generated docs: `uv run python -m glovebox.formatdocs`.
- No new dependencies.
