"""
iCalendar (RFC 5545) file for one reminder (design D6), written by hand.

One all-day ``VEVENT`` on the due date with two display alarms: 09:00 on the
remind date (only when the lead time is above 0) and 09:00 on the due date.
"""

from __future__ import annotations

from datetime import date, timedelta

from glovebox.models import Reminder
from glovebox.services.reminders import event_description, event_summary

PRODID = "-//Glovebox//Reminders//EN"
UID_DOMAIN = "glovebox"
MAX_LINE_OCTETS = 75
ALARM_HOUR = 9


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and line breaks."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    escaped = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\n", "\\n")


def fold_line(line: str) -> str:
    """
    Fold a content line at 75 octets: continuation lines start with a space.
    UTF-8 characters are never split.
    """
    parts: list[str] = []
    current = ""
    limit = MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            parts.append(current)
            current, limit = char, MAX_LINE_OCTETS - 1  # the leading space counts
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _ical_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def reminder_ics(reminder: Reminder, vehicle_name: str) -> bytes:
    """
    The .ics file of a reminder.

    ``UID`` is stable and ``SEQUENCE`` is the reminder's revision, so a
    calendar app that opens a newer file updates the event it already has.
    ``DTSTAMP`` is the time of the last change, which keeps the file the same
    until the reminder changes.
    """
    stamp = reminder.updated_at.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{reminder.uid}@{UID_DOMAIN}",
        f"SEQUENCE:{reminder.revision}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{_ical_date(reminder.due_date)}",
        f"DTEND;VALUE=DATE:{_ical_date(reminder.due_date + timedelta(days=1))}",
        f"SUMMARY:{escape_text(event_summary(vehicle_name, reminder.title))}",
        f"DESCRIPTION:{escape_text(event_description(reminder))}",
        "TRANSP:TRANSPARENT",
    ]
    description = escape_text(f"{vehicle_name}: {reminder.title}")
    if reminder.lead_days > 0:
        # The event starts at 00:00 of the due date; 09:00 on the remind date
        # is (lead days - 1) days and 15 hours before that.
        lines += _alarm(f"-P{reminder.lead_days - 1}DT{24 - ALARM_HOUR}H", description)
    lines += _alarm(f"PT{ALARM_HOUR}H", description)
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "".join(fold_line(line) + "\r\n" for line in lines).encode("utf-8")


def _alarm(trigger: str, description: str) -> list[str]:
    return [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"TRIGGER:{trigger}",
        f"DESCRIPTION:{description}",
        "END:VALARM",
    ]
