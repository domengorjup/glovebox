## Why

Paying a bill often means adding amounts (a service of 120 plus parts of 45.50, minus a discount), and a refuelling total is sometimes a receipt split in two. Today the user has to add them elsewhere and type the result.

## What Changes

- **Cost fields accept a small sum**, Excel style: `=120+45.50-10`, `1,299*(2-1)`. Fields: refuel Total and Price per litre, expense/service Amount, on the quick pages and the full forms. Not litres, not odometer.
- **Grammar** (as in the sibling app Cekar): numbers (decimal comma or point), `+ - * /` with the usual precedence, unary minus, parentheses, optional leading `=`, spaces ignored, at most 200 characters. No functions. Evaluated exactly, then rounded half up to the field's decimals.
- **Server:** a small parser (no `eval`) evaluates the text when it is not a plain number. A malformed calculation ("Not a valid calculation.") or a division by zero ("Can't divide by zero.") is the field's normal validation error, prefixed with the field name; the typed text is kept.
- **Page script:** on change (leaving the field) the expression is replaced by its result; the refuel two-of-three calculation uses the evaluated values. An invalid expression stays as typed and the field is marked invalid.
- **Unchanged:** the number keypad (`inputmode="decimal"`), plain numbers (read by the old rules), rounding and storage, the CSV formats and import, the stats API.

## Capabilities

### Modified Capabilities
- `fuel-records`: Total and Price per litre accept a sum.
- `expense-records`: Amount accepts a sum.

## Impact

- **Code:** `web/formatting.py` (`evaluate_expression`, `parse_money`), `web/refuels.py`, `web/expenses.py`, `web/static/app.js`.
- **Docs:** `docs/user/records.md`; CHANGELOG at release.
- **Data:** none. No new dependencies.
