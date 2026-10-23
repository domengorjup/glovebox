"""
Reminder services (design D1): create, edit, done, reopen, delete, the dates.

Like the record services, every function takes a ``Session`` first, flushes
and does not commit. Every change of a reminder bumps ``revision``; the
calendar sync (``reminder_sync``) compares it with ``cal_synced_revision``.

A reminder that was written to a calendar leaves a *removal note* when it is
deleted, because its row is gone but its event may not be. The sync pass works
off these notes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from glovebox.models import (
    CalendarState,
    Expense,
    ExpenseCategory,
    Reminder,
    ReminderStatus,
    Vehicle,
)
from glovebox.services.preferences import get_setting, set_setting
from glovebox.services.records import NotFoundError, ValidationError

DEFAULT_LEAD_DAYS = 30
MAX_LEAD_DAYS = 365
MAX_TITLE_LENGTH = 200
MARKER_PREFIX = "Glovebox reminder"
REMOVALS_SETTING = "reminders.removals"

# Vehicle date fields that can own a reminder -> (category, title).
VEHICLE_FIELDS: dict[str, tuple[ExpenseCategory, str]] = {
    "insurance_valid_until": (ExpenseCategory.INSURANCE, "Insurance renewal"),
    "registration_valid_until": (ExpenseCategory.REGISTRATION, "Registration renewal"),
}


@dataclass(frozen=True)
class ReminderInput:
    """
    Values of the reminder form.

    ``expense_id`` and ``vehicle_field`` are links set by the quick-create
    paths; ``update_reminder`` leaves them alone.
    """

    vehicle_id: int
    title: str
    category: str
    due_date: date | None
    lead_days: int = DEFAULT_LEAD_DAYS
    notes: str | None = None
    expense_id: int | None = None
    vehicle_field: str | None = None


# --- Dates ------------------------------------------------------------------


def remind_date(reminder: Reminder) -> date:
    """The day the reminder starts to show: the due date minus the lead days."""
    return date.fromordinal(reminder.due_date.toordinal() - reminder.lead_days)


def days_until_due(reminder: Reminder, today: date) -> int:
    """Days from ``today`` to the due date; negative when overdue."""
    return (reminder.due_date - today).days


def is_overdue(reminder: Reminder, today: date) -> bool:
    """True for an open reminder whose due date has passed."""
    return reminder.status is ReminderStatus.OPEN and reminder.due_date < today


def is_due_soon(reminder: Reminder, today: date) -> bool:
    """True for an open reminder whose remind date is today or earlier."""
    return reminder.status is ReminderStatus.OPEN and remind_date(reminder) <= today


def due_text(days: int) -> str:
    """Words for the days to the due date: "in 12 days", "Overdue by 1 day"."""
    if days == 0:
        return "today"
    unit = "day" if abs(days) == 1 else "days"
    return f"in {days} {unit}" if days > 0 else f"Overdue by {-days} {unit}"


# --- Reading ----------------------------------------------------------------


def get_reminder(session: Session, reminder_id: int) -> Reminder:
    """Return the reminder or raise ``NotFoundError``."""
    reminder = session.get(Reminder, reminder_id)
    if reminder is None:
        raise NotFoundError(f"Reminder {reminder_id} not found")
    return reminder


def list_reminders(
    session: Session,
    vehicle_ids: tuple[int, ...] = (),
    status: ReminderStatus | None = None,
) -> list[Reminder]:
    """
    Reminders by due date (newest first for done ones), optionally for some
    vehicles (empty = all) and one status.
    """
    query = select(Reminder)
    if vehicle_ids:
        query = query.where(Reminder.vehicle_id.in_(vehicle_ids))
    if status is not None:
        query = query.where(Reminder.status == status)
    if status is ReminderStatus.DONE:
        query = query.order_by(Reminder.due_date.desc(), Reminder.id.desc())
    else:
        query = query.order_by(Reminder.due_date, Reminder.id)
    return list(session.scalars(query))


def due_soon(
    session: Session, today: date, vehicle_ids: tuple[int, ...] = ()
) -> list[Reminder]:
    """Open reminders whose remind date has arrived; overdue ones come first."""
    open_reminders = list_reminders(session, vehicle_ids, ReminderStatus.OPEN)
    return [r for r in open_reminders if is_due_soon(r, today)]


def count_open(session: Session, vehicle_ids: tuple[int, ...] = ()) -> int:
    """Number of open reminders (for the Manage row)."""
    query = (
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.status == ReminderStatus.OPEN)
    )
    if vehicle_ids:
        query = query.where(Reminder.vehicle_id.in_(vehicle_ids))
    return session.scalar(query) or 0


def count_vehicle_reminders(session: Session, vehicle_id: int) -> int:
    """Number of reminders of a vehicle, open or done."""
    query = select(func.count()).select_from(Reminder)
    return session.scalar(query.where(Reminder.vehicle_id == vehicle_id)) or 0


# --- Writing ----------------------------------------------------------------


def create_reminder(session: Session, data: ReminderInput) -> Reminder:
    """Validate and store a new open reminder."""
    reminder = Reminder(
        vehicle_id=data.vehicle_id,
        expense_id=data.expense_id,
        vehicle_field=data.vehicle_field,
        revision=1,
    )
    _apply(session, reminder, data)
    session.add(reminder)
    session.flush()
    return reminder


def update_reminder(
    session: Session, reminder_id: int, data: ReminderInput
) -> Reminder:
    """Change a reminder's form fields; the links are kept."""
    reminder = get_reminder(session, reminder_id)
    _apply(session, reminder, data)
    _touch(reminder)
    session.flush()
    return reminder


