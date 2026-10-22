## Context

Glovebox runs as a Home Assistant add-on (Ingress, `panel_admin: true`) and standalone (Docker, optional password). It has no link to HA Core yet. The user wants date reminders per vehicle that reach HA calendars and their own Google/Outlook calendars, and that can produce a phone notification, while staying as simple as possible and using existing HA mechanisms.

**HA calendar facts (checked in HA Core source, 2026-10-21):**
- What each integration can do with events:
  - Local Calendar: create, update and delete.
  - Google Calendar: create (read/write setup only) and delete; no update.
  - CalDAV: create only.
  - Remote Calendar: read-only.
  - Outlook: no official integration.
- The calls:
  - `calendar.create_event` (service) returns no uid, and `calendar.get_events` omits the uid.
  - `GET /api/calendars/<entity>?start=&end=` returns events with their uid.
  - Update and delete are websocket-only: `calendar/event/update` and `calendar/event/delete`.
- Add-on access:
  - With `homeassistant_api: true` an add-on reaches the Core REST API at `http://supervisor/core/api` with `SUPERVISOR_TOKEN`.
  - The websocket proxy URL for add-ons (expected `ws://supervisor/core/websocket`) is **not verified** (task 0.1).
- Calendar triggers with an offset can drive Companion-app notifications.

**Sibling app (Cekar), checked 2026-10-22:** it reads HA user identity from the Ingress `X-Remote-User-*` headers (its design D2) but does not call the Core API yet. Its v1.1 plans "notifications via HA notify (needs `homeassistant_api`)". So Glovebox's Core API client is the first one. It is written as a small, self-contained module and documented in `docs/dev/architecture.md` so that Cekar can reuse the same pattern. Reminders here are per vehicle, not per person, so HA user identity is not needed (D10).

## Goals / Non-Goals

**Goals:**
- Reminders per vehicle with a due date and a lead time, created by hand, from an expense, or from a vehicle's insurance/registration date.
- Visible on the Timeline when they come due.
- Delivered to one user-chosen HA calendar, kept in step when the reminder changes, as far as that calendar allows.
- A per-reminder and an all-open .ics download for any other calendar (Outlook, Apple, Google without HA) and for standalone mode.
- Phone notifications through a documented HA automation, with no notification code in the add-on.

**Non-Goals:**
- Recurring reminders (the renewal flow covers it: record the new expense, tap "Remind me").
- Odometer-based "service due" (v2, companion integration).
- An iCal feed (D8), a native HA calendar entity (v2 companion), HA to-do entities (rejected earlier: no due-date trigger).
- Calendar sync in standalone mode (no HA URL/token settings).
- Reading changes back from the calendar (sync is one way: Glovebox to calendar).
- Reminder fields in `/api/v1` (v2).

## Decisions

### D1. Data model

New table `reminder` (migration 0006):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `uid` | str(36), unique | Random UUID. Stable across backups; used in the .ics `UID`, in the HA event marker (D4) and for import duplicates. |
| `vehicle_id` | FK vehicle, `ON DELETE CASCADE` | Required. |
| `title` | str(200) | Required, e.g. "Insurance renewal". |
| `category` | `ExpenseCategory` | `maintenance` (shown as "Service"), `insurance`, `registration`, `other`. Same enum as expenses. |
| `due_date` | date | Required. |
| `lead_days` | int ≥ 0 | Default 14. **Remind date** = `due_date - lead_days` (computed, not stored). |
| `notes` | text, nullable | |
| `status` | `open` / `done` | Done = dismissed; `done_at` records when. |
| `done_at` | datetime, nullable | |
| `expense_id` | FK expense, nullable, `ON DELETE SET NULL` | "Created from" link, informational only. |
| `vehicle_field` | str(40), nullable | `insurance_valid_until` or `registration_valid_until` (names follow the vehicle-details change). At most one open reminder per vehicle and field. |
| `revision` | int | +1 on every change; the .ics `SEQUENCE`. |
| `cal_entity` | str, nullable | Calendar entity the event lives in. |
| `cal_uid` | str, nullable | Event uid found by the REST lookup (D4). |
| `cal_state` | str | `none`, `pending`, `synced`, `stale`, `error` (D5). |
| `cal_message` | text, nullable | Plain-language reason for `pending`, `stale`, `error`. |
| `cal_synced_revision` | int, nullable | Revision last written to the calendar. |
| `import_batch_id` | FK import batch, nullable | Undo of an import removes its reminders. |
| `created_at`, `updated_at` | datetime | |

