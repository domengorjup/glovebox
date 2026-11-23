## 1. Server
- [x] 1.1 `services/records.py`: last price per litre of a vehicle.
- [x] 1.2 `web/refuels.py`: default price map and placeholder on add forms; apply the rule in `_save` for new refuels.
- [x] 1.3 `web/expenses.py`: placeholder instead of prefilled value; empty odometer on a new entry saves the last known reading.

## 2. UI
- [x] 2.1 Templates: refuel price placeholder and data map, quick litres/total not required with a default; expense odometer placeholder.
- [x] 2.2 `static/app.js`: `bindCalc` uses the default price; `bindOdometerHint` sets the placeholder; quick Save check follows calculated fields.
- [x] 2.3 Check the grey is visibly lighter than typed text in light and dark; CSS at the end of `app.css` only if needed.

## 3. Tests
- [x] 3.1 Price default: shown, only litres, only total, both, typed price, no history, edit unchanged.
- [x] 3.2 Odometer: placeholder, empty saved as last reading, typed kept, no earlier reading, edit unchanged.

## 4. Docs and checks
- [x] 4.1 `docs/user/records.md`.
- [x] 4.2 Touched tests green, `openspec validate --strict`, `mkdocs build --strict`, screenshots.
