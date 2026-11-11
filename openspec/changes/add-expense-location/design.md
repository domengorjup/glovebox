## Context

An `Expense` has `title`, `amount_cents`, `notes` and coverage dates. The user wants the place of a service ("izvajalec": the garage) next to purpose and price. They decided: a free-text optional field with suggestions from earlier entries, for all expense categories, and in import/export. Named "Location" in the UI and the data.

No reference to the sibling app is needed: this is a routine field, no new infrastructure.

## Goals / Non-Goals

**Goals:**
- One optional text field on every expense, entered with suggestions, shown on the Timeline, round-tripped through the standard CSV and backup, filled by the Drivvo presets.

**Non-Goals:**
- A `Location` table or entity (like stations), with its own management page, brand or merge. Free text only.
- Statistics or filters by location (a "compare garages" view). Possible later; not asked.
- A location on refuels (they already have stations).
- Showing it in the stats API.

## Decisions

### D1. Column
`expense.location`: `String(200)`, nullable, no default. Empty or blank input is stored as `NULL` (like `notes`). Text is stripped; longer than 200 characters is rejected on the forms with a message, and truncated on import (like `title[:200]`, in `importers/pipeline.py`). Alembic migration `0008_expense_location.py` (`down_revision = '0007'`), a `batch_alter_table` add_column as in `0004`; downgrade drops it. No index (not queried by filter). The duplicate-detection index `ix_expense_dedupe` is **unchanged**.

### D2. Duplicate detection unchanged
The key stays (vehicle, date, category, amount). The same payment re-imported with a corrected location is still a duplicate and is skipped; an existing row is never rewritten by an import. Adding the location to the key would make a re-import of an older backup create copies of every row that was later edited.

### D3. Suggestions: per expense category
Garages are not insurers: service suggests garages, insurance suggests insurers, and so on. The source is the distinct non-empty `location` values of earlier expenses **of the same category**, across all vehicles (a second car often goes to the same garage), most recently used first (by `date` desc, then `id` desc), at most 50, case-insensitive de-duplication keeping the newest spelling. A new function `records.recent_locations(session, category, limit=50)` returns it; `web/expenses.py` passes the list for the form's category as `location_options`, rendered as `<datalist id="location-options">` attached to the input with `list=`. (The `.mockups/ui-v2/` design uses one datalist of the same record type.)
- On the full expense form the category can be changed by the user; the datalist then follows by embedding one list per category and switching on the category control (or, simplest, the list of the category the form was opened with). Decide in 2.2 with what the form already does for title chips.
- A `<datalist>` is the native, phone-friendly choice; it adds no JS of its own and no design element. If a reusable element is added after all, it goes into `docs/dev/design.md`.

### D4. Forms
- **Full form** (`web/templates/expenses/form.html`): "Location" text input after Title and Amount; Odometer stays next to Date (see `.mockups/ui-v2/NOTES.md`). Same for all categories. Uses the existing text-field macro. `autocomplete="off"` so the browser's own history does not cover the datalist.
- **Quick Service and Expense pages** (`quick.html`): always visible, not behind **More**, in the order Title (with chips), Amount, Odometer, Location. **More** keeps date-related extras, coverage dates, reminder and notes. Location is optional and does not gate Save.
- `web/expenses.py`: `ExpenseForm.location: str = ""`, `_form_from_expense` fills it, `_parse_form` strips it and rejects more than 200 characters, `ExpenseInput.location` in `services/records.py`, `_apply_expense` sets `expense.location = data.location or None`.
- The reminders "Remind me" flow does not use the location (reminders are unchanged).

### D5. Timeline
`web/timeline.py::_expense_entry` adds the location to the meta line as recorded in `.mockups/ui-v2/NOTES.md`: service `<Location> · <notes>`; expense `<Type> · <Location> · covers ... / notes`.

