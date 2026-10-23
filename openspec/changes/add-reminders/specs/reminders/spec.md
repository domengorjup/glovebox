## ADDED Requirements

### Requirement: Reminder records
The system SHALL store reminders with these fields:
- **Required:** vehicle, title, category, due date and lead days.
- **Optional:** notes.
- **Category:** one of the expense categories (`maintenance`, shown as "Service"; `insurance`; `registration`; `other`).
- **Lead days** ("notify N days before"): a whole number from 0 to 365, default 30, set when the reminder is created and editable.
- **Remind date:** the due date minus the lead days.
- **Status:** `open` or `done`.
- **Stable uid:** a unique id that SHALL be kept across backup and restore.

A reminder MAY record the expense it was created from. Deleting that expense SHALL keep the reminder and drop the link. The user SHALL be able to create, edit, mark done, reopen and delete a reminder.

#### Scenario: Default lead time
- **WHEN** the user opens the new-reminder form
- **THEN** "Notify … days before" is 30

#### Scenario: Create a reminder
- **WHEN** the user saves a reminder for "Golf" titled "Registration", category registration, due 2027-03-01, 14 days before
- **THEN** it is stored as open with remind date 2027-02-15

#### Scenario: Reject a reminder without title or due date
- **WHEN** a reminder is submitted with a blank title, no due date, or lead days below 0 or above 365
- **THEN** the system rejects it and stores nothing

#### Scenario: Mark done and reopen
- **WHEN** the user marks an open reminder done
- **THEN** its status is done and it no longer appears in "Due soon"
- **AND** reopening it makes it open again

#### Scenario: Expense deleted
- **WHEN** an expense a reminder was created from is deleted
- **THEN** the reminder remains and no longer shows "Created from"

### Requirement: Remind me from an expense
The expense edit dialog SHALL offer "Remind me", which SHALL open the reminder form pre-filled with:
- the expense's vehicle and category;
- the title "<expense title> renewal", without repeating "renewal" when the expense title already ends with it (case-insensitive);
- the due date: the expense's coverage end when set, otherwise the expense date plus one year;
- 30 lead days.

The add-expense form SHALL offer a "Remind me before it runs out" switch, off by default, with a lead-days field. Saving the expense with the switch on SHALL also create that reminder. The reminder SHALL keep a link to the expense, but later edits of the expense SHALL NOT change the reminder.

#### Scenario: Insurance with coverage end
- **WHEN** the user opens "Remind me" on the insurance expense "Annual policy" with coverage 2026-03-01 to 2027-02-28
- **THEN** the form shows title "Annual policy renewal", category insurance, due 2027-02-28 and 30 days before

#### Scenario: Title already ends in renewal
- **WHEN** the user opens "Remind me" on the expense "Registration renewal"
- **THEN** the form shows title "Registration renewal"

#### Scenario: Expense without coverage
- **WHEN** the user opens "Remind me" on a service expense dated 2026-05-10 without coverage dates
- **THEN** the form shows due 2027-05-10

#### Scenario: Switch on the add form
- **WHEN** the user adds a registration expense with coverage end 2027-04-30 and the switch on with 30 days
- **THEN** the expense and an open reminder due 2027-04-30, 30 days before, are stored

### Requirement: Reminders from vehicle dates
When a vehicle has an insurance or registration "valid until" date (vehicle-details change), the vehicle form SHALL offer a "Remind me … days before" switch next to each of these dates, with 30 days by default.
- **Switch on:** saving SHALL create an open reminder linked to that vehicle field, due on that date, titled "Insurance renewal" or "Registration renewal", with the category of the same name.
- **Date changed:** the linked open reminder SHALL move to the new date.
- **Date cleared or switch off:** the linked open reminder SHALL be deleted.
- **One per field:** a vehicle SHALL have at most one open reminder per linked field.
- **New period:** when the linked reminder is done and a different date is saved with the switch on, a new linked reminder SHALL be created.

#### Scenario: Registration date with reminder
- **WHEN** the user sets "Registration valid until" 2027-04-30 on "Golf" with the switch on and 30 days
- **THEN** an open reminder "Registration renewal" due 2027-04-30, 30 days before, is linked to that field

#### Scenario: Date moved
- **WHEN** the user changes that date to 2028-04-30
- **THEN** the same reminder is now due 2028-04-30 and no second reminder exists

### Requirement: Due soon on the Timeline
The Timeline SHALL show a "Due soon" card above the summary cards. The card SHALL list the open reminders whose remind date is today or earlier, for the vehicle selected in the app bar or for all vehicles. Overdue reminders (due date before today) SHALL come first, and the rest SHALL follow by due date.
- **Each row:** title, vehicle, due date, and the days left or "Overdue by N days", plus a Done action.
- **Header:** an "All reminders" button.
- **Empty:** the card SHALL be hidden when no reminder is due.

#### Scenario: Reminder becomes due
- **WHEN** today is 2027-02-15 and an open reminder is due 2027-03-01 with 14 lead days
- **THEN** the Timeline shows it in "Due soon" with "in 14 days"

#### Scenario: Not yet due
- **WHEN** today is 2027-02-14 for the same reminder
- **THEN** the "Due soon" card does not list it

#### Scenario: Overdue first
- **WHEN** one open reminder was due yesterday and another is due in 5 days and is past its remind date
- **THEN** the overdue one is listed first with "Overdue by 1 day"

#### Scenario: Done from the Timeline
- **WHEN** the user presses Done on a row
- **THEN** the reminder is marked done and the row disappears

### Requirement: Reminders page
The system SHALL provide a Reminders page, reachable from the "Due soon" card and from Manage. It SHALL list the open reminders by due date and the done reminders in a collapsed section, filtered by the app-bar vehicle. The add chooser SHALL offer "Reminder", which opens the reminder form.

#### Scenario: Open the list from Manage
- **WHEN** the user opens Manage and selects Reminders
- **THEN** the Reminders page lists the open reminders by due date and shows the count of open reminders on the Manage row
