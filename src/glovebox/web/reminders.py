"""
Reminder routes: the Reminders page, the reminder dialog (create and edit),
the .ics download, done / reopen / delete, the calendar choice and "Sync now".
Each POST redirects to ``next`` (an in-app path, default ``/reminders``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.ics import reminder_ics
from glovebox.models import (
    CalendarState,
    Expense,
    ExpenseCategory,
    Reminder,
    ReminderStatus,
    Vehicle,
)
from glovebox.services import reminder_sync, reminders
from glovebox.services.reminder_sync import SAVE_DEADLINE_SECONDS
from glovebox.services.records import NotFoundError, ValidationError
from glovebox.web.common import (
    SessionDep,
    load_chrome,
    redirect,
    render,
    safe_next,
)
from glovebox.web.formatting import short_date

router = APIRouter(prefix="/reminders")

DEFAULT_NEXT = "/reminders"
NextForm = Annotated[str, Form()]
# Shown name of each category in the reminder form (maintenance is "Service").
CATEGORY_LABELS = {
    ExpenseCategory.MAINTENANCE: "Service",
    ExpenseCategory.INSURANCE: "Insurance",
    ExpenseCategory.REGISTRATION: "Registration",
    ExpenseCategory.OTHER: "Other",
}
CATEGORY_ICONS = {
    ExpenseCategory.MAINTENANCE: "wrench",
    ExpenseCategory.INSURANCE: "file-document-outline",
    ExpenseCategory.REGISTRATION: "file-document-outline",
    ExpenseCategory.OTHER: "file-document-outline",
}
UNSYNCED_STATES = (CalendarState.PENDING, CalendarState.UNCHANGED, CalendarState.ERROR)


class ReminderForm(BaseModel):
    """Raw (string) fields of the reminder dialog."""

    vehicle_id: str = ""
    title: str = ""
    category: str = ExpenseCategory.OTHER.value
    due_date: str = ""
    lead_days: str = str(reminders.DEFAULT_LEAD_DAYS)
    notes: str = ""
    expense_id: str = ""
    next: str = DEFAULT_NEXT


@dataclass(frozen=True)
class ReminderRow:
    """One reminder as a list row (Reminders page, Timeline card)."""

    id: int
    title: str
    vehicle: str
    category: ExpenseCategory
    icon: str
    detail: str
    overdue: bool
    message: str


def sync_after_save(request: Request) -> None:
    """
    Write pending reminders to the calendar, right after the commit.

    Never raises and gives up after ``SAVE_DEADLINE_SECONDS``; whatever is left
    is retried in the background.
    """
    request.app.state.reminder_sync.run_safely(SAVE_DEADLINE_SECONDS)


def _get(session: SessionDep, reminder_id: int):
    try:
        return reminders.get_reminder(session, reminder_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Reminder not found") from None


@router.get("/{reminder_id:int}.ics")
def reminder_download(session: SessionDep, reminder_id: int) -> Response:
    """Download one reminder as an iCalendar file."""
    reminder = _get(session, reminder_id)
    vehicle = session.get(Vehicle, reminder.vehicle_id)
    content = reminder_ics(reminder, vehicle.name if vehicle else "")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", reminder.title).strip("-").lower() or "reminder"
    return Response(
        content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="glovebox-{slug}.ics"'},
    )


@router.post("/{reminder_id:int}/done")
def reminder_done(
    request: Request, session: SessionDep, reminder_id: int, next: NextForm = DEFAULT_NEXT
):
    """Mark a reminder done."""
    _get(session, reminder_id)
    reminders.mark_done(session, reminder_id)
    session.commit()
    sync_after_save(request)
    return redirect(request, safe_next(next))


@router.post("/{reminder_id:int}/reopen")
def reminder_reopen(
    request: Request, session: SessionDep, reminder_id: int, next: NextForm = DEFAULT_NEXT
):
    """Make a done reminder open again."""
    _get(session, reminder_id)
    reminders.reopen(session, reminder_id)
    session.commit()
    sync_after_save(request)
    return redirect(request, safe_next(next))


@router.post("/{reminder_id:int}/delete")
def reminder_delete(
    request: Request, session: SessionDep, reminder_id: int, next: NextForm = DEFAULT_NEXT
):
    """Delete a reminder."""
    _get(session, reminder_id)
    reminders.delete_reminder(session, reminder_id)
    session.commit()
    sync_after_save(request)
    return redirect(request, safe_next(next))


@router.post("/calendar")
def reminder_calendar(
    request: Request,
    session: SessionDep,
    entity_id: Annotated[str, Form()] = "",
    next: NextForm = DEFAULT_NEXT,
):
    """Choose the calendar (empty = None). Ignored without Home Assistant."""
    if request.app.state.reminder_sync.available:
        reminder_sync.set_calendar(session, entity_id)
        session.commit()
        sync_after_save(request)
    return redirect(request, safe_next(next))


@router.post("/sync")
def reminder_sync_now(request: Request, session: SessionDep, next: NextForm = DEFAULT_NEXT):
    """Run the calendar sync at once ("Sync now")."""
    sync_after_save(request)
    return redirect(request, safe_next(next))


# --- Rows -------------------------------------------------------------------


def _long_date(day: date) -> str:
    return f"{short_date(day)} {day.year}"


def build_rows(
    session: Session, items: list[Reminder], today: date, show_message: bool = True
) -> list[ReminderRow]:
    """Turn reminders into list rows with their wording ("Due 1 Mar 2027 · in 12 days")."""
    names = {v.id: v.name for v in session.query(Vehicle)}
    rows = []
    for item in items:
        days = reminders.days_until_due(item, today)
        overdue = reminders.is_overdue(item, today)
        due = f"Due {_long_date(item.due_date)}"
        detail = f"{due} \u00b7 {reminders.due_text(days)}" if item.status is ReminderStatus.OPEN else due
        unsynced = item.cal_state in UNSYNCED_STATES and item.status is ReminderStatus.OPEN
        rows.append(
            ReminderRow(
                item.id, item.title, names.get(item.vehicle_id, ""), item.category,
                CATEGORY_ICONS[item.category], detail, overdue,
                (item.cal_message or "") if show_message and unsynced else "",
            )
        )
    return rows


def _calendar_choices(request: Request) -> tuple[list, str | None]:
    """Calendars to choose from (add-on mode only) and a listing problem."""
    sync = request.app.state.reminder_sync
    return sync.list_choices() if sync.available else ([], None)


# --- The Reminders page -------------------------------------------------------


@router.get("")
def reminders_page(request: Request, session: SessionDep):
    """Open and done reminders of the app-bar vehicle, and the calendar setting."""
    chrome = load_chrome(session)
    today = date.today()
    ids = chrome.selected_ids
    sync = request.app.state.reminder_sync
    status = reminder_sync.calendar_status(session, sync.available)
    choices, listing_problem = _calendar_choices(request)
    options = [("", "None")]
    # The chosen calendar may be gone or unable to take events: keep it in the
    # list so the select still shows the stored choice.
    if status.entity_id and not listing_problem and status.entity_id not in {
        c.entity_id for c in choices
    }:
        options.append((status.entity_id, f"{status.entity_id} - not available"))
    options += [(c.entity_id, f"{c.name} - {c.capability}") for c in choices]
    return render(
        request,
        "reminders/index.html",
        open_rows=build_rows(
            session, reminders.list_reminders(session, ids, ReminderStatus.OPEN), today
        ),
        done_rows=build_rows(
            session, reminders.list_reminders(session, ids, ReminderStatus.DONE), today
        ),
        status=status,
        calendar_options=options,
        listing_problem=listing_problem,
    )


# --- The dialog ---------------------------------------------------------------


def _form_values(reminder: Reminder) -> dict[str, str]:
    return ReminderForm(
        vehicle_id=str(reminder.vehicle_id),
        title=reminder.title,
        category=reminder.category.value,
        due_date=reminder.due_date.isoformat(),
        lead_days=str(reminder.lead_days),
        notes=reminder.notes or "",
        expense_id=str(reminder.expense_id or ""),
    ).model_dump()


def _form_page(
    request: Request, session: Session, entered: dict[str, str],
    reminder: Reminder | None = None, status: int = 200,
    errors: list[str] | None = None,
):
    chrome = load_chrome(session)
    vehicles = list(chrome.vehicles)
    shown = entered.get("vehicle_id", "")
    if shown.isdigit() and not any(str(v.id) == shown for v in vehicles):
        archived = session.get(Vehicle, int(shown))
        if archived is not None:
            vehicles.append(archived)
    source = None
    if entered.get("expense_id", "").isdigit():
        source = session.get(Expense, int(entered["expense_id"]))
    sync = request.app.state.reminder_sync
    return render(
        request, "reminders/form.html", status,
        section="timeline", f=entered, reminder=reminder, vehicles=vehicles,
        categories=[(c.value, CATEGORY_LABELS[c]) for c in ExpenseCategory],
        source=source, errors=errors or [], calendar_line=_calendar_line(reminder),
        can_sync=sync.available and reminder is not None
        and reminder.cal_state in UNSYNCED_STATES,
    )


def _calendar_line(reminder: Reminder | None) -> str:
    """One line on where the reminder is in the calendar, or ``""``."""
    if reminder is None or reminder.status is not ReminderStatus.OPEN:
        return ""
    if reminder.cal_state is CalendarState.SYNCED:
        return f"In calendar {reminder.cal_entity}"
    return reminder.cal_message or ""


@router.get("/new")
def reminder_new(
    request: Request, session: SessionDep, vehicle: str = "", expense: int | None = None,
    next: str = DEFAULT_NEXT,
):
    """Empty reminder form, or pre-filled from an expense ("Remind me")."""
    if expense is not None:
        source = session.get(Expense, expense)
        if source is None:
            raise HTTPException(status_code=404, detail="Expense not found")
        data = reminders.suggest_from_expense(source)
        entered = ReminderForm(
            vehicle_id=str(data.vehicle_id), title=data.title, category=data.category,
            due_date=data.due_date.isoformat(), lead_days=str(data.lead_days),
            expense_id=str(source.id), next=safe_next(next),
        ).model_dump()
    else:
        entered = ReminderForm(
            vehicle_id=vehicle or load_chrome(session).form_vehicle,
            next=safe_next(next),
        ).model_dump()
    return _form_page(request, session, entered)


@router.get("/{reminder_id:int}/edit")
def reminder_edit(
    request: Request, session: SessionDep, reminder_id: int, next: str = DEFAULT_NEXT
):
    """Reminder form filled from a stored reminder."""
    reminder = _get(session, reminder_id)
    entered = _form_values(reminder) | {"next": safe_next(next)}
    return _form_page(request, session, entered, reminder)


def _parse(form: ReminderForm) -> reminders.ReminderInput:
    """Convert raw form text; ``ValueError`` carries a message for the user."""
    if not form.vehicle_id.isdigit():
        raise ValueError("Choose a vehicle")
    try:
        due = date.fromisoformat(form.due_date) if form.due_date else None
    except ValueError:
        raise ValueError("Due date: enter a valid date") from None
    try:
        lead_days = int(form.lead_days)
    except ValueError:
        raise ValueError("Notify: enter a whole number of days") from None
    return reminders.ReminderInput(
        vehicle_id=int(form.vehicle_id), title=form.title, category=form.category,
        due_date=due, lead_days=lead_days, notes=form.notes,
        expense_id=int(form.expense_id) if form.expense_id.isdigit() else None,
    )


def _save(
    request: Request, session: Session, form: ReminderForm, reminder: Reminder | None
):
    try:
        data = _parse(form)
        if reminder is None:
            reminders.create_reminder(session, data)
        else:
            reminders.update_reminder(session, reminder.id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _form_page(
            request, session, form.model_dump(),
            reminder and reminders.get_reminder(session, reminder.id), 422, messages,
        )
    session.commit()
    sync_after_save(request)
    return redirect(request, safe_next(form.next))


@router.post("/new")
def reminder_create(request: Request, session: SessionDep, form: Annotated[ReminderForm, Form()]):
    """Create a reminder."""
    return _save(request, session, form, None)


@router.post("/{reminder_id:int}/edit")
def reminder_update(
    request: Request, session: SessionDep, reminder_id: int,
    form: Annotated[ReminderForm, Form()],
):
    """Save changes to a reminder."""
    return _save(request, session, form, _get(session, reminder_id))