"Overdue" = open and `due_date < today`. "Due soon" = open and remind date ≤ today. "Today" is the same local date the Timeline periods use.

The chosen calendar is one setting in the existing `setting` table (`reminders.calendar`, an entity id or empty). It is not chosen per reminder, to keep the UI to one setting.

### D2. UI

All UI work goes through the living mockup `.mockups/ui-v2/` first (task 2.1), then into the app. The standard elements in `docs/dev/design.md` are reused: list card and rows, dialog, buttons, floating button chooser, sub-page header, messages.

- **Timeline "Due soon" card:** a list card above the summary cards. It shows open reminders whose remind date has arrived, filtered by the app-bar vehicle (all vehicles: every vehicle, with the vehicle name in each row). Order: overdue first, then by due date. Each row shows:
  - category icon, title, vehicle;
  - "Due 1 Mar 2027 · in 12 days" or "Overdue by 3 days";
  - a Done icon button on the right.

  Tapping the row opens the edit dialog. The card header has an "All reminders" button. The card is hidden when nothing is due.
- **Reminders page** `/reminders` (sub-page header with back button; also a row "Reminders" under Manage > Garage, with the count of open ones):
  - an "Open" list ordered by due date;
  - a collapsed "Done" section;
  - a "Download all (.ics)" button;
  - the calendar setting (D5): HA calendar select plus a status line.

  A reminder whose `cal_state` is not `synced` or `none` shows a small status line in its row, for example "Not in calendar yet: Home Assistant did not answer. Will retry."
- **Create:** a "Reminder" entry in the floating add chooser opens the reminder dialog. Its fields are vehicle (default as in other forms), title, category, due date, "Remind me … days before", and notes.
- **Edit dialog:** the same fields, plus:
  - "Download .ics", Mark done (or Reopen), Delete;
  - "Created from: <expense title, date>" when linked;
  - the calendar status with a "Sync now" button when the state is not synced.
- **"Remind me" on an expense:** the expense edit dialog gets a "Remind me" button. It opens the reminder dialog pre-filled with:
  - the vehicle and category of the expense;
  - the title "<expense title> renewal";
  - the due date = coverage end if set, else the expense date + 1 year;
  - 14 lead days.

  The add-expense form gets a "Remind me before it runs out" switch, off by default, with the lead days next to it. Saving with the switch on creates the same reminder in one step. Editing the expense later does not move the reminder (the link is informational).
- **From vehicle dates (depends on vehicle-details):** next to each of the "Insurance valid until" and "Registration valid until" fields of the vehicle form, a "Remind me … days before" switch.
  - Switching it on creates the reminder, linked to the field, with the title "Insurance renewal" or "Registration renewal".
  - Changing the date moves the linked open reminder to the new date.
  - Clearing the date or switching off deletes the linked open reminder.
  - When the linked reminder is marked done and a later date is saved, a new linked reminder is created (if the switch is on).

  Why these follow their field and expense links do not: the vehicle field *is* the due date. An expense only suggests one.

### D3. Calendar event shape

One all-day event per open reminder, **on the remind date**, not on the due date. Reasons:
- It is the day the user should act.
- A single generic HA automation can notify at a fixed time of that day (D9) without per-reminder offset arithmetic, which a calendar trigger cannot do.
- Google and Outlook show their own default notification for all-day events on that day.

