## Why

The last odometer was prefilled in the quick service and expense forms, which made it look like a typed value. It is only a suggestion.

## What Changes

- Add forms (quick and full) for service and expense: the odometer field starts empty and shows the last known reading as its placeholder and in the hint. Left empty, behaviour is unchanged: the last reading is saved as an estimate with the warning. Edit forms show no placeholder.

## Capabilities

### Modified Capabilities
- `expense-records`: odometer hint.

## Impact

- Code: `web/expenses.py`, `expenses/quick.html`, `expenses/form.html`, `app.js`. Docs: `records.md`, `design.md`.