def mark_done(session: Session, reminder_id: int) -> Reminder:
    """Dismiss a reminder; its calendar event is removed by the next sync."""
    reminder = get_reminder(session, reminder_id)
    if reminder.status is not ReminderStatus.DONE:
        reminder.status = ReminderStatus.DONE
        reminder.done_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _touch(reminder)
        session.flush()
    return reminder


def reopen(session: Session, reminder_id: int) -> Reminder:
    """Make a done reminder open again."""
    reminder = get_reminder(session, reminder_id)
    if reminder.status is not ReminderStatus.OPEN:
        reminder.status = ReminderStatus.OPEN
        reminder.done_at = None
        _touch(reminder)
        session.flush()
    return reminder


def delete_reminder(session: Session, reminder_id: int) -> None:
    """Delete a reminder; a written calendar event is removed by the next sync."""
    reminder = get_reminder(session, reminder_id)
    leave_removal_note(session, reminder)
    session.delete(reminder)
    session.flush()


def delete_vehicle_reminders(session: Session, vehicle_id: int) -> int:
    """Delete all reminders of a vehicle; returns how many."""
    reminders = list_reminders(session, (vehicle_id,))
    for reminder in reminders:
        leave_removal_note(session, reminder)
        session.delete(reminder)
    session.flush()
    return len(reminders)


def _apply(session: Session, reminder: Reminder, data: ReminderInput) -> None:
    """Validate ``data`` and copy it onto ``reminder``."""
    errors: list[str] = []
    title = (data.title or "").strip()
    if not title:
        errors.append("Enter a title for the reminder.")
    elif len(title) > MAX_TITLE_LENGTH:
        errors.append(f"The title is longer than {MAX_TITLE_LENGTH} characters.")
    try:
        category = ExpenseCategory(data.category)
    except ValueError:
        errors.append(f"Unknown category: {data.category!r}.")
        category = None
    if data.due_date is None:
        errors.append("Enter the due date.")
    if not 0 <= data.lead_days <= MAX_LEAD_DAYS:
        errors.append(f"Notify between 0 and {MAX_LEAD_DAYS} days before.")
    if session.get(Vehicle, data.vehicle_id) is None:
        errors.append("Choose a vehicle.")
    if errors:
        raise ValidationError(errors)
    reminder.vehicle_id = data.vehicle_id
    reminder.title = title
    reminder.category = category
    reminder.due_date = data.due_date
    reminder.lead_days = data.lead_days
    reminder.notes = (data.notes or "").strip() or None


def _touch(reminder: Reminder) -> None:
    """Record a change: new revision, and the calendar has to hear of it."""
    reminder.revision += 1
    if reminder.cal_state is not CalendarState.NONE:
        reminder.cal_state = CalendarState.PENDING
        reminder.cal_message = None


# --- Removal notes ----------------------------------------------------------


def leave_removal_note(session: Session, reminder: Reminder) -> None:
    """Note that the reminder's calendar event has to go, if it may exist."""
    if not reminder.cal_entity:
        return
    notes = load_removal_notes(session)
    notes.append(
        {
            "entity": reminder.cal_entity,
            "uid": reminder.cal_uid,
            "marker": reminder.uid,
            "due": (reminder.cal_synced_due or reminder.due_date).isoformat(),
        }
    )
    save_removal_notes(session, notes)


