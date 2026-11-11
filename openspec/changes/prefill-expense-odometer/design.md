## Context

`openspec/specs/expense-records/spec.md` ("Odometer default on the expense and service forms") says: odometer optional, the field starts empty with the last known reading as placeholder, an empty field is saved as that reading with `odometer_estimated` true, and the Timeline shows a one-time warning. The code for this is `web/expenses.py::_save` (calls `records.last_known_odometer`, replaces the data with `odometer_estimated=True`, sets a `("estimated", km)` or `("missing", None)` notice), `web/timeline.py::_flash_warnings`, `bindOdometerHint` and the quick hint in `web/static/app.js`, and the hint wording in `form.html` and `quick.html`.

The user decided to prefill as a normal value. The mockup `.mockups/ui-v2/` (NOTES.md, 2026-11-11) already has the hint wording: "Last: 75,892 km on 9 Oct", "+N km since the last recorded reading (9 Oct)", red "Lower than the last recorded reading ... Check the number."

## Goals / Non-Goals

**Goals:** a visible, editable odometer on new service/expense forms; no hidden estimating; less code in `_save`.

**Non-Goals:** removing `odometer_estimated` (existing data, backups and imports use it); changing statistics; changing the refuelling forms; migrating existing estimated rows.

## Decisions

### D1. Prefill on new forms only
- Add forms (`/expenses/new`, quick service and expense) set `odometer_km` to the last known odometer of the selected vehicle on the entry date, formatted like the value of an entered odometer (`f"{km:g}"`). Without an earlier reading it stays empty.
- Edit forms are unchanged: they show the stored value, and an estimated one is shown empty as before (`_form_from_expense`), with the note about the estimate.
- A re-rendered add form after a validation error keeps what the user entered, including a cleared field: the prefill applies only to the first GET, not to the 422 re-render.
- `last_known_odometer` keeps its definition (highest entered odometer on or before the date, refuels and non-estimated expenses, or the initial odometer if higher), so estimated rows still never feed it.

### D2. Browser behaviour
The server prefills for the vehicle and date it knows. In the browser, when the user changes the vehicle or the date, the field follows the new last known value (data already in `odometer_steps`) **only while the user has not edited the field** (track a "touched" flag on `input`). Once edited or cleared, it is left alone. This replaces the placeholder logic in `bindOdometerHint` and the quick hint.

### D3. Save
`_save` stores the parsed odometer as entered with `odometer_estimated` false; an empty field stores `NULL`. The `last_known_odometer` lookup, the `replace(...)` and the notices are removed from `_save`. `ExpenseInput.odometer_estimated` and `records._apply_expense` keep the flag (`data.odometer_estimated and data.odometer_km is not None`), because imports and tests still set it; the web forms never do.

### D4. After-save warning: removed
The Timeline warning goes entirely. The "estimated" variant is gone with the estimate. The "left empty, recommended" variant is dropped too: with a prefilled field an empty value means the user cleared it, or the vehicle has no earlier reading and the hint under the field already said so. A nag after the fact helps little (recommendation, user's decision). `_flash_warnings` keeps its structure only if other notices use it (check `preferences.set_flash` callers; otherwise remove the odometer branches and the unused notice kinds). The one-time snackbar of the quick pages ("Service saved", Undo) is unchanged.

### D5. Hints
Under the field, plain grey help text, as in the refuelling form:
- Before typing: `Last: 75,892 km on 9 Oct` (`(initial)` for the vehicle's initial odometer); without a reading: `No earlier reading for this vehicle.`
- Typed or prefilled value above the last: `+N km since the last recorded reading (9 Oct).` With the prefill unchanged this reads +0 km, so show the "Last: ..." text while the value equals the last known one.
- Lower: red `Lower than the last recorded reading (75,892 km, 9 Oct). Check the number.` (does not block saving).
- The hint refers to the date and vehicle currently chosen. The full forms use the same wording (help line below the Odometer next to Date); the "Left empty, this is used and marked as estimated" sentences are removed from `form.html`, `quick.html` and `app.js`.

### D6. Existing estimated rows
Unchanged: Timeline "~"/"≈" marker (`web/timeline.py::_expense_entry`), the edit-form note (`estimated_km` in `_form_page`), exclusion from statistics (`services/stats.py`, `records.last_known_odometer`, `odometer_steps`), standard column `odometer_estimated`, import mapping. They fade out as users correct those rows.

### D7. Refuelling
The refuelling forms (quick and full) are unaffected: the odometer stays required there with its own "Last: ... / +N km since the last refuelling" hint.

## Risks / Trade-offs

- **A prefilled value can be saved untouched and be wrong** (the car has been driven since). It is stored as a real reading with no flag, which affects cost-per-km distances if used as an endpoint. Accepted by the user's decision; the "+N km" and red hints and the visible value are the safeguard. Statistics that use expense odometers can be slightly off for such rows.
- **Behavioural change visible to users:** an empty field no longer gets a value. Documented in `docs/user/records.md` and the CHANGELOG.
