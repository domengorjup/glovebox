## Why

A service entry says what was done and what it cost, but not where. Comparing garages, or finding which workshop did a repair, is impossible today. Drivvo has a "Service location" and "Expense location" column that the importers currently drop. The same applies to the other expense categories: the insurer, the office that registered the car, the shop of an "other" cost.

## What Changes

- **New optional field `location` on every expense** (service/maintenance, insurance, registration, other): free text, at most 200 characters, label "Location". It names where the work was done or who it was paid to (garage, insurer, office, shop).
- **Forms:** the full form and the quick Service and Expense pages get a "Location" text field with suggestions from earlier entries of the same category (a `<datalist>` of distinct previous values). On the quick pages it is always visible, after Odometer.
- **Timeline:** the location is shown in the entry's meta line (visual detail from the `.mockups/ui-v2/` design iteration).
- **Standard CSV format:** a new optional column `location`, right after `title`, applying to expenses. Included in the standard export, the full backup (records table and `datapackage.json`) and the custom export columns.
- **Import:** `location` becomes a mapping target. The Drivvo services preset maps "Service location" and the Drivvo expenses preset maps "Expense location". Other shipped presets have no such column and stay as they are.
- **Unchanged:** duplicate detection (still vehicle, date, category, amount), the stats API, statistics and the Fuelly export.

## Capabilities

### Modified Capabilities
- `expense-records`: the optional location, the forms, the suggestions and the Timeline line.
- `standard-format`: column `location` in the records table and the generated docs.
- `data-export`: the standard export and backup carry it; Fuelly export unchanged.
- `data-import`: `location` mapping target, standard round trip, Drivvo presets.

## Impact

- **Code:** `models.py` (+ migration 0008), `services/records.py` (`ExpenseInput`, `_apply_expense`, suggestions query), `web/expenses.py`, `web/templates/expenses/form.html` and `quick.html`, `web/timeline.py`, `standard.py`, `exporters/csv_export.py`, `importers/base.py` (`CanonicalExpense`), `importers/engine.py`, `importers/pipeline.py`, `web/imports.py` (target label), `presets/drivvo-services.toml`, `presets/drivvo-expenses.toml`.
- **Docs:** `docs/user/records.md`, regenerated `docs/user/standard-format.md`, its `datapackage.json` and `docs/user/presets.md`, `docs/dev/design.md` only if a new element is added, CHANGELOG at release.
- **Data:** one nullable column; existing rows stay empty. No new dependencies.
