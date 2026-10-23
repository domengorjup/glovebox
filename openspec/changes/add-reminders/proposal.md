## Why

Insurance, registration and services come due once a year or so, and Glovebox already knows most of these dates (the coverage end of an insurance expense, soon the "valid until" dates on a vehicle). Today the user has to copy them into a calendar by hand. Reminders should show up on the Timeline, in a Home Assistant calendar (and through it the user's own calendars), and as a phone notification. Glovebox should pass them on to HA's standard calendar handling and maintain as little as possible itself.

## What Changes

- **Reminders per vehicle:** title, category (the expense categories), due date, "notify N days before" (default 30, set per reminder), notes, status open or done. Create, edit, mark done, delete.
- **Quick create:**
  - "Remind me" on an expense: due date = coverage end if set, else expense date + 1 year.
  - From the vehicle's insurance and registration "valid until" dates (added by the concurrent vehicle-details change): a reminder linked to the date that moves with it.
- **Timeline:** a "Due soon" card at the top for open reminders whose notify date has arrived, overdue first. A Reminders page (from the card and from Manage) lists all of them. The add chooser gets "Reminder".
- **Calendars:**
  1. **HA calendar (add-on mode):** the user picks any calendar entity HA can create events in.
     - Each open reminder becomes an all-day event on the due date, e.g. "Golf: Registration due". The description carries a machine-readable "Notify 30 days before" line and a marker line.
     - Edits and removals are passed on only where the calendar's supported features allow. Otherwise a plain message says to edit it there.
  2. **.ics download per reminder**, with alarms on the notify date and the due date: for Outlook and any other calendar, and in standalone mode.
- **Notifications:** Glovebox sends none. The repository ships one HA automation blueprint (importable with a my.home-assistant.io link). It runs daily, reads the calendar's upcoming events and notifies on the notify date and on the due date. A fallback (a separate heads-up event) is ready in case the test VM check fails.
- **Add-on config:** `homeassistant_api: true`. No new dependencies: the HA client uses only the standard library.
- **Backup:** a new `reminders.csv` companion table in the standard format, in the full backup and in imports.
- **Vehicle delete:** the confirmation also counts the vehicle's reminders.
- **Not in this change:** an iCal feed, integrations for specific calendar providers, recurring reminders.

## Capabilities

### New Capabilities
- `reminders`: reminder records, the quick-create paths, the Timeline "Due soon" card and the Reminders page.
- `reminder-delivery`: HA calendar writing, .ics download, failure handling, standalone behaviour, the notification blueprint.

### Modified Capabilities
- `ha-addon`: Core API access (`homeassistant_api: true`).
- `standard-format`: `reminders.csv` backup table; generated docs cover four tables.
- `data-export`: the full backup contains `reminders.csv`.
- `data-import`: `reminders.csv` accepted as a companion table and restored from backups.
- `vehicle-management`: deleting a vehicle deletes and counts its reminders.

## Impact

- **Code:**
  - `models.py` + migration 0006 (`reminder` table).
  - New `services/reminders.py`, `services/ha_calendar.py` (stdlib REST and minimal websocket client), `ics.py`, `web/reminders.py` with templates.
  - Changes to `web/timeline.py`, `web/expenses.py`, `web/vehicles.py`, `manage.html`, `standard.py`, `formatdocs.py`, `exporters/backup.py`, `importers/pipeline.py`, `app.py` (background retry), `config.py` (Supervisor token).
- **New repo file:** `blueprints/automation/glovebox/reminders.yaml`.
- **Add-on:** `addon/glovebox/config.yaml`, `DOCS.md`.
- **Docs:** new `docs/user/reminders.md`; `standard-format.md`, `export.md`, `import.md`, `timeline.md`; `docs/dev/design.md`; `docs/dev/architecture.md` (HA Core API client, written so the sibling app can reuse it).
- **API:** `/api/v1` is unchanged.
- **Dependencies:** none added.
- **Depends on:** the vehicle-details change, for the two "valid until" fields (task group 6 waits for it).
