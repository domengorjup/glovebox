## 0. Checks on the test VM before building on them
- [ ] 0.1 On `haos-test`, use a debug build of the add-on (or a throwaway add-on) with `homeassistant_api: true`. Record:
  - the websocket URL that works for add-ons (expected `ws://supervisor/core/websocket`) and that auth with `SUPERVISOR_TOKEN` succeeds;
  - whether `calendar/event/update` and `calendar/event/delete` are allowed through it;
  - whether the add-on's security rating in HA changes.

  Update design D4, D7 and the Risks section with the result. If the websocket is not usable, switch D4 to the create-only fallback before group 4.
- [ ] 0.2 On `haos-test`, add a Local Calendar "Glovebox reminders". Through `http://supervisor/core/api`, check:
  - `GET /calendars` and `supported_features` on `GET /states/<entity>` (expected 7);
  - `calendar.create_event` with `start_date`/`end_date` and a description;
  - the uid lookup via `GET /calendars/<entity>?start=&end=` by the marker line.
- [ ] 0.3 On `haos-test`, check that a calendar trigger with `offset: "9:00:00"` fires at 09:00 on an all-day event's day, using a persistent notification as the action. Fix the example in D9 if the offset syntax differs.

## 1. Data model
- [ ] 1.1 `Reminder` model and migration 0006 (D1), with tests for the cascade on vehicle delete and `SET NULL` on expense delete.
- [ ] 1.2 `services/reminders.py`: create, edit, done, reopen, delete, the remind date, due-soon and overdue queries, `revision` bump. Unit tests, including the "Due soon" boundaries.

## 2. UI (design iteration first)
- [ ] 2.1 Add to `.mockups/ui-v2/`: the "Due soon" card, the Reminders page (with the calendar setting and status lines), the reminder dialog, "Remind me" in the expense dialog and form, the vehicle date switches. Desktop and phone, light and dark; record it in `NOTES.md`; get the user's feedback before 2.2.
- [ ] 2.2 `web/reminders.py` and templates: Reminders page, reminder dialog, add-chooser entry, Manage row.
- [ ] 2.3 Timeline "Due soon" card (`web/timeline.py`, `timeline.html`), filtered by the app-bar vehicle.
- [ ] 2.4 "Remind me" on the expense dialog and the switch on the add-expense form.
- [ ] 2.5 New repeated elements added to `docs/dev/design.md`. Screenshots (desktop 1400x900, phone 390x844, light and dark) compared with the mockup.

## 3. .ics download
- [ ] 3.1 `ics.py` writer (D6) with tests for folding, escaping, the dates, `UID`/`SEQUENCE` and `VALARM`.
- [ ] 3.2 `GET /reminders/<id>.ics` and `GET /reminders.ics`, download buttons, tests through Ingress-prefixed URLs.

## 4. HA calendar sync
- [ ] 4.1 `uv add httpx websockets` (after Q4 is answered; else a stdlib client). `config.py` reads `SUPERVISOR_TOKEN`. `homeassistant_api: true` goes into `addon/glovebox/config.yaml`.
- [ ] 4.2 `services/ha_calendar.py`: list calendars with their features, create, look up by marker, update, delete. Tests against a fake HA (a local test server, not monkeypatching).
- [ ] 4.3 Sync pass (D4): find-first, create, update / delete-and-recreate / stale, done and delete, and moving to another calendar. Tests per calendar capability (7, 3, 1).
- [ ] 4.4 Failure states and messages (D5), the background retry task in the app lifespan with a lock, and "Sync now". Tests for timeout, 401, missing entity, lost create feature, and delayed listing.
- [ ] 4.5 Calendar setting on the Reminders page (only calendars that can create, with capability labels; the standalone text of D11).

## 5. Backup and import
- [ ] 5.1 `reminders.csv` in `standard.py`. Regenerate with `uv run python -m glovebox.formatdocs`; the descriptor gets four tables.
- [ ] 5.2 Full backup writes `reminders.csv`; vehicle selection respected.
- [ ] 5.3 Import pipeline reads `reminders.csv`: uid duplicates, errors, preview counts, undo. Round-trip test (backup, restore into an empty database, backup, compare).
- [ ] 5.4 The vehicle delete confirmation counts reminders.

## 6. Reminders from vehicle dates (after the vehicle-details change has landed)
- [ ] 6.1 The vehicle form switches for insurance and registration "valid until": create, move, delete, and a new reminder after done. Tests through the real forms.

## 7. Docs
- [ ] 7.1 `docs/user/reminders.md` and its nav entry:
  - creating reminders, "Due soon", the calendar choice and what each calendar type can do;
  - the .ics limits (Google import duplicates);
  - the example automation (D9);
  - standalone mode.
- [ ] 7.2 Update `timeline.md`, `export.md` and `import.md`; the add-on `DOCS.md` (Core API use, the automation); README Features. Write `docs/dev/architecture.md` notes on the HA Core API client (REST and websocket through the Supervisor, the token, timeouts) so that the sibling app can reuse them.
- [ ] 7.3 `openspec validate add-reminders --strict`, full `uv run pytest`, `mkdocs build --strict`, `formatdocs --check`.

## 8. Verification on the test HA
- [ ] 8.1 Deploy to `haos-test`. With the Local Calendar "Glovebox reminders":
  - create a reminder (event appears on the remind date, uid stored);
  - edit the due date (same uid, moved);
  - mark done (event removed);
  - delete;
  - switch the calendar to None and back;
  - restore a backup into the same HA (no duplicate events).
- [ ] 8.2 Failure cases on `haos-test`:
  - restart HA Core while saving (pending, then synced);
  - delete the Local Calendar integration (error, and a warning at the setting);
  - re-add it and choose it again.
- [ ] 8.3 The example automation from the docs creates a persistent notification at the expected time (the phone part is user-assisted, 8.6).
- [ ] 8.4 (user-assisted) Google Calendar in HA's read/write setup with the user's account: create, edit (delete and re-create), done (removed), and the delayed listing. Also check that Google's default notification arrives on the remind date.
- [ ] 8.5 (user-assisted) CalDAV calendar with the user's server: create, the edit shows "out of date" with "Add new event", and done leaves the event with a message.
- [ ] 8.6 (user-assisted) Phone:
  - the Companion app notification from the example automation;
  - .ics download and open in the Companion app (Android and iOS);
  - .ics import into Outlook (re-open after an edit updates the event) and into Google Calendar.
- [ ] 8.7 Screenshots inside HA; review against the mockup.
