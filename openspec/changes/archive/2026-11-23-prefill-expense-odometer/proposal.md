## Why

A new service or expense form today leaves the Odometer empty, shows the last known reading as a grey placeholder, and saves an empty field as an estimate (`odometer_estimated`) with a warning on the Timeline afterwards. That is indirect: the user cannot see or correct the value that will be stored, and the estimated flag and warning add complexity. The user prefers the obvious behaviour: the field starts with the last known reading as a normal editable value, and what is in the field is what gets stored.

## What Changes

- **Prefill:** a new service or expense form (quick and full) starts with the Odometer field filled with the last known odometer (same definition as today). It is a normal value, editable and clearable.
- **Stored as entered:** a non-empty field is stored with `odometer_estimated` false, also when the user did not change it. An empty field stores no odometer (NULL, not estimated).
- **Removed:** the rule that an empty field is saved as the last known reading with `odometer_estimated` true, and the one-time Timeline warning after saving ("Odometer not entered ... used the last recorded ..." and the "left empty ... recommended" variant).
- **Hints under the field** (as in `.mockups/ui-v2/`): "Last: X km on date" (or "(initial)"); "+N km since the last recorded reading" when the value is higher; red "Lower than the last recorded reading ... Check the number." when lower. They update when the vehicle or date changes. The old wording "Left empty, this is used and marked as estimated" goes.
- **Kept:** the `odometer_estimated` column, the standard-format column, import of it, and the statistics rule that estimated odometers do not count. Existing estimated rows keep their "~" marker on the Timeline and the note on the edit form ("The saved value (...) is an estimate; enter the real reading to replace it").
- **Not changed:** edit forms (they show the stored value; an estimated one stays shown as empty as today), the full and quick refuelling forms (the odometer is required there and has its own hint), the definition of the last known odometer.

## Capabilities

### Modified Capabilities
- `expense-records`: "Odometer default on the expense and service forms" is replaced by the prefill behaviour.

## Impact

- **Code:** `web/expenses.py` (`_save` loses the estimate and the notice, `_form_page`/`expense_new`/quick routes prefill `odometer_km`), `services/records.py` (`last_known_odometer` and `odometer_steps` unchanged), `web/templates/expenses/form.html` and `quick.html` (value instead of placeholder, new hint wording), `web/static/app.js` (`bindOdometerHint`, quick hint: prefill follows vehicle/date changes until the user edits, plus the "+N km" and red states), `web/timeline.py` (`_flash_warnings` loses the two odometer variants; `_flash_saved` and the "~"/"≈" marker stay), `web/preferences.py`/flash handling only where the "estimated"/"missing" notice kinds are set.
- **Tests:** `tests/test_expense_odometer.py`, `tests/test_quick_add.py`, `tests/test_e2e.py` where they assert the estimate or the warning.
- **Docs:** `docs/user/records.md` (Service and Expense paragraphs), `docs/dev/design.md` only if the hint element changes, CHANGELOG at release.
- **Data:** none. No migration.
