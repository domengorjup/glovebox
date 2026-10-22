## Why

Insurance, registration and services come due once a year or so, and Glovebox already knows most of these dates (the coverage end of an insurance expense, soon the "valid until" dates on a vehicle). Today the user has to copy them into a calendar by hand. Reminders should show up where the user already looks: the Glovebox Timeline, Home Assistant's calendars, and the user's own Google or Outlook calendar, with a phone notification if they want one.

## What Changes

- **Reminders per vehicle:** title, category (the expense categories), due date, "remind me N days before", notes, status open or done. Create, edit, mark done, delete.
- **Quick create:**
  - "Remind me" on an expense: due date = coverage end if set, else the expense date + 1 year; lead days editable.
  - From the vehicle's insurance and registration "valid until" dates (added by the concurrent vehicle-details change): a reminder linked to the date that moves with it.
- **Timeline:** a "Due soon" card at the top lists open reminders whose reminder date has arrived (with overdue ones first). A Reminders page (from the card and from Manage) lists all of them. The add chooser gets "Reminder".
- **Delivery to calendars, in tiers:**
  1. **HA calendar sync (add-on mode):** the user picks one HA calendar entity that can create events. Glovebox writes each open reminder as an all-day event, finds the event's uid through HA's REST calendar API and keeps it. Changes use update where the calendar supports it, else delete and re-create, else the reminder says why the event cannot follow. Through HA this reaches Local Calendar, Google Calendar (read/write setup) and CalDAV.
  2. **.ics download** per reminder and for all open reminders: works with any calendar app, including Outlook, and in standalone mode.
  3. **iCal feed:** not in this change (see design D8).
- **Notifications:** no new notification code. The docs give an example HA automation (calendar trigger on the reminders calendar, then `notify.mobile_app_*`).
- **Add-on config:** `homeassistant_api: true`.
- **Backup:** a new `reminders.csv` companion table in the standard format, in the full backup and in imports.
- **Vehicle delete:** the confirmation also counts the vehicle's reminders.

## Capabilities

### New Capabilities
- `reminders`: reminder records, the quick-create paths, the Timeline "Due soon" card and the Reminders page.
- `reminder-delivery`: HA calendar sync, .ics download, failure handling, standalone behaviour, notification guidance.

### Modified Capabilities
- `ha-addon`: Core API access (`homeassistant_api: true`).
- `standard-format`: `reminders.csv` backup table; generated docs cover four tables.
- `data-export`: the full backup contains `reminders.csv`.
- `data-import`: `reminders.csv` accepted as a companion table and restored from backups.
- `vehicle-management`: deleting a vehicle deletes and counts its reminders.

## Impact

- **Code:**
  - `models.py` + migration 0006 (`reminder` table).
  - New `services/reminders.py`, `services/ha_calendar.py` (Core API client), `ics.py`, `web/reminders.py` with templates.
  - Changes to `web/timeline.py`, `web/expenses.py`, `web/vehicles.py`, `manage.html`, `standard.py`, `formatdocs.py`, `exporters/backup.py`, `importers/pipeline.py`, `app.py` (background retry), `config.py` (Supervisor token).
- **Dependencies:** `httpx` moves from dev to runtime; `websockets` is added for the two websocket-only calendar commands (open question Q4).
- **Add-on:** `addon/glovebox/config.yaml` (`homeassistant_api: true`), `DOCS.md`.
- **Docs:** new `docs/user/reminders.md` (with the example automation); `standard-format.md`, `export.md`, `import.md`, `timeline.md`; `docs/dev/design.md` (new elements); `docs/dev/architecture.md` (HA Core API client, written so the sibling app can reuse it).
- **API:** `/api/v1` is unchanged. The stats-api rule that the summary has no reminder fields stays as it is; a reminders endpoint for the companion integration is v2 work.
- **Depends on:** the vehicle-details change for the two "valid until" fields (task group 6 waits for it; everything else is independent).
