## Why

Service and expense entries get the same phone-first quick pages as refuelling, and the Android shortcut can open them directly.

## What Changes

- Quick pages `/quick-service` and `/quick-expense` (title chips, big amount, odometer prefilled with the last reading and saved as an estimate when left as it is, date chip, More). The + chooser opens them; the full forms stay for editing.
- Saving returns to the Timeline with a snackbar and Undo.
- The page script opens `/quick`, `/quick-service` or `/quick-expense` inside the Ingress iframe when the Home Assistant panel URL ends with that path.

## Capabilities

### Modified Capabilities
- `ui-preferences`: vehicle choice on the quick pages.

## Impact

- Code: `web/expenses.py`, `web/timeline.py`, templates `expenses/quick.html`, `add.html`, `timeline.html`, `app.js`, `app.css`, `theme.js`.
- Docs: `docs/dev/design.md`, `docs/user/records.md`, `install.md`, `faq.md`.
