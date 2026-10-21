## 1. Data and format
- [x] 1.1 `expense.odometer_estimated` column and migration 0004
- [x] 1.2 Standard format column, preset mapping, import and export, regenerated docs

## 2. Behaviour
- [x] 2.1 `last_known_odometer` service function
- [x] 2.2 Expense and service form: hint, estimate on empty save, one-time warning, Timeline marker
- [x] 2.3 Statistics ignore estimated odometers
- [x] 2.4 Import preview warning for expenses without an odometer

## 3. Checks
- [x] 3.1 Tests (refuel odometer required, estimate flow, stats, import, round trip, migration)
- [x] 3.2 `openspec validate`, full test run, docs build, `formatdocs --check`
- [x] 3.3 Screenshots in `.mockups/app-v2/screenshots/`