### D6. Standard format
In `standard.py::RECORD_FIELDS` add, directly after `title`:
`StandardField("location", STRING, "Where the work was done or who was paid: garage, insurer, office, shop.", "Example Garage", applies_to=(EXPENSE,))`.
- Optional, expenses only; empty on refuel rows. The column order becomes `... category, title, location, coverage_start ...`.
- Consequences are all derived (design D1/D2 of v1): the `--check` test of `formatdocs.py` fails until `docs/user/standard-format.md`, `standard-format.datapackage.json` and the example records file are regenerated (`uv run python -m glovebox.formatdocs`); the export columns, the import target list and the standard preset follow. `StandardField` has no "since" marker, so no extra code for older files: a file without the column simply leaves it empty (as `odometer_estimated` was handled).
- The standard preset (`presets/glovebox.toml`) is checked: if it lists fields explicitly, `location` is added; if it is derived from the definition, nothing to do (verify in task 4.2).
- `test_standard.py` / `test_format_docs.py` may hard-code the column list or the example: update them.

### D7. Export
- **Standard CSV and backup records table:** `exporters/csv_export.py::_expense_values` adds `"location": e.location`. The backup reuses the records writer, so `datapackage.json` follows from D6.
- **Custom export / user presets:** `location` is a standard column and so is selectable and renameable with no extra code. Presets that list no `location` do not write it.
- **Fuelly export:** confirmed unaffected. It writes refuels only (`fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags`); expenses are not exported and have no column to carry a place.
- Lossless round trip (standard-format spec) now includes `location`.

### D8. Import
- `importers/base.py::CanonicalExpense` gets `location: str | None = None`; `importers/engine.py` reads `self.text("location")` in the expense row builder (next to `title`) and passes it on; `importers/pipeline.py::_new_expense` stores `location=(record.location or None)` truncated to 200; `web/imports.py` gets a label for the mapping page (`"location": "Location"` in the target label map near line 79). Since the engine has a fixed list of targets, check that the compact mapping page shows the new target only for expense presets.
- **Shipped presets, checked against the fixtures and the real-export notes:**
  - `drivvo-services.toml`: the `##Service` section has "Service location" (fixtures `drivvo_en_sections.csv`, `drivvo_web_sections.csv` show "Example Garage"). Add `location = { column = "Service location" }` and drop "Service location" from the "not imported" comment. The zero-amount fold ("Also: ...") keeps the location of the first priced item, as it keeps the other fields.
  - `drivvo-expenses.toml`: the `##Expense` section has "Expense location" (fixture: "Example Insurer"). Add `location = { column = "Expense location" }`; update the comment.
  - Both Drivvo presets are marked verified against real exports and the columns exist in the same files, so the mapping can be checked with the existing fixtures. The preset notes stay the same; the comment says the location is imported.
  - `fuelio-costs.toml`: the `## Costs` header (`CostTitle,Date,Odo,CostTypeID,Notes,Cost,flag,idR,read,RemindOdo,RemindDate,isTemplate,RepeatOdo,RepeatMonths,isIncome,UniqueId`) has no place column. Not mapped. (Note: the fixture's "Garage" is a `CostTitle` value, not a place.)
  - Fuelio fill-ups and the three Fuelly presets are refuel-only: not applicable.
- `presets.md` is regenerated; `test_presets_shipped.py` gets the Drivvo location checks.
- The Drivvo web export has the same columns in other sections but no preset of its own (see the preset comments). Nothing to do.

### D9. Stats API: not exposed
`api/v1.py` does not serialise single expenses, only summaries (cost totals, consumption). There is nothing to add a field to, and no statistic uses a location. Left out; if the companion integration (v2) wants "last service garage", it is added in that change.

### D10. Docs
`docs/user/records.md`: describe "Location" under the service and expense sections (what it is, suggestions of the same category, shown after Odometer on the quick pages, imported from Drivvo). Generated pages are rebuilt (D6, D8). CHANGELOG entry at release. README feature list is checked for a mention of expense fields (probably none).

## Risks / Trade-offs

- **Spelling variants** ("Avto Celje" vs "Avto Celje d.o.o.") split suggestions and any later per-garage statistic. Accepted for free text; case-insensitive de-duplication in suggestions helps a little.
- **Standard format grows a column:** third-party files that were made by hand are unaffected (optional); a file with the new column imported into an older Glovebox would fail on an unknown column. Acceptable: the app and its backups version together.
- **Backup restore of older backups:** no `location` column present; all values stay empty (the importer treats missing optional columns as empty).
