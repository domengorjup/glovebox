"""
Reminder routes that need no template: the .ics download, done / reopen /
delete, the calendar choice and "Sync now". Each POST redirects to ``next``
(an in-app path, default ``/reminders``). The page and the dialog come with
the UI.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, Response

from glovebox.ics import reminder_ics
from glovebox.models import Vehicle
from glovebox.services import reminder_sync, reminders
from glovebox.services.reminder_sync import SAVE_DEADLINE_SECONDS
from glovebox.services.records import NotFoundError
from glovebox.web.common import SessionDep, redirect, safe_next

router = APIRouter(prefix="/reminders")

DEFAULT_NEXT = "/reminders"
NextForm = Annotated[str, Form()]


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
