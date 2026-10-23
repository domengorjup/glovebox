## ADDED Requirements

### Requirement: Reminders calendar setting
In add-on mode the Reminders page SHALL let the user choose one Home Assistant calendar entity for reminders, or None (the default). Every calendar entity whose supported features include creating events SHALL be offered, whatever integration provides it. Each SHALL be labelled with what it supports: changing and removing events, removing only, changing only, or only adding. The choice SHALL be stored server-side. The system SHALL NOT contain rules for particular calendar providers.

#### Scenario: Choice list
- **WHEN** HA has a Local Calendar, a calendar that can only add events, and a read-only calendar
- **THEN** the first two are offered, labelled "Adds, changes and removes events" and "Only adds events"
- **AND** the read-only calendar is not offered

### Requirement: Reminders written to the HA calendar
With a calendar chosen, every open reminder SHALL be written to it as one all-day event on the due date.
- **Summary:** "<vehicle>: <title> due".
- **Description:** the notes, a line `Notify <N> days before` with the reminder's lead days, and a final marker line `Glovebox reminder <uid>`.

The system SHALL find the event's uid through the HA calendar events REST endpoint by the marker, and SHALL store it. Before creating an event, the system SHALL look for an existing event with the same marker and reuse it, so that retries and restores do not create duplicates.

#### Scenario: New reminder in Local Calendar
- **WHEN** the chosen calendar is a Local Calendar and the user saves a reminder for "Golf", "Registration", due 2027-03-01, 30 days before
- **THEN** the calendar has an all-day event on 2027-03-01 titled "Golf: Registration due"
- **AND** its description contains "Notify 30 days before" and the marker line
- **AND** the reminder stores the event's uid and shows no calendar message

#### Scenario: Retry does not duplicate
- **WHEN** a create succeeded in HA but the answer timed out, and the sync runs again
- **THEN** the existing event is found by its marker and no second event is created

### Requirement: Changes passed on where supported
When a synced reminder changes, the system SHALL update its event if the calendar supports changing events. Otherwise it SHALL leave the event as it is and show "This calendar can't change events; edit it there."

When a reminder is marked done or deleted, the system SHALL remove its event if the calendar supports removing events. Otherwise it SHALL leave the event and show "This calendar can't remove events; remove it there."

When the chosen calendar changes, open reminders SHALL be written to the new calendar, and their events SHALL be removed from the old one where it supports removing. Choosing None SHALL stop writing and remove the events where supported.

#### Scenario: Update in Local Calendar
- **WHEN** the due date of a synced reminder in a Local Calendar changes to 2027-03-10
- **THEN** the same event (same uid) moves to 2027-03-10

#### Scenario: Calendar that only adds
- **WHEN** the same change is made with a calendar that can only add events
- **THEN** the event is unchanged and the reminder shows "This calendar can't change events; edit it there."

#### Scenario: Done removes the event
- **WHEN** a reminder synced to a Local Calendar is marked done
- **THEN** its event is removed from the calendar

### Requirement: Calendar sync failures
A calendar failure SHALL NOT block or undo saving a reminder. The system SHALL attempt the sync on save, and SHALL retry unsynced reminders in the background at least every 15 minutes and at startup. A "Sync now" action SHALL run the retry at once. A reminder that is not synced SHALL show a plain-language reason:
- Home Assistant did not answer (will retry);
- the add-on may not use the Home Assistant API;
- the calendar no longer exists, or no longer accepts events (choose another);
- the calendar has not listed the new event yet (will retry without creating another).

#### Scenario: HA unreachable
- **WHEN** a reminder is saved while Home Assistant Core is restarting
- **THEN** the reminder is stored and shows "Home Assistant did not answer. Will retry."
- **AND** a later retry writes the event once HA is back

#### Scenario: Calendar entity removed
- **WHEN** the chosen calendar entity no longer exists
- **THEN** the calendar setting shows a warning asking the user to choose another calendar
- **AND** the affected reminders show the same reason

### Requirement: Calendar file download
Each reminder SHALL offer a "Download .ics" action that returns an iCalendar (RFC 5545) file with one all-day event on the due date. The event SHALL have:
- the same summary and description as the HA event;
- a `UID` built from the reminder uid, and a `SEQUENCE` that increases with every change;
- a display alarm at 09:00 on the remind date when the lead days are above 0, and one at 09:00 on the due date.

The download SHALL work through Ingress and in standalone mode.

#### Scenario: Download one reminder
- **WHEN** the user downloads the .ics of a reminder due 2027-03-01 with 30 lead days
- **THEN** the file is `text/calendar` with one `VEVENT` with `DTSTART;VALUE=DATE:20270301` and `DTEND;VALUE=DATE:20270302`
- **AND** it has an alarm at 09:00 on 2027-01-30 and one at 09:00 on 2027-03-01

#### Scenario: Changed reminder
- **WHEN** the reminder is edited and downloaded again
- **THEN** the event has the same `UID` and a higher `SEQUENCE`

### Requirement: Standalone mode has no calendar sync
In standalone mode the system SHALL NOT try to reach Home Assistant. The Reminders page SHALL explain that calendar sync needs the Home Assistant add-on and point to the .ics download. All other reminder features SHALL work as in add-on mode.

#### Scenario: Standalone reminders page
- **WHEN** the app runs standalone and the user opens the Reminders page
- **THEN** no calendar select is shown
- **AND** the page says calendar sync needs the add-on and that each reminder can be downloaded as .ics

### Requirement: Notification blueprint
The app SHALL NOT send notifications itself. The repository SHALL ship one Home Assistant automation blueprint with a `source_url`, importable through a my.home-assistant.io blueprint-import link given in the user documentation and `DOCS.md`.

Its inputs SHALL be a calendar entity, a time of day and a notify action. Once a day at that time it SHALL read the calendar's upcoming events. For each Glovebox event it SHALL send one notification on the day that is the lead days before the event, and one on the event's day.

#### Scenario: Notify on the remind date
- **WHEN** the blueprint runs at 09:00 on 2027-01-30 and the calendar holds the event "Golf: Registration due" on 2027-03-01 with "Notify 30 days before"
- **THEN** it sends one notification that says the registration is due in 30 days

#### Scenario: Notify on the due date
- **WHEN** the blueprint runs on 2027-03-01 for the same event
- **THEN** it sends one notification that says the registration is due today

#### Scenario: Other events ignored
- **WHEN** the calendar also holds an event without the Glovebox marker
- **THEN** the blueprint sends no notification for it