def load_removal_notes(session: Session) -> list[dict]:
    """The stored removal notes (see ``leave_removal_note``)."""
    raw = get_setting(session, REMOVALS_SETTING)
    try:
        notes = json.loads(raw) if raw else []
    except ValueError:
        return []
    return notes if isinstance(notes, list) else []


def save_removal_notes(session: Session, notes: list[dict]) -> None:
    """Store the removal notes (an empty list clears them)."""
    set_setting(session, REMOVALS_SETTING, json.dumps(notes))


# --- Quick create -----------------------------------------------------------


def suggest_from_expense(
    expense: Expense, lead_days: int = DEFAULT_LEAD_DAYS
) -> ReminderInput:
    """
    The "Remind me" suggestion for an expense: its vehicle and category, the
    title "<title> renewal" (not repeated when it already ends in "renewal"), due at the coverage end, else a year after the
    expense date.
    """
    title = (expense.title or "").strip()
    if not title:
        title = "Renewal"
    elif not title.casefold().endswith("renewal"):
        title = f"{title} renewal"
    return ReminderInput(
        vehicle_id=expense.vehicle_id,
        title=title,
        category=expense.category.value,
        due_date=expense.coverage_end or _one_year_later(expense.date),
        lead_days=lead_days,
        expense_id=expense.id,
    )


def _one_year_later(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year + 1, day=28)


def linked_open_reminder(
    session: Session, vehicle_id: int, vehicle_field: str
) -> Reminder | None:
    """The open reminder that follows a vehicle date, if any."""
    return session.scalar(
        select(Reminder).where(
            Reminder.vehicle_id == vehicle_id,
            Reminder.vehicle_field == vehicle_field,
            Reminder.status == ReminderStatus.OPEN,
        )
    )


def follow_vehicle_date(
    session: Session, vehicle: Vehicle, vehicle_field: str, lead_days: int | None
) -> Reminder | None:
    """
    Make the reminder linked to a vehicle date match the vehicle form.

    ``lead_days`` is ``None`` when the switch is off. Off, or no date: the
    linked open reminder is deleted. On: it moves with the date, or is created.
    A reminder already done for this very date is not created again; a new
    date starts a new one.

    Returns the open reminder that now follows the date, or ``None``.
    """
    category, title = VEHICLE_FIELDS[vehicle_field]
    due = getattr(vehicle, vehicle_field)
    linked = linked_open_reminder(session, vehicle.id, vehicle_field)
    if lead_days is None or due is None:
        if linked is not None:
            delete_reminder(session, linked.id)
        return None
    if linked is not None:
        data = ReminderInput(
            vehicle.id, linked.title, linked.category.value, due, lead_days,
            linked.notes,
        )
        if (linked.due_date, linked.lead_days) != (due, lead_days):
            update_reminder(session, linked.id, data)
        return linked
    if _was_done_for(session, vehicle.id, vehicle_field, due):
        return None
    return create_reminder(
        session,
        ReminderInput(
            vehicle.id, title, category.value, due, lead_days,
            vehicle_field=vehicle_field,
        ),
    )


def _was_done_for(
    session: Session, vehicle_id: int, vehicle_field: str, due: date
) -> bool:
    return (
        session.scalar(
            select(Reminder.id).where(
                Reminder.vehicle_id == vehicle_id,
                Reminder.vehicle_field == vehicle_field,
                Reminder.status == ReminderStatus.DONE,
                Reminder.due_date == due,
            )
        )
        is not None
    )


# --- Text shared by the calendar event and the .ics file ---------------------


def event_summary(vehicle_name: str, title: str) -> str:
    """Event title (design D3): "Golf: Registration due"."""
    return f"{vehicle_name}: {title} due"


def event_description(reminder: Reminder) -> str:
    """
    Event description (design D3): the notes, a machine-readable
    ``Notify N days before`` line and the marker line.
    """
    lines = [reminder.notes] if reminder.notes else []
    unit = "day" if reminder.lead_days == 1 else "days"
    lines.append(f"Notify {reminder.lead_days} {unit} before")
    lines.append(f"{MARKER_PREFIX} {reminder.uid}")
    return "\n".join(lines)
