# TODO

## Start here
User checks 0.4.0 on their phone in the HA app: the Save button stays above the keyboard (Refuelling, Service, Expense; also iOS if available), prefilled odometer, Location suggestions.

## Next
1. User-assisted checks on the home server for `add-reminders` 9.4 (own writable calendar) and 9.5 (blueprint notification, .ics on phone/Outlook), the blueprint-import badge; then archive `add-reminders` via the `openspec-archive` skill.
2. Archive `add-expense-location` and `prefill-expense-odometer` via the `openspec-archive` skill once the user is happy with 0.4.0.
3. Refresh docs screenshots only where outdated by 0.4.0 (timeline, service/expense forms); no new ones.
4. Open question for the user: show the calendar's name instead of its entity id in the reminder dialog (one HA call per dialog open).
5. Clean up `haos-test` leftovers (`local_glovebox_dev`, `local_glovebox_dev2`, `core_ssh`, test calendar, test automation) once the user agrees.
