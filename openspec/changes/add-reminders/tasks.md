## 0. Checks on the test VM before building on them
- [x] 0.1 (verified 2026-10-27 with a throwaway debug build `local_glovebox_dev` that ran a probe in the container before the app: `SUPERVISOR_TOKEN` present; REST `http://supervisor/core/api/calendars` listed `calendar.glovebox_test` with features 7; `ws://supervisor/core/websocket` (and `.../core/api/websocket`) gave `auth_required`, then `auth_ok` with the token; the stdlib client created, found by marker, moved with `calendar/event/update` (same uid, new date and summary) and removed with `calendar/event/delete`; a wrong token gave 401 on REST and an auth failure on the websocket; security rating 7 with and without `homeassistant_api: true`, the same as the published 0.2.5) On `haos-test`, use a debug build of the add-on (or a throwaway add-on) with `homeassistant_api: true`. Record:
  - the websocket URL that works for add-ons (expected `ws://supervisor/core/websocket`) and that auth with `SUPERVISOR_TOKEN` succeeds;
  - whether `calendar/event/update` and `calendar/event/delete` work through it, using a stdlib-only client (D8);
  - whether the add-on's security rating changes.

  Update design D7, D8 and Risks with the result.
- [x] 0.2 (verified 2026-10-23 from outside the add-on over the HA API; `http://supervisor/core/api` itself not yet tried, covered by 0.1) On `haos-test`, add a Local Calendar "Glovebox reminders". Through `http://supervisor/core/api`, check:
  - `GET /calendars`, `supported_features` on `GET /states/<entity>` (expected 7), `calendar.create_event` with `start_date`/`end_date` and a description, and the uid lookup by the marker via `GET /calendars/<entity>?start=&end=`;
  - the blueprint sketch of D9 against two test events (30 and 0 days):
    - that the `calendar.get_events` response contains `description`;
    - that the regex and date templates work;
    - that `action: !input notify_action` is accepted;
    - that an all-day event of today is in the window;
    - that each event gives exactly one notification on its days (persistent notification as the action).

  **Decision gate:** if this works, keep D9 as is. If not, switch to the heads-up event fallback of D9 and update D3, D9, `specs/reminder-delivery` and the tasks below before group 4.

## 1. Data model
- [x] 1.1 `Reminder` model and migration 0006 (D1), with tests for the cascade on vehicle delete, `SET NULL` on expense delete, and lead days limited to 0-365.
- [x] 1.2 `services/reminders.py`: create, edit, done, reopen, delete, the remind date, due-soon and overdue queries, the `revision` bump. Unit tests, including the "Due soon" boundaries.

## 2. UI (design iteration first)
- [x] 2.1 (done 2026-10-23; the user has not reviewed the mockup yet) Add to `.mockups/ui-v2/`: the "Due soon" card, the Reminders page (with the calendar setting and status lines), the reminder dialog, "Remind me" in the expense dialog and form, the vehicle date switches. Desktop and phone, light and dark; record it in `NOTES.md`; get the user's feedback before 2.2.
- [x] 2.2 `web/reminders.py` and templates: Reminders page, reminder dialog (default 30 days), Manage row (the add-chooser entry was dropped on 2026-10-26 when + started opening the quick Refuelling form).
- [x] 2.3 Timeline "Due soon" card (`web/timeline.py`, `timeline.html`), filtered by the app-bar vehicle.
- [x] 2.4 "Remind me" on the expense dialog, and the switch on the add-expense form.
- [x] 2.5 New repeated elements added to `docs/dev/design.md`. Screenshots (desktop 1400x900, phone 390x844, light and dark) compared with the mockup.

## 3. .ics download
- [x] 3.1 `ics.py` writer (D6) with tests: folding, escaping, the dates, `UID`/`SEQUENCE`, both alarms, and only the due-date alarm when lead days are 0.
- [x] 3.2 `GET /reminders/<id>.ics` and the download button; tests through Ingress-prefixed URLs. (Route and tests done in `web/reminders.py`; the button comes with the dialog.)

## 4. HA calendar sync
- [x] 4.1 `config.py` reads `SUPERVISOR_TOKEN`; `homeassistant_api: true` goes into `addon/glovebox/config.yaml`.
- [x] 4.2 `services/ha_calendar.py` (stdlib only, D8): list calendars with their features, create, look up by marker, update and delete over the minimal websocket client. Tests against a local fake HA server (REST and websocket), not monkeypatching.
- [x] 4.3 Sync pass (D4), driven only by `supported_features`: find first, create, update or the "edit it there" message, delete on done or delete or the "remove it there" message, and moving to another calendar. Tests for features 7, 3, 5 and 1.
- [x] 4.4 Failure states and messages (D5), the background retry task in the app lifespan with a lock, and "Sync now". Tests for timeout, 401, missing entity, lost create feature, and delayed listing.
- [x] 4.5 Calendar setting on the Reminders page: only calendars that can create events, with the capability labels; the standalone text (D11).

