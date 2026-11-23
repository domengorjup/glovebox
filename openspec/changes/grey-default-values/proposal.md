## Why

Two new-entry forms ask for values the app already knows. The refuelling form makes the user type a price per litre that is nearly always the last one. The service/expense form fills the Odometer with a real value that looks typed. Showing the known value in grey (the normal placeholder) and using it when the field stays empty is simpler to read and to correct.

## What Changes

- **Refuelling (quick and full, add forms only):** the Price / litre field shows the last price per litre of the same vehicle in grey. If the user types no price and only one of litres / total, the grey price is used to calculate the other one. If litres and total are both typed, the price is calculated from them as today and the grey value is ignored. The server applies the same rule on save.
- **Service and expense (quick and full, add forms only):** the Odometer field no longer starts with a value. The last known odometer is its grey placeholder, and an empty field is saved as that reading (`odometer_estimated` false). A typed value is saved as typed.
- **Removed:** the prefilled odometer value. The way to save no odometer at all (clearing the field) goes: an empty field now means "use the shown reading". Without any earlier reading the field stays empty and no odometer is stored.
- **Kept:** the odometer hints ("Last: ...", "+N km ...", red "Lower than ..."), edit forms, money expressions, existing estimated rows.

## Capabilities

### Modified Capabilities
- `fuel-records`: new requirement "Default price per litre" (grey value, two-of-three rule).
- `expense-records`: "Odometer default on the expense and service forms" now uses a grey placeholder and an empty field stores the shown reading.

## Impact

- **Code:** `services/records.py` (last price per litre), `web/refuels.py`, `web/expenses.py`, templates `refuels/quick.html`, `refuels/form.html`, `expenses/quick.html`, `expenses/form.html`, `_macros.html` (odometer hint flag), `static/app.js` (`bindCalc`, `bindOdometerHint`, quick refuel Save check).
- **Tests:** `tests/test_e2e.py` and the odometer/quick-add tests.
- **Docs:** `docs/user/records.md`.
- **Data:** none, no migration.
