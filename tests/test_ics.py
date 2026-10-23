"""The .ics writer (reminder-delivery spec): structure, folding, escaping, alarms."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from glovebox.ics import escape_text, fold_line, reminder_ics
from glovebox.services import records, reminders
from glovebox.services.records import VehicleInput
from glovebox.services.reminders import ReminderInput


def _reminder(session: Session, **changes):
    vehicle = records.create_vehicle(session, VehicleInput(name="Golf"))
    values = dict(
        vehicle_id=vehicle.id, title="Registration", category="registration",
        due_date=date(2027, 3, 1), lead_days=30,
    )  # fmt: skip
    reminder = reminders.create_reminder(session, ReminderInput(**{**values, **changes}))
    reminder.updated_at = datetime(2026, 10, 23, 8, 30, 5)
    return reminder


def _parse(data: bytes) -> list[tuple[str, str]]:
    """Unfold the content lines and split them into (name with params, value)."""
    text = data.decode("utf-8")
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    unfolded = text.replace("\r\n ", "").split("\r\n")[:-1]
    return [tuple(line.split(":", 1)) for line in unfolded]


def _alarms(lines: list[tuple[str, str]]) -> list[str]:
    triggers = []
    inside = False
    for name, value in lines:
        if (name, value) == ("BEGIN", "VALARM"):
            inside = True
        elif inside and name == "TRIGGER":
            triggers.append(value)
        elif (name, value) == ("END", "VALARM"):
            inside = False
    return triggers


def test_structure_and_dates(session: Session) -> None:
    reminder = _reminder(session, notes="Bring papers, green card")
    data = reminder_ics(reminder, "Golf")
    lines = _parse(data)
    names = [n for n, _ in lines]
    assert names[:5] == ["BEGIN", "VERSION", "PRODID", "METHOD", "BEGIN"]
    assert names[-1] == "END" and lines[-1][1] == "VCALENDAR"
    assert lines.count(("BEGIN", "VEVENT")) == 1
    alarm_start = lines.index(("BEGIN", "VALARM"))
    fields = dict(lines[:alarm_start])  # the alarms have their own DESCRIPTION
    assert fields["VERSION"] == "2.0" and fields["METHOD"] == "PUBLISH"
    assert fields["DTSTART;VALUE=DATE"] == "20270301"
    assert fields["DTEND;VALUE=DATE"] == "20270302"
    assert fields["DTSTAMP"] == "20261023T083005Z"
    assert fields["SUMMARY"] == "Golf: Registration due"
    assert fields["UID"] == f"{reminder.uid}@glovebox"
    assert fields["SEQUENCE"] == "1"
    assert fields["TRANSP"] == "TRANSPARENT"
    assert fields["DESCRIPTION"] == (
        "Bring papers\\, green card\\nNotify 30 days before"
        f"\\nGlovebox reminder {reminder.uid}"
    )


def test_two_alarms_at_nine(session: Session) -> None:
    lines = _parse(reminder_ics(_reminder(session, lead_days=30), "Golf"))
    # 09:00 on 2027-01-30 is 29 days and 15 hours before 00:00 on 2027-03-01.
    assert _alarms(lines) == ["-P29DT15H", "PT9H"]
    assert dict(lines)["ACTION"] == "DISPLAY"


def test_one_day_lead_alarm_is_the_evening_before(session: Session) -> None:
    lines = _parse(reminder_ics(_reminder(session, lead_days=1), "Golf"))
    assert _alarms(lines) == ["-P0DT15H", "PT9H"]


def test_zero_lead_days_has_only_the_due_date_alarm(session: Session) -> None:
    lines = _parse(reminder_ics(_reminder(session, lead_days=0), "Golf"))
    assert _alarms(lines) == ["PT9H"]


def test_edit_keeps_the_uid_and_raises_the_sequence(session: Session) -> None:
    reminder = _reminder(session)
    before = dict(_parse(reminder_ics(reminder, "Golf")))
    reminders.update_reminder(
        session, reminder.id,
        ReminderInput(reminder.vehicle_id, "Registration", "registration",
                      date(2027, 3, 10), 30),
    )
    after = dict(_parse(reminder_ics(reminder, "Golf")))
    assert after["UID"] == before["UID"]
    assert int(after["SEQUENCE"]) > int(before["SEQUENCE"])


def test_long_lines_fold_within_75_octets_and_unfold_back(session: Session) -> None:
    title = "Überprüfung " * 20  # multi-byte characters must not be split
    data = reminder_ics(_reminder(session, title=title[:200]), "Golf")
    for physical in data.decode("utf-8").split("\r\n"):
        assert len(physical.encode("utf-8")) <= 75
    summary = dict(_parse(data))["SUMMARY"]
    assert summary == f"Golf: {title[:200].strip()} due"


def test_fold_line_leaves_short_lines_alone() -> None:
    assert fold_line("SUMMARY:short") == "SUMMARY:short"


def test_fold_line_never_splits_a_character() -> None:
    folded = fold_line("X:" + "š" * 100)
    assert all(len(p.encode()) <= 75 for p in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "X:" + "š" * 100


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [("a;b", "a\\;b"), ("a,b", "a\\,b"), ("a\\b", "a\\\\b"), ("a\nb", "a\\nb"),
     ("a\r\nb", "a\\nb")],
)
def test_escape_text(raw: str, escaped: str) -> None:
    assert escape_text(raw) == escaped
