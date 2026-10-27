## Context

Glovebox runs as a Home Assistant add-on (Ingress, `panel_admin: true`) and standalone (Docker, optional password). It has no link to HA Core yet. The user wants date reminders per vehicle that reach HA calendars and their own calendars, and phone notifications. Glovebox should **pass reminders on to HA's standard calendar handling and maintain as little as possible itself**.

**HA calendar facts (checked in HA Core source, 2026-10-21):**
- Each calendar entity reports in `supported_features` what it can do: CREATE_EVENT = 1, DELETE_EVENT = 2, UPDATE_EVENT = 4. For example:
  - Local Calendar: 7 (create, update, delete);
  - Google Calendar: create and delete in the read/write setup;
  - CalDAV: create only;
  - Remote Calendar: read-only.
- The calls:
  - `calendar.create_event` returns no uid.
  - `GET /api/calendars/<entity>?start=&end=` returns events with their uid.
  - Update and delete are websocket-only: `calendar/event/update` and `calendar/event/delete`.
- Add-on access:
  - With `homeassistant_api: true` an add-on reaches the Core REST API at `http://supervisor/core/api` with `SUPERVISOR_TOKEN`.
  - The websocket URL for add-ons (expected `ws://supervisor/core/websocket`) is **not verified** (task 0.1).

**Sibling app (Cekar), checked 2026-10-22:** it reads HA user identity from the Ingress `X-Remote-User-*` headers (its design D2) but does not call the Core API yet. Its v1.1 plans HA notifications with `homeassistant_api`. Glovebox's Core API client is therefore the first one. It is documented in `docs/dev/architecture.md` so that Cekar can reuse the pattern. Reminders here belong to a vehicle, not a person, so HA user identity is not needed (D10).

## Goals / Non-Goals

**Goals:**
- Reminders per vehicle with a due date and a lead time, created by hand, from an expense, or from a vehicle's insurance/registration date.
- Visible on the Timeline when they come due.
- Written to one user-chosen HA calendar. Edits and deletes are passed on where that calendar supports them.
- A per-reminder .ics download for every other calendar (Outlook, Apple, anything) and for standalone mode.
- Phone notifications through one shipped HA blueprint. Glovebox sends no notifications.

**Non-Goals:**
- Logic per calendar provider beyond reading `supported_features`; any integration of our own (Outlook or other).
- An iCal feed. Google Calendar and Outlook.com fetch subscribed URLs from their own servers, which would need the app exposed to the internet.
- Recurring reminders. The renewal flow covers them: record the new expense, then "Remind me".
- Odometer-based "service due", a native HA calendar entity, reminder fields in `/api/v1` (all v2, companion integration).
- Reading changes back from the calendar. Sync is one way.
- Calendar sync in standalone mode.

## Decisions

### D1. Data model

New table `reminder` (migration 0006):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `uid` | str(36), unique | Random UUID. Stable across backups; used in the .ics `UID`, the event marker (D3) and import duplicates. |
| `vehicle_id` | FK vehicle, `ON DELETE CASCADE` | Required. |
| `title` | str(200) | Required, e.g. "Registration". |
| `category` | `ExpenseCategory` | `maintenance` (shown as "Service"), `insurance`, `registration`, `other`. |
| `due_date` | date | Required. |
| `lead_days` | int, 0 to 365 | Default **30**. Set when the reminder is created; editable. |
| `notes` | text, nullable | |
| `status` | `open` / `done` | Done = dismissed; `done_at` records when. |
| `done_at` | datetime, nullable | |
| `expense_id` | FK expense, nullable, `ON DELETE SET NULL` | "Created from" link, informational only. |
| `vehicle_field` | str(40), nullable | `insurance_valid_until` or `registration_valid_until` (names follow the vehicle-details change). At most one open reminder per vehicle and field. |
| `revision` | int | +1 on every change; the .ics `SEQUENCE` and the "needs sync" check. |
| `cal_entity`, `cal_uid` | str, nullable | Where the event was written, and its uid. |
| `cal_state` | str | `none`, `pending`, `synced`, `unchanged`, `error` (D5). |
| `cal_message` | text, nullable | Plain-language reason when the state is not `synced`. |
| `cal_synced_revision` | int, nullable | Revision last written. |
| `import_batch_id` | FK import batch, nullable | Undo of an import removes its reminders. |
| `created_at`, `updated_at` | datetime | |

