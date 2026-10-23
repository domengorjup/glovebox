"""Reminder model, migration 0007 and service rules (reminders spec)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from glovebox.db import MIGRATIONS_DIR, make_engine, run_migrations
from glovebox.models import (
    CalendarState,
    Expense,
    ExpenseCategory,
    Reminder,
    ReminderStatus,
)
from glovebox.services import records, reminders
from glovebox.services.records import (
    ConfirmationRequired,
    ExpenseInput,
    ValidationError,
    VehicleInput,
)
from glovebox.services.reminders import ReminderInput


@pytest.fixture
def golf(session: Session):
    return records.create_vehicle(session, VehicleInput(name="Golf"))


def _input(vehicle_id: int, **changes) -> ReminderInput:
    values = dict(
        vehicle_id=vehicle_id, title="Registration", category="registration",
        due_date=date(2027, 3, 1), lead_days=14,
    )  # fmt: skip
    return ReminderInput(**{**values, **changes})


def _config(connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


# --- Migration and constraints ------------------------------------------------


def test_migration_0007_creates_table_and_downgrade_drops_it() -> None:
    engine = make_engine()
    with engine.begin() as connection:
        command.upgrade(_config(connection), "0006")
        assert "reminder" not in inspect(connection).get_table_names()
        command.upgrade(_config(connection), "0007")
        assert "reminder" in inspect(connection).get_table_names()
        command.downgrade(_config(connection), "0006")
        assert "reminder" not in inspect(connection).get_table_names()
    engine.dispose()


def test_deleting_the_vehicle_cascades(session: Session, golf) -> None:
    reminders.create_reminder(session, _input(golf.id))
    session.commit()
    session.delete(session.get(type(golf), golf.id))
    session.commit()
    assert session.scalars(select(Reminder)).all() == []


def test_deleting_the_expense_keeps_the_reminder(session: Session, golf) -> None:
    expense = records.create_expense(session, ExpenseInput(
        vehicle_id=golf.id, date=date(2026, 3, 1), category=ExpenseCategory.INSURANCE,
        amount_cents=50000, title="Policy",
    ))
    reminder = reminders.create_reminder(session, _input(golf.id, expense_id=expense.id))
    session.commit()
    records.delete_expense(session, expense.id)
    session.commit()
    session.refresh(reminder)
    assert reminder.expense_id is None


def test_database_limits_lead_days(session: Session, golf) -> None:
    session.add(Reminder(
        vehicle_id=golf.id, title="x", category=ExpenseCategory.OTHER,
        due_date=date(2027, 1, 1), lead_days=366, revision=1,
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# --- Service ------------------------------------------------------------------


def test_create_stores_an_open_reminder_with_remind_date(session: Session, golf) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id, title=" Registration "))
    assert reminder.title == "Registration"
    assert reminder.status is ReminderStatus.OPEN
    assert reminder.revision == 1 and len(reminder.uid) == 36
    assert reminders.remind_date(reminder) == date(2027, 2, 15)


def test_default_lead_days_is_30() -> None:
    assert ReminderInput(1, "t", "other", date(2027, 1, 1)).lead_days == 30


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "  "}, {"due_date": None}, {"lead_days": -1}, {"lead_days": 366},
        {"category": "nonsense"}, {"vehicle_id": 999},
    ],
)
def test_invalid_reminders_are_rejected(session: Session, golf, changes) -> None:
    with pytest.raises(ValidationError):
        reminders.create_reminder(session, replace(_input(golf.id), **changes))
    assert session.scalars(select(Reminder)).all() == []


def test_lead_days_limits_are_allowed(session: Session, golf) -> None:
    reminders.create_reminder(session, _input(golf.id, lead_days=0))
    reminders.create_reminder(session, _input(golf.id, lead_days=365))


def test_edit_bumps_revision_and_marks_a_written_reminder_pending(
    session: Session, golf
) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id))
    reminder.cal_state = CalendarState.SYNCED
    reminders.update_reminder(session, reminder.id, _input(golf.id, lead_days=7))
    assert (reminder.revision, reminder.lead_days) == (2, 7)
    assert reminder.cal_state is CalendarState.PENDING


def test_done_and_reopen(session: Session, golf) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id))
    reminders.mark_done(session, reminder.id)
    assert reminder.status is ReminderStatus.DONE and reminder.done_at is not None
    assert reminder.revision == 2
    reminders.reopen(session, reminder.id)
    assert reminder.status is ReminderStatus.OPEN and reminder.done_at is None
    assert reminder.revision == 3


def test_delete_leaves_a_removal_note_only_for_written_reminders(
    session: Session, golf
) -> None:
    plain = reminders.create_reminder(session, _input(golf.id))
    written = reminders.create_reminder(session, _input(golf.id, title="Policy"))
    written.cal_entity, written.cal_uid = "calendar.glovebox", "ev-1"
    reminders.delete_reminder(session, plain.id)
    assert reminders.load_removal_notes(session) == []
    reminders.delete_reminder(session, written.id)
    [note] = reminders.load_removal_notes(session)
    assert note["entity"] == "calendar.glovebox" and note["uid"] == "ev-1"
    assert note["marker"] == written.uid


# --- Due soon -----------------------------------------------------------------


def test_due_soon_boundaries(session: Session, golf) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id))  # remind 2027-02-15
    assert reminders.due_soon(session, date(2027, 2, 14)) == []
    assert reminders.due_soon(session, date(2027, 2, 15)) == [reminder]
    assert reminders.due_soon(session, date(2027, 3, 1)) == [reminder]
    assert reminders.due_soon(session, date(2027, 3, 2)) == [reminder]  # overdue
    assert reminders.is_overdue(reminder, date(2027, 3, 2))
    assert not reminders.is_overdue(reminder, date(2027, 3, 1))


def test_done_reminders_are_not_due_soon(session: Session, golf) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id))
    reminders.mark_done(session, reminder.id)
    assert reminders.due_soon(session, date(2027, 3, 1)) == []


def test_overdue_comes_first_and_vehicle_filter_applies(session: Session, golf) -> None:
    polo = records.create_vehicle(session, VehicleInput(name="Polo"))
    later = reminders.create_reminder(session, _input(golf.id, due_date=date(2027, 3, 5)))
    overdue = reminders.create_reminder(session, _input(golf.id, due_date=date(2027, 2, 28)))
    other = reminders.create_reminder(session, _input(polo.id, due_date=date(2027, 3, 3)))
    today = date(2027, 3, 1)
    assert reminders.due_soon(session, today) == [overdue, other, later]
    assert reminders.due_soon(session, today, (golf.id,)) == [overdue, later]
    assert reminders.count_open(session) == 3
    assert reminders.count_open(session, (polo.id,)) == 1


@pytest.mark.parametrize(
    ("days", "text_"),
    [(14, "in 14 days"), (1, "in 1 day"), (0, "today"), (-1, "Overdue by 1 day"),
     (-3, "Overdue by 3 days")],
)
def test_due_text(days: int, text_: str) -> None:
    assert reminders.due_text(days) == text_


def test_remind_date_crosses_year_end(session: Session, golf) -> None:
    reminder = reminders.create_reminder(
        session, _input(golf.id, due_date=date(2027, 1, 10), lead_days=30)
    )
    assert reminders.remind_date(reminder) == date(2026, 12, 11)


# --- Quick create -------------------------------------------------------------


def _expense(session: Session, vehicle_id: int, **changes) -> Expense:
    values = dict(
        vehicle_id=vehicle_id, date=date(2026, 5, 10),
        category=ExpenseCategory.MAINTENANCE, amount_cents=18000, title="Oil change",
    )  # fmt: skip
    return records.create_expense(session, ExpenseInput(**{**values, **changes}))


def test_suggestion_uses_coverage_end(session: Session, golf) -> None:
    expense = _expense(
        session, golf.id, category=ExpenseCategory.INSURANCE, title="Annual policy",
        coverage_start=date(2026, 3, 1), coverage_end=date(2027, 2, 28),
    )
    suggestion = reminders.suggest_from_expense(expense)
    assert (suggestion.title, suggestion.category) == ("Annual policy renewal", "insurance")
    assert (suggestion.due_date, suggestion.lead_days) == (date(2027, 2, 28), 30)
    assert suggestion.expense_id == expense.id and suggestion.vehicle_id == golf.id


def test_suggestion_without_coverage_is_a_year_later(session: Session, golf) -> None:
    expense = _expense(session, golf.id)
    assert reminders.suggest_from_expense(expense).due_date == date(2027, 5, 10)
    leap = _expense(session, golf.id, date=date(2028, 2, 29))
    assert reminders.suggest_from_expense(leap).due_date == date(2029, 2, 28)


def test_later_expense_edits_do_not_move_the_reminder(session: Session, golf) -> None:
    expense = _expense(session, golf.id)
    reminder = reminders.create_reminder(session, reminders.suggest_from_expense(expense))
    records.update_expense(session, expense.id, ExpenseInput(
        vehicle_id=golf.id, date=date(2026, 6, 1), category=ExpenseCategory.MAINTENANCE,
        amount_cents=18000, title="Oil change",
    ))
    assert reminder.due_date == date(2027, 5, 10)


# --- Vehicle dates -------------------------------------------------------------


def _vehicle_with_date(session: Session, vehicle, due: date | None):
    vehicle.registration_valid_until = due
    session.flush()
    return vehicle


def test_vehicle_date_creates_moves_and_removes_the_reminder(session: Session, golf) -> None:
    field = "registration_valid_until"
    _vehicle_with_date(session, golf, date(2027, 4, 30))
    created = reminders.follow_vehicle_date(session, golf, field, 30)
    assert (created.title, created.category) == ("Registration renewal", ExpenseCategory.REGISTRATION)
    assert created.vehicle_field == field and created.due_date == date(2027, 4, 30)

    _vehicle_with_date(session, golf, date(2028, 4, 30))
    moved = reminders.follow_vehicle_date(session, golf, field, 30)
    assert moved.id == created.id and moved.due_date == date(2028, 4, 30)
    assert session.scalars(select(Reminder)).all() == [created]

    assert reminders.follow_vehicle_date(session, golf, field, None) is None
    assert session.scalars(select(Reminder)).all() == []


def test_vehicle_date_cleared_deletes_the_linked_reminder(session: Session, golf) -> None:
    field = "registration_valid_until"
    _vehicle_with_date(session, golf, date(2027, 4, 30))
    reminders.follow_vehicle_date(session, golf, field, 30)
    _vehicle_with_date(session, golf, None)
    assert reminders.follow_vehicle_date(session, golf, field, 30) is None
    assert session.scalars(select(Reminder)).all() == []


def test_done_reminder_is_not_recreated_for_the_same_date_but_for_a_new_one(
    session: Session, golf
) -> None:
    field = "registration_valid_until"
    _vehicle_with_date(session, golf, date(2027, 4, 30))
    first = reminders.follow_vehicle_date(session, golf, field, 30)
    reminders.mark_done(session, first.id)
    assert reminders.follow_vehicle_date(session, golf, field, 30) is None
    _vehicle_with_date(session, golf, date(2028, 4, 30))
    second = reminders.follow_vehicle_date(session, golf, field, 30)
    assert second is not None and second.id != first.id


# --- Vehicle delete -------------------------------------------------------------


def test_vehicle_delete_counts_and_deletes_reminders(session: Session, golf) -> None:
    reminders.create_reminder(session, _input(golf.id))
    written = reminders.create_reminder(session, _input(golf.id, title="Policy"))
    written.cal_entity = "calendar.glovebox"
    assert records.count_vehicle_records(session, golf.id).reminders == 2
    with pytest.raises(ConfirmationRequired) as info:
        records.delete_vehicle(session, golf.id)
    assert info.value.reminders == 2
    records.delete_vehicle(session, golf.id, confirm=True)
    assert session.scalars(select(Reminder)).all() == []
    assert len(reminders.load_removal_notes(session)) == 1  # its event still has to go


def test_event_text(session: Session, golf) -> None:
    reminder = reminders.create_reminder(session, _input(golf.id, notes="Bring papers"))
    assert reminders.event_summary("Golf", reminder.title) == "Golf: Registration due"
    assert reminders.event_description(reminder).splitlines() == [
        "Bring papers", "Notify 14 days before", f"Glovebox reminder {reminder.uid}",
    ]


@pytest.mark.parametrize("title, expected", [
    ("Registration renewal", "Registration renewal"),
    ("Insurance RENEWAL", "Insurance RENEWAL"),
    ("Policy", "Policy renewal"),
])
def test_suggested_title_does_not_repeat_renewal(session: Session, golf, title, expected) -> None:
    expense = _expense(session, golf.id, category=ExpenseCategory.INSURANCE, title=title)
    assert reminders.suggest_from_expense(expense).title == expected
