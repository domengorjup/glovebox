## Why

Logging a refuelling at the pump needs fewer fields and bigger controls than the full form. The user approved a phone-first quick page in the UI mockup.

## What Changes

- **Quick-add page** `/quick`: full screen on phones, a small dialog on desktop; the + chooser's "Refuelling" entry opens it. The full form stays for editing.
- **Vehicle choice:** a segmented choice shown only with more than one active vehicle (the full forms keep their dropdown). Default as before: app-bar vehicle, else the last specific one.
- **Station chips:** the last station used with the vehicle plus its two most frequent ones, and "Other" for the normal station select.
- **Saving:** the time is the current time; the same validation as the full form. The Timeline then shows a snackbar "Refuel saved" with litres, total, consumption of the tank (when there is one) and Undo, which deletes the new refuel.
- **Not included:** any change to the data model or the API.

## Capabilities

### Modified Capabilities
- `ui-preferences`: vehicle choice in entry forms.

## Impact

- Code: `web/refuels.py`, `web/timeline.py`, `services/preferences.py` (flash data), templates `refuels/quick.html`, `refuels/_station_picker.html`, `timeline.html`, `app.js`, `app.css`.
- Docs: `docs/dev/design.md`, `docs/user/records.md`, `docs/user/install.md`, `docs/user/faq.md`.