Dates used:
- **Remind date** = `due_date - lead_days`. It is computed, not stored.
- **Due soon** = open and remind date ≤ today.
- **Overdue** = open and due date < today.
- "Today" is the same local date the Timeline periods use.

The chosen calendar is one row in the existing `setting` table (`reminders.calendar`: an entity id, or empty for none).

### D2. UI

All UI work goes through the living mockup `.mockups/ui-v2/` first (task 2.1), then into the app. The standard elements from `docs/dev/design.md` are reused: list card and rows, dialog, buttons, floating button, sub-page header, messages.

- **Timeline "Due soon" card:** a list card above the summary cards. It shows open reminders whose remind date has arrived, filtered by the app-bar vehicle (with all vehicles, the vehicle name is in each row). Order: overdue first, then by due date. Each row shows:
  - category icon, title, vehicle;
  - "Due 1 Mar 2027 · in 12 days" or "Overdue by 3 days";
  - a Done icon button.

  Tapping the row opens the edit dialog. The header has an "All reminders" button. The card is hidden when nothing is due.
- **Reminders page** `/reminders` (sub-page header; also a "Reminders" row under Manage > Garage with the open count):
  - open reminders by due date;
  - a collapsed "Done" section;
  - the calendar setting (D4) with a status line.

  A row whose calendar state is not `synced` or `none` shows its message in one line.
- **Reminder dialog** (from "Add reminder" on the Reminders page):
  - fields: vehicle, title, category, due date, "Notify … days before" (default 30), notes;
  - in the edit dialog also: Download .ics, Mark done (or Reopen), Delete, "Created from: <expense>" when linked, and "Sync now" when not synced.
- **"Remind me" on an expense:** a button in the expense edit dialog opens the reminder dialog pre-filled with:
  - the vehicle and category of the expense;
  - the title "<expense title> renewal";
  - the due date = coverage end if set, else expense date + 1 year;
  - 30 days.

  The add-expense form has a "Remind me before it runs out" switch, off by default, with the days next to it. Later edits of the expense do not move the reminder.
- **From vehicle dates (depends on vehicle-details):** next to each "Insurance valid until" / "Registration valid until" field, a "Remind me … days before" switch (default 30).
  - Switch on: a reminder linked to the field.
  - Date changed: the linked open reminder moves with it.
  - Date cleared or switch off: the linked open reminder is deleted.
  - A new date after the linked reminder was done: a new linked reminder.

  The vehicle field *is* the due date, so the reminder follows it. An expense only suggests one.

### D3. Calendar event shape