The due date is in the title and the description:
- **Summary:** `<vehicle>: <title> (due 1 Mar 2027)`. With 0 lead days: `<vehicle>: <title> (due today)`.
- **Description:** the notes (if any), then a final marker line `Glovebox reminder <uid>`.
- **Dates:** `start_date = remind date`, `end_date = remind date + 1 day` (HA's all-day end is exclusive).

This choice is open question Q1.

### D4. HA calendar sync (tier 1)

A small client `services/ha_calendar.py`, used only in add-on mode when `SUPERVISOR_TOKEN` is set.

- **REST** (`httpx`, base `http://supervisor/core/api`, `Authorization: Bearer $SUPERVISOR_TOKEN`, 10 s timeout):
  - `GET /calendars` lists the calendar entities.
  - `GET /states/<entity>` gives `attributes.supported_features`: CREATE_EVENT = 1, DELETE_EVENT = 2, UPDATE_EVENT = 4.
  - `POST /services/calendar/create_event` with `entity_id`, `summary`, `description`, `start_date`, `end_date`.
  - `GET /calendars/<entity>?start=<remind date>&end=<remind date + 1 day>` finds the uid.
- **Websocket** (`websockets`, URL from task 0.1, auth with the same token): `calendar/event/update` and `calendar/event/delete`, used only when the calendar supports them.

**Writing an open reminder whose revision is not yet synced:**
1. **Find first.** Look up the event by the marker line `Glovebox reminder <uid>` in the reminder's event window and in the window of the last synced remind date. If it is found, keep its uid. This makes sync idempotent: a retry after a timeout, or a restore into the same HA, does not create duplicates.
2. **No event yet:** `create_event`, then look up the uid by the marker.
   - If the lookup does not find it (some integrations, e.g. Google, may list a new event only after their next refresh), the state stays `pending` with the message "Waiting for the calendar to list the new event", and the next pass looks again without creating a second event.
3. **Event exists and the reminder changed:**
   - **UPDATE_EVENT supported (Local Calendar):** `calendar/event/update` with the new summary, dates and description.
   - **Only DELETE_EVENT (Google):** delete, then create and look up a new uid.
   - **Create only (CalDAV):** state `stale`, with the message "This calendar can only add events, so the event on 12 Feb cannot follow the change. Delete it in your calendar app, then press Add new event." The **Add new event** button creates a fresh event and forgets the old uid.

**Mark done or delete a reminder:** delete the event if DELETE_EVENT is supported. If not, the event stays and the app says so once ("The calendar event stays: this calendar cannot delete events").

**Change the calendar setting:** open reminders are moved:
- they are deleted from the old calendar where it allows that, otherwise they stay there and the page says how many;
- then they are created in the new one.

Setting the calendar to "None" only removes the events (same rule).

**The calendar select lists** calendars with CREATE_EVENT, each labelled with what it can do: "Adds, changes and removes events", "Adds and removes events" or "Can only add events". Remote Calendar and read-only Google calendars therefore do not appear. The docs recommend a dedicated Local Calendar named "Glovebox reminders" (simplest, full support, easy to target in an automation). For Google: a Google calendar in HA's read/write setup.

### D5. Sync timing and failure handling

- **On save:** sync runs right after the database commit, with the 10 s timeout. A failure never blocks or rolls back the reminder itself.
- **Background retry:** a task started in the app lifespan retries every 15 minutes (and once at startup) every reminder whose `cal_state` is `pending` or `error`, or whose revision differs from `cal_synced_revision`. "Sync now" on the page and in the dialog runs the same pass at once.

| Failure | State | Message (shown on the row and in the dialog) |
|---|---|---|
| HA unreachable, timeout, 5xx | `pending` | "Home Assistant did not answer. Will retry." |
| 401/403 (no `homeassistant_api`, token problem) | `error` | "Glovebox may not use the Home Assistant API. Update or reinstall the add-on." |
| Entity gone (404 on states) | `error` on all, plus a warning at the calendar setting | "Calendar <entity> no longer exists. Choose another calendar." |
| Entity lost CREATE_EVENT (e.g. Google switched to read-only) | `error` | "Calendar <name> no longer accepts new events." |
| Update not supported | `stale` | See D4. |
| Lookup cannot find the created event | `pending` | "Waiting for the calendar to list the new event." |

Errors are also logged.

### D6. .ics download (tier 2)

- **Endpoints:** `GET /reminders/<id>.ics` (one event) and `GET /reminders.ics` (all open reminders, all vehicles or the app-bar vehicle). Served as `text/calendar; charset=utf-8` with `Content-Disposition: attachment`. Standard download buttons, also under Ingress.
- **Writer:** hand-written in `ics.py`, about 40 lines with no new dependency. RFC 5545 rules: CRLF, line folding at 75 octets, escaping `\ ; ,` and newlines.
- **Content:**
  - `VCALENDAR` with `PRODID:-//Glovebox//Reminders//EN`, `VERSION:2.0`, `METHOD:PUBLISH`.
  - Per reminder a `VEVENT`:
    - `UID:<uid>@glovebox`, `SEQUENCE:<revision>`, `DTSTAMP`;
    - `DTSTART;VALUE=DATE` = remind date, `DTEND;VALUE=DATE` = next day;
    - `SUMMARY` and `DESCRIPTION` as in D3;
    - `TRANSP:TRANSPARENT`;
    - a `VALARM` (`ACTION:DISPLAY`, `TRIGGER:PT9H`, i.e. 09:00 on that day).
- **Limits:**
  - Calendar apps that honour `UID` and `SEQUENCE` (Outlook, Apple) update the event when a newer file is opened. Google Calendar's import does not and may add a duplicate; the docs say so.
  - Google ignores `VALARM` on import and uses its default notification.
- **Standalone mode:** this is the only delivery (D11).

### D7. Add-on config

`addon/glovebox/config.yaml` gets `homeassistant_api: true`. Nothing else: no new options, since the calendar is chosen in the UI. `config.py` reads `SUPERVISOR_TOKEN` (present only in add-on mode). Task 0.1 also records whether the change alters the add-on's security rating shown in HA.

### D8. iCal feed (tier 3): not in this change

A subscribable feed (`/reminders/feed.ics?token=…`) was considered and left out:
- Google Calendar and Outlook.com fetch subscribed URLs **from their own servers**, so the feed would have to be reachable from the internet. Ingress requires an HA login, so it would need the API port opened to the internet with a token in the URL. That is a bigger exposure than the feature is worth.
- On the LAN, HA's Remote Calendar could read it, but tier 1 with a Local Calendar already gives HA a calendar with less setup.
- The all-open .ics download covers a one-off import into any app.

It can be added later as its own small change if the user wants a live feed for a LAN client (Thunderbird, Apple Calendar, ICSx5).

### D9. Notifications

The add-on sends no notifications itself. A calendar trigger on the reminders calendar is the existing HA mechanism, and it leaves the choice of device, time and wording to the user. `docs/user/reminders.md` and `DOCS.md` give this example (the trigger offset is checked in task 0.3):

```yaml
alias: Glovebox reminder on my phone
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.glovebox_reminders
    offset: "9:00:00"   # all-day events start at 00:00; notify at 09:00
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Car reminder
      message: "{{ trigger.calendar_event.summary }}"
```

With a shared calendar (e.g. Google), the example adds a condition `{{ 'Glovebox reminder' in trigger.calendar_event.description }}`. Whether the add-on should also create its own HA notification is open question Q3.

### D10. HA user identity

Not used. Reminders belong to a vehicle and the household, as all Glovebox data does. Who gets notified is decided in the user's automation. If per-person reminders are ever needed, Cekar's header approach (its design D2) is the one to reuse.

### D11. Standalone mode

There is no HA connection and no token setting. The calendar setting is hidden and replaced by the line "Calendar sync needs the Home Assistant add-on. Use Download .ics to add reminders to any calendar." `cal_state` stays `none`. The Timeline card, the Reminders page and the .ics downloads work the same.

### D12. Backup and standard format

`reminders.csv` becomes a companion table of the standard format, defined in `standard.py` like `vehicles.csv` and `stations.csv`. It is generated into the docs and the Data Package descriptor.

- **Columns:** `uid`, `vehicle`, `title`, `category`, `due_date`, `lead_days`, `status`, `done_date`, `vehicle_field`, `notes`.
- **Full backup:** always contains it (header only when there are no reminders).
- **Import:** a ZIP member named `reminders` with a `due_date` column is read as this table.
  - A reminder whose `uid` already exists is skipped as a duplicate.
  - The vehicle mapping applies.
  - Undo removes the imported reminders.
- **Not kept:** the expense link (records have no stable id in the CSV; the link is informational) and the calendar state (it belongs to one HA installation). After a restore in add-on mode, the open reminders are synced to the configured calendar. Thanks to the marker lookup (D4) this does not duplicate events that are already there.

### D13. Dependencies

- `httpx` moves from the dev group to runtime dependencies (`uv add httpx`); it is already locked.
- `websockets` is added (`uv add websockets`) for the two websocket commands. It is small, pure Python and widely used.
- **Alternative:** a stdlib-only websocket client like the one in `.dev/release_deploy.py`. It avoids the dependency but is more code to maintain in the app. Open question Q4.

## Risks / Trade-offs

- **Websocket proxy URL unverified** → task 0.1 checks it before any code depends on it. Fallback if add-ons cannot use the websocket: create only, with every calendar treated like CalDAV (D4 `stale` path), and say so in the docs.
- **Google lists new events with a delay** → the lookup stays `pending` and retries without creating a second event, thanks to the marker (D4 step 1).
- **The marker line is visible** in the user's calendar → accepted. It is short and makes sync idempotent without storing anything in HA.
- **The user deletes or edits the event in the calendar** → sync is one way. On the next change Glovebox does not find the uid, so it creates a new event (update or delete of a missing uid is treated as "not found", then create). Edits made in the calendar are overwritten on the next change.
- **Event on the remind date, not the due date** → the calendar does not show the deadline day itself. This is Q1.
- **.ics re-import into Google** may duplicate → documented. Google users are pointed to tier 1.
- **Background task in a single-process app** → one asyncio task with a lock, so a manual "Sync now" and the timer never run at the same time.

## Migration Plan

- Migration 0006 adds the `reminder` table; existing data is untouched. The new add-on version asks for `homeassistant_api`, which HA grants on update.
- **Rollback:** the table is dropped by the downgrade. Events already written to calendars stay there.

## Open Questions

- **Q1. Event date.** Should the calendar event sit on the remind date (proposed: "act now" day, simple notifications) or on the due date (calendar shows the deadline; notifications then need a fixed-offset automation, the same N days for all reminders)?
- **Q2. Outlook.** Do you use Outlook with a Microsoft 365 work account or outlook.com? Tier 2 (.ics) works with both. A HACS Microsoft 365 calendar integration might expose a writable HA calendar, but that is unverified. Should we look into it, or is .ics enough for Outlook?
- **Q3. Add-on notification.** Is the documented calendar automation enough, or should the add-on also create an HA persistent notification on the remind date (no automation needed, but one more piece of code and a setting)?
- **Q4. Dependency.** May we add `websockets` (and move `httpx` to runtime), or do you prefer a stdlib-only client?
- **Q5. Default lead time.** 14 days for everything, or 30 days for insurance and registration?
