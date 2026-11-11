## 1. Data model and records service
- [ ] 1.1 `Expense.location` (`String(200)`, nullable) in `src/glovebox/models.py`; migration `src/glovebox/migrations/versions/0008_expense_location.py` (D1). Test: migrate an existing database, old rows have `NULL`.
- [ ] 1.2 `services/records.py`: `ExpenseInput.location`, `_apply_expense` (strip, blank to `NULL`, reject over 200), `recent_locations(session, category, limit=50)` (D3). Unit tests for the order, case-insensitive de-duplication, the limit, that only the same category is listed, and that the duplicate key is unchanged.

## 2. UI (design iteration first)
- [ ] 2.1 In `.mockups/ui-v2/` (done, see NOTES.md 2026-11-11): the "Location" field on the full form and the quick pages (visible, after Odometer), and the Timeline meta line with the location; desktop and phone, light and dark; record in `NOTES.md` (in progress in parallel; get the user's feedback before 2.2).
- [ ] 2.2 `web/expenses.py` (`ExpenseForm.location`, `_form_from_expense`, input conversion, `location_options` for the form's category) and `web/templates/expenses/form.html`, `quick.html` (datalist; quick pages: Location always visible after Odometer, order title, amount, odometer, location). Check `docs/dev/design.md` for the text-field element first.
- [ ] 2.3 `web/timeline.py::_expense_entry`: location in the meta line as designed in 2.1.

## 3. Standard format, export
- [ ] 3.1 `standard.py`: field `location` after `title` (D6). Regenerate the docs (`uv run python -m glovebox.formatdocs`) and fix `tests/test_standard.py` / `tests/test_format_docs.py` if they list columns.
- [ ] 3.2 `exporters/csv_export.py::_expense_values`: write `location`. Tests in `tests/test_export_csv.py` and `tests/test_export_backup.py` (column in `records.csv` and in `datapackage.json`; custom export with and without the column; Fuelly export unchanged).

## 4. Import
- [ ] 4.1 `importers/base.py`, `importers/engine.py`, `importers/pipeline.py`, `web/imports.py`: the `location` target (D8). Tests in `tests/test_import_engine.py` / `tests/test_import_pipeline.py`: stored, truncated at 200, a duplicate with another location is still skipped.
- [ ] 4.2 Check `presets/glovebox.toml` against the definition; add `location` if the fields are listed there. Round-trip test: export, import into an empty database, export again, files identical.
- [ ] 4.3 `presets/drivvo-services.toml` ("Service location") and `presets/drivvo-expenses.toml` ("Expense location"): map and update the comments. Tests in `tests/test_presets_shipped.py` with the existing Drivvo fixtures ("Example Garage", "Example Insurer"); regenerate `docs/user/presets.md`.

## 5. End-to-end tests (`tests/test_e2e.py` style, real web forms)
- [ ] 5.1 Add a service on the full form with a location; it is stored and shown on the Timeline; editing keeps and changes it; clearing it stores nothing.
- [ ] 5.2 Quick Service and Expense pages: Location visible after Odometer, saved; the datalist offers earlier values of the same category only (across vehicles, newest first, no duplicates); more than 200 characters is rejected with a message.
- [ ] 5.3 An insurance and a registration expense accept a location too.
- [ ] 5.4 Full backup then restore into an empty database keeps the locations.

## 6. Docs and checks
- [ ] 6.1 `docs/user/records.md`; confirm the README feature list needs no change; `mkdocs build --strict`.
- [ ] 6.2 Full test suite green; `uv run python -m glovebox.formatdocs --check`.
- [ ] 6.3 At release: CHANGELOG entry (user-visible: Location field, Drivvo import fills it, new `location` column in the standard format).