## 5. Notification blueprint
- [x] 5.1 `blueprints/automation/glovebox/reminders.yaml` (from task 0.2) with `source_url` pointing to the file on `master`. Add a test that parses it, with a loader that knows `!input`, and checks the inputs.

## 6. Backup and import
- [x] 6.1 `reminders.csv` in `standard.py`. Regenerate with `uv run python -m glovebox.formatdocs`; the descriptor gets four tables.
- [x] 6.2 Full backup writes `reminders.csv`, respecting a vehicle selection.
- [x] 6.3 Import pipeline reads `reminders.csv`: uid duplicates, errors, preview counts, undo. Round-trip test (backup, restore into an empty database, backup, compare).
- [x] 6.4 The vehicle delete confirmation counts reminders. (Service done: `RecordCounts.reminders`, `ConfirmationRequired.reminders`, reminders deleted with the vehicle; the template line is left.)

## 7. Reminders from vehicle dates (after the vehicle-details change has landed)
- [x] 7.1 The vehicle form switches for insurance and registration "valid until": create, move, delete, and a new reminder after done. Tests through the real forms.

## 8. Docs
- [x] 8.1 `docs/user/reminders.md` and its nav entry:
  - creating reminders and "Due soon";
  - choosing a calendar and what the capability labels mean;
  - the "edit it there" messages;
  - .ics for Outlook and other calendars (alarms may be ignored by some apps);
  - the blueprint-import badge and how to fill in its inputs;
  - standalone mode.
- [x] 8.2 Update `timeline.md`, `export.md`, `import.md`; the add-on `DOCS.md` (Core API use, the blueprint link); README Features. Write `docs/dev/architecture.md` notes on the HA Core API client (REST and websocket through the Supervisor, the token, timeouts) so that the sibling app can reuse them.
- [x] 8.3 `openspec validate add-reminders --strict`, full `uv run pytest`, `mkdocs build --strict`, `formatdocs --check`.

## 9. Verification on the test HA
- [x] 9.1 (verified 2026-10-27 on a local unpublished build `local_glovebox_dev` with the Local Calendar "Glovebox test": create gave one all-day event with the Notify and marker lines; edit kept the event uid and changed date and summary; done and delete removed the event, reopen wrote it again; None removed it and choosing the calendar again wrote it again; moving to another calendar removed it from the old one; re-importing the backup into the same add-on skipped the reminder, and restoring it into a second, empty add-on on the same HA adopted the existing event by its marker, no duplicate) Deploy to `haos-test`. With the Local Calendar "Glovebox reminders":
  - create (event on the due date with the "Notify" and marker lines, uid stored);
  - edit (same uid, updated);
  - mark done (event removed);
  - delete;
  - switch the calendar to None and back;
  - restore a backup into the same HA (no duplicate events).
- [x] 9.2 (verified 2026-10-27: with HA Core stopped, a reminder saved through the Supervisor ingress was stored with "Home Assistant did not answer. Will retry." and the background retry wrote it about 15 minutes later; a browser save during a Core restart cannot reach the add-on because ingress goes through Core. Deleting the Local Calendar integration showed "not available" in the select and, after the next pass, the warning at the setting and on every open reminder; re-adding it with the same name: first run found that untouched reminders were not written again, fixed (D5: a gone calendar flags every open reminder, Sync now checks every open reminder); after the fix both reminders came back on the next pass and through Sync now) Failure cases on `haos-test`:
  - restart HA Core while saving (pending, then synced);
  - delete the Local Calendar integration (error, and a warning at the setting);
  - re-add it and choose it again.
- [x] 9.3 (verified 2026-10-27: imported from its GitHub URL through HA's Import blueprint dialog, stored as `domengorjup/reminders.yaml` with the `source_url`; the my-link redirect opened the blueprint list but not the prefilled dialog in the headless browser, so the badge itself is left for the user's check in 9.5. An automation with `persistent_notification.create` at a set time gave exactly two notifications: "Clio: ... due today" for a reminder due that day and "Golf: ... due in 5 days" for one whose remind date it was; the two later reminders gave none) Import the shipped blueprint on `haos-test` through its import link (from `master` after the push). Create an automation with a persistent notification as the action and check that it fires on a reminder's remind date and due date (test dates set accordingly).
- [ ] 9.4 (user-assisted) A calendar from the user's own account that HA can write to (e.g. Google in the read/write setup, or CalDAV): create, then edit and done. Check that the capability label and the "edit it there" / "remove it there" messages match what that calendar does.
- [ ] 9.5 (user-assisted) Phone: the blueprint's notification through the Companion app's notify action; .ics download and open from the Companion app (Android and iOS); .ics import into Outlook (re-opening after an edit updates the event, the alarms fire).
- [x] 9.6 (done 2026-10-27, `.mockups/ha-v2/screenshots/vm030-*`: Timeline with Due soon, Reminders page, reminder dialog and the quick-add tabs, desktop and phone, light and dark. Matches the mockup except that the dialog names the calendar by entity id ("In calendar calendar.glovebox_test") where the mockup shows its name. Found and fixed: the phone refuel form squeezed the vehicle switch (dialog body children now keep their height)) Screenshots inside HA; review against the mockup.
