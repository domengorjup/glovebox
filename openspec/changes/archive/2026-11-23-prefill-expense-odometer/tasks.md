## 1. Server
- [x] 1.1 `src/glovebox/web/expenses.py`: prefill `odometer_km` from `records.last_known_odometer` on the first GET of `/expenses/new` and the quick service/expense pages (not on the 422 re-render, not on edit); remove the estimate branch and the `("estimated"/"missing")` notices from `_save` (D1, D3, D4).
- [x] 1.2 `src/glovebox/web/timeline.py::_flash_warnings` (and `preferences.set_flash` callers, `_flash_saved` in `web/expenses.py`): remove the odometer warning variants and any now-unused notice kinds (D4). Keep the "~"/"≈" marker in `_expense_entry`.
- [x] 1.3 Check that `services/records.py` (`ExpenseInput.odometer_estimated`, `_apply_expense`, `last_known_odometer`, `odometer_steps`), `services/stats.py`, `standard.py`, importers and exporters need no change.

## 2. UI (design iteration first)
- [x] 2.1 `.mockups/ui-v2/` already shows the hints (NOTES.md 2026-11-11); update it to a prefilled value (filled field, "+N km" and red states) and record in `NOTES.md`; get the user's feedback before 2.2.
- [x] 2.2 `src/glovebox/web/templates/expenses/form.html` and `quick.html`: value instead of placeholder, new hint wording, estimated-row note kept.
- [x] 2.3 `src/glovebox/web/static/app.js` (`bindOdometerHint`, quick hint): follow vehicle/date changes until the field is touched; "Last: ...", "+N km ...", red "Lower than ..." states (D2, D5). Reuse the refuelling hint code where possible.

## 3. Tests
- [x] 3.1 Update `tests/test_expense_odometer.py` and `tests/test_quick_add.py`, plus any `tests/test_e2e.py` assertions on the estimate or the warning: new form shows the last reading as value; saved untouched = stored, not estimated; cleared = NULL, not estimated, no warning; typed value stored; no earlier reading = empty field; 422 re-render keeps a cleared field; edit form unchanged, estimated rows keep marker and note; refuelling forms unaffected.
- [x] 3.2 Existing estimated rows (set directly in the database) still show "~"/"≈", stay out of `last_known_odometer` and statistics; an import with `odometer_estimated` true still works.

## 4. Docs and checks
- [x] 4.1 `docs/user/records.md` (Service paragraph at line ~31 and the Expense paragraph): prefilled odometer, hints, no estimate; CHANGELOG at release.
- [x] 4.2 Full test suite green; `mkdocs build --strict`.
