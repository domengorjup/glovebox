## ADDED Requirements

### Requirement: Reminders calendar setting
In add-on mode the Reminders page SHALL let the user choose one Home Assistant calendar entity for reminders, or None (the default). Only calendars that support creating events SHALL be offered. Each SHALL be labelled with what it supports: adding, changing and removing events; adding and removing; or only adding. The choice SHALL be stored server-side.

#### Scenario: Choice list
- **WHEN** HA has a Local Calendar, a read/write Google calendar, a CalDAV calendar and a Remote Calendar
- **THEN** the first three are offered, labelled "Adds, changes and removes events", "Adds and removes events" and "Can only add events"
- **AND** the Remote Calendar is not offered

### Requirement: Reminders written to the HA calendar
With a calendar chosen, every open reminder SHALL be written to it as one all-day event on the remind date.
- **Summary:** the vehicle name, the title and the due date.
- **Description:** the notes and a final marker line `Glovebox reminder <uid>`.

After creating an event, the system SHALL find its uid through the HA calendar events REST endpoint by the marker, and SHALL store it with the reminder. Before creating, the system SHALL look for an existing event with the same marker and reuse it, so that retries and restores do not create duplicates.

#### Scenario: New reminder in Local Calendar
- **WHEN** the chosen calendar is a Local Calendar and the user saves a reminder for "Golf", "Registration", due 2027-03-01, 14 days before
- **THEN** the calendar has an all-day event on 2027-02-15 titled "Golf: Registration (due 1 Mar 2027)"
- **AND** the reminder stores the event's uid and shows no calendar warning

#### Scenario: Retry does not duplicate
- **WHEN** a create succeeded in HA but the answer timed out, and the sync runs again
- **THEN** the existing event is found by its marker and no second event is created

### Requirement: Calendar events follow changes
When a synced reminder changes, the system SHALL change its event as far as the calendar allows:
- **Changing supported:** the event SHALL be updated in place.
- **Only adding and removing:** the old event SHALL be removed and a new one created.
- **Only adding:** the event SHALL stay as it was. The reminder SHALL show that the event is out of date, why, and an "Add new event" action that creates a new event.

When a reminder is marked done or deleted, its event SHALL be removed where the calendar allows removing. Otherwise the user SHALL be told that the event stays.

When the chosen calendar changes, the events of open reminders SHALL be removed from the old calendar where it allows that, and created in the new one. Choosing None SHALL only remove them.

#### Scenario: Update in Local Calendar
- **WHEN** the due date of a synced reminder in a Local Calendar changes to 2027-03-10
- **THEN** the same event (same uid) moves to the new remind date

#### Scenario: Google calendar
- **WHEN** the same change is made with a read/write Google calendar chosen
- **THEN** the old event is removed, a new one is created, and the new uid is stored

#### Scenario: CalDAV calendar
- **WHEN** the same change is made with a CalDAV calendar chosen
- **THEN** the event is unchanged and the reminder says "This calendar can only add events, so the event on 15 Feb cannot follow the change", with "Add new event"

#### Scenario: Done removes the event
- **WHEN** a reminder synced to a Local Calendar is marked done
- **THEN** its event is removed from the calendar

### Requirement: Calendar sync failures
A calendar failure SHALL NOT block or undo saving a reminder. The system SHALL attempt the sync on save and retry unsynced reminders in the background at least every 15 minutes and at startup. A "Sync now" action SHALL run the retry at once. A reminder that is not synced SHALL show a plain-language reason:
- Home Assistant did not answer (will retry);
- the add-on may not use the Home Assistant API;
- the calendar no longer exists, or no longer accepts events (choose another);
- the calendar has not listed the new event yet (will retry, without creating another).

#### Scenario: HA unreachable
- **WHEN** a reminder is saved while Home Assistant Core is restarting
- **THEN** the reminder is stored and shows "Home Assistant did not answer. Will retry."
- **AND** a later retry writes the event once HA is back

#### Scenario: Calendar entity removed
- **WHEN** the chosen calendar entity no longer exists
- **THEN** the calendar setting shows a warning asking the user to choose another calendar
- **AND** the affected reminders show the same reason

### Requirement: Calendar file download
Each reminder SHALL offer a "Download .ics" action that returns an iCalendar (RFC 5545) file with one all-day event on the remind date:
- the same summary and description as the HA event;
- `UID` built from the reminder uid, and `SEQUENCE` increasing with every change;
- a display alarm at 09:00 on that day.

The Reminders page SHALL offer one file with all open reminders. Downloads SHALL work through Ingress and in standalone mode.

#### Scenario: Download one reminder
- **WHEN** the user downloads the .ics of a reminder due 2027-03-01 with 14 lead days
- **THEN** the file is `text/calendar` with one `VEVENT` with `DTSTART;VALUE=DATE:20270215` and `DTEND;VALUE=DATE:20270216`

#### Scenario: Changed reminder
- **WHEN** the reminder is edited and downloaded again
- **THEN** the event has the same `UID` and a higher `SEQUENCE`

### Requirement: Standalone mode has no calendar sync
In standalone mode the system SHALL NOT try to reach Home Assistant. The Reminders page SHALL explain that calendar sync needs the Home Assistant add-on and point to the .ics download. All other reminder features SHALL work as in add-on mode.

#### Scenario: Standalone reminders page
- **WHEN** the app runs standalone and the user opens the Reminders page
- **THEN** no calendar select is shown
- **AND** the page says calendar sync needs the add-on and offers "Download all (.ics)"

### Requirement: Notification guidance
The add-on SHALL NOT send notifications itself. The user documentation SHALL include an example Home Assistant automation that uses a calendar trigger on the reminders calendar to send a phone notification on the remind date.

#### Scenario: Example in the docs
- **WHEN** the user reads the reminders page of the documentation
- **THEN** it contains a calendar-trigger automation that calls a `notify.mobile_app_*` action with the event summary
