# Reminders

A reminder tells you that something is coming up for a vehicle: insurance or registration runs out, a service is due. Glovebox shows reminders on the Timeline, can put them in a Home Assistant calendar, and a ready-made automation can send them to your phone.

## What a reminder holds

| Field | Meaning |
|---|---|
| Vehicle | The vehicle it belongs to |
| Title | For example "Registration renewal" |
| Category | Service, insurance, registration or other |
| Due date | The day it is due |
| Notify N days before | How many days ahead it counts as "due soon". The default is 30. |
| Notes | Optional |

A reminder is **open** until you mark it done (**Done** on a row, **Mark done** in the reminder). A done reminder stays in a collapsed list on the Reminders page, and **Reopen** brings it back. **Delete** removes it for good. Open a reminder from the Timeline or the Reminders page to change any of this.

## Creating a reminder

- **From the Timeline:** tap **+** and choose **Reminder**.
- **From an expense:** open the expense and tap **Remind me**. The reminder form is filled in for you: same vehicle and category, the title "*expense title* renewal", and the due date. The due date is the coverage end if the expense has one, otherwise the expense date plus one year. You can change everything before saving.
- **While adding an expense:** switch on **Remind me before it runs out** on the add-expense forms and set the days. It makes the same reminder when you save. Later edits of the expense do not move the reminder.
- **From the vehicle dates:** in **More details** of the vehicle form, the insurance and registration *valid until* dates each have a switch **Remind me before it ends**, with the number of days to notify before. This reminder follows the date: change the date and the reminder moves with it. Clear the date or switch it off and the reminder is deleted. If you set a new date after you marked the reminder done, a new reminder is made.

## Due soon on the Timeline

The **Due soon** card sits at the top of the Timeline. It lists open reminders whose notify date has arrived (due date minus the notify days), overdue ones first, then by due date. Each row shows the title, the vehicle, the due date and either "in 12 days" or "Overdue by 3 days". Tap a row to edit it, or tap **Done** to dismiss it. **All reminders** opens the Reminders page. The card is hidden when nothing is due, and follows the vehicle chosen in the top bar.

## The Reminders page

Open it from **Manage > Reminders**, or from the Due soon card. It lists all open reminders by due date, and the done ones in a collapsed section. In the Home Assistant add-on it also holds the calendar setting described below.

## Putting reminders in a Home Assistant calendar

This works in the add-on only. Glovebox writes each open reminder as an all-day event on its due date, for example "Golf: Registration due". The event text holds your notes, a line "Notify 30 days before" and a line that marks it as a Glovebox reminder. Through Home Assistant the event can reach your other calendars, for example Google Calendar.

### Choosing a calendar

On the Reminders page, pick the calendar under the calendar setting. The list shows every calendar that can take new events, with what Glovebox can do there:

| Label | Meaning |
|---|---|
| Adds, changes and removes events | Full support |
| Adds and removes events | A changed reminder is not updated in the calendar |
| Adds and changes events | A removed reminder stays in the calendar |
| Only adds events | Changes and removals stay in the calendar |

**Recommended:** create a Local Calendar in Home Assistant (Settings > Devices & services > Add integration > Local Calendar) and call it "Glovebox reminders". It supports everything, and it keeps your own calendars free of changes you did not expect.

What other calendars support depends on the Home Assistant version and the integration. As of the version we checked, Local Calendar can add, change and remove events. Google Calendar (read and write setup) can add and remove. CalDAV can only add. Remote Calendar is read-only, so it is not offered. Check the label in the list instead of relying on this table.

When the calendar cannot do something, the reminder shows a plain message: "This calendar can't change events; edit it there." or "This calendar can't remove events; remove it there." Do that in the calendar itself.

### Syncing

Glovebox sends a reminder to the calendar right after you save it. If Home Assistant does not answer, saving still works, the reminder shows "Home Assistant did not answer. Will retry." and Glovebox tries again every 15 minutes. **Sync now** on the Reminders page, or in the reminder, tries at once. It also checks every open reminder against the calendar and writes again any event that is missing there, for example after the calendar was removed and added again.

Sync is one way. Glovebox writes to the calendar and never reads changes back. If you change or delete the event in the calendar, Glovebox does not notice. If you switch to another calendar, open reminders are written to the new one, and the old events are removed where that calendar allows it. The page says how many stay behind.

## Phone notifications with a blueprint

Glovebox sends no notifications itself. Home Assistant does, with a blueprint that reads the calendar.

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fdomengorjup%2Fglovebox%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Fglovebox%2Freminders.yaml)

Press the button, import the blueprint, then create an automation from it and fill in:

- **Calendar:** the calendar you chose on the Reminders page.
- **Time of day:** when the notification should arrive. The default is 09:00.
- **Notify action:** the notification action of your phone, for example `notify.mobile_app_my_phone`.

Every day at that time the automation looks at the next year of the calendar and finds the Glovebox reminders. It sends a message on the notify date (the due date minus the notify days of that reminder) and again on the due date, for example "Golf: Registration due in 30 days" and "Golf: Registration due today". It does not repeat overdue reminders. The automation only reads events in the calendar you give it that carry the Glovebox marker.

## Adding a reminder to any calendar (.ics file)

For Outlook, Apple Calendar or any calendar that Home Assistant cannot reach, open a reminder and tap **Download .ics**. Open the file in your calendar app. The event is an all-day event on the due date with two alarms, one at 09:00 on the notify date and one at 09:00 on the due date.

If you change the reminder and download it again, apps that follow the standard identifiers in the file update the existing event instead of adding a second one. Some apps ignore the alarms in imported files and use their own default alerts.

## Standalone

Without Home Assistant there is no calendar setting and no sync. Reminders still show on the Timeline, and **Download .ics** works.

## Backup and restore

The full backup contains the reminders as `reminders.csv`, and restoring brings them back. See [Export and backup](export.md) and the [standard format](standard-format.md#reminderscsv).
