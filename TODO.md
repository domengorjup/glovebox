# TODO

## Start here
Ask the user to OK the mockup `.mockups/ui-v2/index.html` (changelog entries of 2026-11-11 in its `NOTES.md`), then implement the items below in the app.

## Next
1. Phone: pinned Save bar in full-screen dialogs so the keyboard never covers it (`.dialog-foot`; viewport meta `interactive-widget=resizes-content`, `visualViewport` handler for iOS). UI only, no OpenSpec; see `NOTES.md` 2026-11-11.
2. Timeline: odometer as a muted third line under the date; estimated readings as "~ 68 390 km" in italics. UI only; see `NOTES.md`.
3. OpenSpec `add-expense-location`: optional Location field on service and expense, suggestions per category, after Odometer on the quick pages.
4. OpenSpec `prefill-expense-odometer`: new service/expense forms prefill the last reading; saved as entered, empty saves nothing, no estimate warning. Big odometer field and hints like Refuelling.
5. Update `docs/dev/design.md` (pinned phone foot, timeline odometer line), `docs/user/records.md`; release 0.4.0; screenshot refresh only where outdated.
6. User-assisted checks on the home server for `add-reminders` 9.4 (own writable calendar) and 9.5 (blueprint notification, .ics on phone/Outlook), the blueprint-import badge; then archive `add-reminders` via the `openspec-archive` skill.
7. Open question for the user: show the calendar's name instead of its entity id in the reminder dialog (one HA call per dialog open).
8. Clean up `haos-test` leftovers (`local_glovebox_dev`, `local_glovebox_dev2`, `core_ssh`, test calendar, test automation) once the user agrees.
