# TODO

## Start here
User checks 0.6.0 on their phone in the HA app: Save in the top bar (Refuelling, Service, Expense, edit forms), grey price per litre and grey odometer used when left as they are, a calculation like `=12.50+3`. `haos-test` is stopped (user's request, 2026-11-20); 0.5.0 and 0.6.0 were never run there.

## Next
1. Archive `grey-default-values` via the `openspec-archive` skill once the user is happy with 0.6.0.
2. User-assisted checks on the home server for `add-reminders` 9.4 (own writable calendar) and 9.5 (blueprint notification, .ics on phone/Outlook), the blueprint-import badge; then archive `add-reminders` via the `openspec-archive` skill.
3. Refresh docs screenshots only where outdated since 0.4.0 (timeline, refuel/service/expense forms); no new ones.
4. Open question for the user: show the calendar's name instead of its entity id in the reminder dialog (one HA call per dialog open).
5. Clean up `haos-test` leftovers (`local_glovebox_dev`, `local_glovebox_dev2`, `core_ssh`, test calendar, test automation) once the user agrees.