One all-day event per open reminder, **on the due date**: `start_date = due_date`, `end_date = due_date + 1 day` (HA's all-day end is exclusive).

- **Summary:** `<vehicle>: <title> due`, e.g. "Golf: Registration due".
- **Description**, one item per line:
  ```
  <notes, if any>
  Notify 30 days before
  Glovebox reminder 6f1c…-uuid
  ```

The `Notify <N> days before` line is machine-readable. The blueprint (D9) reads it, so the lead time travels with the event and nothing else has to be stored in HA. The marker line identifies Glovebox's events, for the uid lookup and for the blueprint.

### D4. HA calendar sync (tier 1)

Glovebox relays to whatever calendar entity the user chooses and adapts only to that entity's `supported_features`.

- **Calendar select:** it lists every entity from `GET /api/calendars` whose `supported_features` include CREATE_EVENT. That covers any integration or add-on the user installs that HA lets create events in, without knowing which one it is. Each entry shows what it can do: "Adds, changes and removes events", "Adds and removes events", "Adds and changes events" or "Only adds events".
- **Write (open reminder whose revision is not yet synced):**
  1. **Find first.** Look up an existing event by its marker with `GET /api/calendars/<entity>`, in a window around the current and the last synced due date. This keeps retries and restores from creating duplicates, and finds the uid.
  2. **No event:** `calendar.create_event`, then the same lookup to store the uid.
     - If the event is not listed yet, the state stays `pending` ("Waiting for the calendar to list the new event"), and the next pass looks again without creating another event.
  3. **Event exists and the reminder changed:**
     - With UPDATE_EVENT: `calendar/event/update`.
     - Without it: the event is left alone. The state is `unchanged` with the message "This calendar can't change events; edit it there."
- **Mark done or delete:**
  - With DELETE_EVENT: `calendar/event/delete`.
  - Without it: the event stays, with the message "This calendar can't remove events; remove it there."
- **Changing the calendar setting:**
  - Open reminders are written to the new calendar.
  - Their events in the old one are deleted where the old calendar supports it. Otherwise the page says how many stay there.
  - "None" stops writing and deletes where supported.

No delete-and-recreate, no per-provider rules.

**Recommended in the docs:** a dedicated Local Calendar named "Glovebox reminders". It supports everything, and the blueprint can target it.

### D5. Sync timing and failures

- **On save:** sync runs right after the database commit, with a 10 s timeout. A failure never blocks or undoes saving the reminder.
- **Background retry:** a task in the app lifespan (one asyncio task with a lock) retries every 15 minutes, and once at startup, every reminder in `pending` or `error`, or whose `revision` differs from `cal_synced_revision`.
- **Sync now:** runs the same pass at once, and also checks every open reminder against the calendar (one lookup by the marker each), so events lost in the calendar are written again (found on `haos-test` 2026-10-27: a Local Calendar deleted and re-added came back empty while untouched reminders still counted as synced).

| Failure | State | Message |
|---|---|---|
| HA unreachable, timeout, 5xx | `pending` | "Home Assistant did not answer. Will retry." |
| 401/403 | `error` | "Glovebox may not use the Home Assistant API. Update or reinstall the add-on." |
| Entity gone | `error` for every open reminder, changed or not (plus a warning at the setting); the next pass after it is back writes them again | "Calendar <entity> no longer exists. Choose another calendar." |
| Entity no longer creates events | `error` | "Calendar <name> no longer accepts new events." |
| Change or removal not supported | `unchanged` | See D4. |
| Created event not listed yet | `pending` | "Waiting for the calendar to list the new event." |

Errors are also logged.

### D6. .ics download (tier 2)

- **Endpoint:** `GET /reminders/<id>.ics`, served as `text/calendar; charset=utf-8` with `Content-Disposition: attachment`. A standard download button in the reminder dialog, working under Ingress and standalone.
- **Writer:** hand-written in `ics.py` (about 40 lines, no dependency), following RFC 5545: CRLF line ends, folding at 75 octets, escaping of `\ ; ,` and newlines.
- **Content:**
  - `VCALENDAR` with `PRODID:-//Glovebox//Reminders//EN`, `VERSION:2.0`, `METHOD:PUBLISH`.
  - One `VEVENT`:
    - `UID:<uid>@glovebox`, `SEQUENCE:<revision>`, `DTSTAMP`;
    - `DTSTART;VALUE=DATE` = due date, `DTEND;VALUE=DATE` = the next day;
    - `SUMMARY` and `DESCRIPTION` as in D3;
    - `TRANSP:TRANSPARENT`.
  - **Alarms**, both `ACTION:DISPLAY` and relative to the start:
    - one at 09:00 on the remind date: `TRIGGER:-P<N-1>DT15H` (N = lead days ≥ 1);
    - one at 09:00 on the due date: `TRIGGER:PT9H`.
- This is the path for Outlook and every other calendar. Apps that honour `UID` and `SEQUENCE` update the event when a newer file is opened. Some apps ignore imported alarms and use their own defaults; the docs say so.

### D7. Add-on config

`addon/glovebox/config.yaml` gets `homeassistant_api: true` and no new options. `config.py` reads `SUPERVISOR_TOKEN`, which is present only in add-on mode. Task 0.1 records whether the change alters the add-on's security rating.

### D8. Core API client and dependencies

`services/ha_calendar.py` uses only the standard library. No new dependencies.

- **REST:** `urllib.request` against `http://supervisor/core/api` with the Bearer token and a 10 s timeout, called from a worker thread. Calls: `GET /calendars`, `GET /states/<entity>`, `POST /services/calendar/create_event`, `GET /calendars/<entity>?start=&end=`.
- **Websocket (update and delete only):** a minimal client over plain `ws://` inside the Supervisor network, about 80 lines:
  - opening the connection: the HTTP upgrade handshake, the `auth` message with the same token, then `auth_ok`;
  - messages: masked text frames out, unfragmented text frames in, answers to pings;
  - one command per connection.

  The same approach already works in the repository's `.dev/release_deploy.py`.

Reasons:
- There is no TLS, no fragmentation and no long-lived connection to deal with.
- The two commands are short request/answer pairs.

If task 0.1 shows the Supervisor needs anything the small client cannot do, the fallback is the `websockets` package (pure Python), added with `uv add`.

### D9. Notifications: one shipped blueprint

Glovebox sends no notifications. The repository ships an automation blueprint, `blueprints/automation/glovebox/reminders.yaml`, with a `source_url` so that it can be imported with the my.home-assistant.io blueprint-import link. The link is shown as a badge in `docs/user/reminders.md` and in `DOCS.md`.

**Inputs:**
- `calendar` (entity selector, domain `calendar`);
- `notify_time` (time selector, default 09:00);
- `notify_action` (text, the notify action to call, e.g. `notify.mobile_app_my_phone`; default `notify.notify`).

**Behaviour:**
- Runs daily at `notify_time`.
- Calls `calendar.get_events` on the calendar for the next 366 days (lead days are capped at 365), with `response_variable`.
- For each event whose description contains `Glovebox reminder`, reads N from `Notify (\d+) days? before` (0 if missing).
- Notifies when *start − N days* is today ("Golf: Registration due in 30 days") or when start is today ("Golf: Registration due today").

**Blueprint** (verified form, `blueprints/automation/glovebox/reminders.yaml`):

```yaml
blueprint:
  name: Glovebox reminders
  description: >-
    Sends a notification on the remind date and on the due date of each
    Glovebox reminder found in a calendar.
  domain: automation
  source_url: https://github.com/domengorjup/glovebox/blob/master/blueprints/automation/glovebox/reminders.yaml
  input:
    calendar:
      name: Calendar
      description: The calendar Glovebox writes its reminders to.
      selector:
        entity:
          domain: calendar
    notify_time:
      name: Time of day
      selector:
        time:
      default: "09:00:00"
    notify_action:
      name: Notify action
      description: The action to call, for example notify.mobile_app_my_phone.
      selector:
        text:
      default: notify.notify
mode: single
triggers:
  - trigger: time
    at: !input notify_time
actions:
  - variables:
      cal: !input calendar
  - action: calendar.get_events
    target:
      entity_id: !input calendar
    data:
      duration:
        days: 366
    response_variable: agenda
  - repeat:
      for_each: >-
        {{ agenda[cal].events
           | selectattr('description', 'defined')
           | selectattr('description', 'search', 'Glovebox reminder')
           | list }}
      sequence:
        - variables:
            lead: >-
              {{ (repeat.item.description
                  | regex_findall('Notify (\\d+) days? before')
                  | first | default(0)) | int }}
            days_left: >-
              {{ ((repeat.item.start | as_datetime).date() - now().date()).days }}
        - if: "{{ days_left == lead or days_left == 0 }}"
          then:
            - action: !input notify_action
              data:
                title: Car reminder
                message: >-
                  {{ repeat.item.summary }}
                  {{ 'today' if days_left == 0 else 'in ' ~ days_left ~ ' days' }}
```

The blueprint works with any calendar Glovebox writes to, including one HA only reads (e.g. Google), because it reads only the events.

**Fallback, gated on task 0.2.** If `calendar.get_events` does not return `description`, or the templates above cannot be made to work, Glovebox also writes a separate heads-up event on the remind date: summary "Golf: Registration due in 30 days", the same marker plus the suffix `heads-up`. That event gets its own `cal_headsup_uid` column and follows the same sync rules. The blueprint then becomes a plain calendar trigger at event start (offset `notify_time`) that notifies with the event summary for events carrying the marker. Task 0.2 decides which variant ships and updates D3, D9 and the specs.

**Verified on haos-test, 2026-10-23** (HA 2026.10.2, Local Calendar "Glovebox test", from outside the add-on over REST and websocket):
- `calendar.get_events` (REST `POST /api/services/calendar/get_events?return_response`) returns `description` for Local Calendar events (empty string if none). An all-day event of today is in the 366-day window. The heads-up fallback is not needed.
- `GET /api/calendars/<entity>?start=&end=` returns `uid` per event; `supported_features` of the Local Calendar is 7; `calendar.create_event` with `start_date`/`end_date` and a description works.
- The regex, the `search` test and the date maths pick the right events; a missing "Notify" line gives 0; events with an empty description are skipped.
- `action: !input notify_action` is accepted. With `persistent_notification.create`, one run on 2026-10-23 gave exactly two notifications: the event due today ("today") and the event due in 30 days with lead 30 ("in 30 days"); events due in 10 and 60 days gave none.
- Correction to the earlier sketch: the `due` variable became a string ("2026-10-23"), so `due - now().date()` would fail (not run in that form); days_left is now computed in one expression.
- Blueprint saved with websocket `blueprint/save` (domain `automation`, path `glovebox/reminders.yaml`) and the automation created from it.
- `calendar/event/update` and `calendar/event/delete` (websocket, `entity_id`, `uid`, `event` with `summary`, `dtstart`, `dtend`, `description`) work on the Local Calendar from outside; the in-add-on URL `ws://supervisor/core/websocket` is still to be checked (task 0.1). Timed events were not tested.

### D10. HA user identity

Not used. Reminders belong to a vehicle and the household, as all Glovebox data does. Who is notified is chosen in the blueprint. If per-person reminders are ever needed, Cekar's header approach (its design D2) is the one to reuse.

### D11. Standalone mode

There is no HA connection and no token setting. The calendar setting is replaced by the line "Calendar sync needs the Home Assistant add-on. Use Download .ics to add a reminder to any calendar." The Timeline card, the Reminders page and the .ics download work the same.

### D12. Backup and standard format

`reminders.csv` becomes a companion table of the standard format, defined in `standard.py` and generated into the docs and the Data Package descriptor.

- **Columns:** `uid`, `vehicle`, `title`, `category`, `due_date`, `lead_days`, `status`, `done_date`, `vehicle_field`, `notes`.
- **Full backup:** always contains it (header only when there are no reminders).
- **Import:** a ZIP member named `reminders` with a `due_date` column is read as this table.
  - A known `uid` is skipped as a duplicate.
  - The vehicle mapping applies.
  - Undo removes the imported reminders.
- **Not kept:** the expense link and the calendar state. After a restore in add-on mode, open reminders are written to the configured calendar. The find-first lookup (D4) reuses events that are already there.

## Risks / Trade-offs

- **The websocket URL for add-ons is unverified** → task 0.1 checks it first. If add-ons cannot use the websocket, sync is create-only for every calendar: changes and removals get the "edit it there" messages. The docs say so.
- **`get_events` may lack `description`** → task 0.2 checks it; the D9 fallback (heads-up event) is ready.
- **The marker and "Notify" lines are visible** in the user's calendar → accepted. They are short and keep HA free of extra state.
- **Edits made in the calendar** are overwritten by the next change in Glovebox. If the user deleted the event, the next change creates a new one (a missing uid is treated as no event).
- **A calendar without update shows outdated events** after edits → the plain message tells the user to edit there. This is the price of having no per-provider logic.
- **A hand-written websocket client** is code to maintain → it is kept to the two commands, and tests run it against a local fake server.

## Migration Plan

- Migration 0006 adds the `reminder` table; existing data is untouched. The add-on update asks for `homeassistant_api`.
- **Downgrade:** drops the table. Events in calendars stay.

## Open Questions

None. The user's decisions of 2026-10-23 settled the event date, notifications, scope, default lead time and dependencies. The only open point is technical and is decided by task 0.2: blueprint over `get_events`, or the heads-up event fallback (D9).
