"""Vehicle pages: list, create/edit (dialogs), archive, delete with confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.services import records, reminders
from glovebox.services.stats import StatsFilter
from glovebox.services.records import (
    ConfirmationRequired,
    ValidationError,
    VehicleInput,
)
from glovebox.models import Vehicle
from glovebox.web.formatting import parse_decimal
from glovebox.web.reminders import sync_after_save
from glovebox.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/vehicles")


# Start of the messages about fields inside the "More details" section.
_DETAIL_MESSAGES = ("Model year", "Insurance valid", "Registration valid", "Remind me")


class VehicleForm(BaseModel):
    """Raw (string) form fields; parsing and errors are handled in one place."""

    name: str = ""
    make: str = ""
    model: str = ""
    plate: str = ""
    fuel_type: str = ""
    initial_odometer: str = ""
    notes: str = ""
    vin: str = ""
    model_year: str = ""
    engine: str = ""
    tyre_size: str = ""
    insurance_policy: str = ""
    insurance_valid_until: str = ""
    registration_valid_until: str = ""
    # "Remind me N days before" next to the two dates ("1" = on).
    insurance_remind: str = ""
    insurance_remind_days: str = str(reminders.DEFAULT_LEAD_DAYS)
    registration_remind: str = ""
    registration_remind_days: str = str(reminders.DEFAULT_LEAD_DAYS)


# Form prefix -> the vehicle date field that a reminder follows.
_REMIND_FIELDS = {
    "insurance": "insurance_valid_until",
    "registration": "registration_valid_until",
}


def _apply_reminders(session: Session, vehicle: Vehicle, form: VehicleForm) -> None:
    """Make the reminders that follow the vehicle's dates match the form switches."""
    for prefix, vehicle_field in _REMIND_FIELDS.items():
        lead_days = None
        if getattr(form, f"{prefix}_remind") == "1":
            text = getattr(form, f"{prefix}_remind_days")
            try:
                lead_days = int(text)
            except ValueError:
                raise ValueError("Remind me: enter a whole number of days") from None
        reminders.follow_vehicle_date(session, vehicle, vehicle_field, lead_days)


def _remind_values(session: Session, vehicle: Vehicle | None) -> dict[str, str]:
    """Switch state of the form for a stored vehicle (a linked open reminder = on)."""
    values: dict[str, str] = {}
    for prefix, vehicle_field in _REMIND_FIELDS.items():
        linked = (
            reminders.linked_open_reminder(session, vehicle.id, vehicle_field)
            if vehicle else None
        )
        values[f"{prefix}_remind"] = "1" if linked else ""
        values[f"{prefix}_remind_days"] = str(
            linked.lead_days if linked else reminders.DEFAULT_LEAD_DAYS
        )
    return values


def _whole_number(text: str, label: str) -> int | None:
    """Parse a whole number (blank is unset); ``ValueError`` otherwise."""
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{label} must be a whole number") from None


def _day(text: str, label: str) -> date | None:
    """Parse ``YYYY-MM-DD`` (blank is unset); ``ValueError`` otherwise."""
    text = text.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{label} is not a date (YYYY-MM-DD)") from None


def _vehicle_input(form: VehicleForm) -> VehicleInput:
    """Build the service input from raw form text (blank means unset)."""
    odometer = parse_decimal(form.initial_odometer, "Initial odometer")
    return VehicleInput(
        name=form.name.strip(),
        make=form.make.strip() or None,
        model=form.model.strip() or None,
        plate=form.plate.strip() or None,
        fuel_type=form.fuel_type.strip() or None,
        initial_odometer=None if odometer is None else float(odometer),
        notes=form.notes.strip() or None,
        vin=form.vin,
        model_year=_whole_number(form.model_year, "Model year"),
        engine=form.engine,
        tyre_size=form.tyre_size,
        insurance_policy=form.insurance_policy,
        insurance_valid_until=_day(
            form.insurance_valid_until, "Insurance valid until"
        ),
        registration_valid_until=_day(
            form.registration_valid_until, "Registration valid until"
        ),
    )


@dataclass(frozen=True)
class VehicleRow:
    """A vehicle with the small stat line shown in the list."""

    vehicle: Vehicle
    records: int
    odometer: float | None


def _rows(session: Session, vehicles: list[Vehicle]) -> list[VehicleRow]:
    """Record count and last odometer reading for each vehicle."""
    rows = []
    for vehicle in vehicles:
        only = StatsFilter(vehicles=(vehicle.id,))
        refuels = records.list_refuels(session, only)
        expenses = records.list_expenses(session, only)
        readings = [r.odometer_km for r in refuels]
        readings += [e.odometer_km for e in expenses if e.odometer_km is not None]
        last = max(readings) if readings else vehicle.initial_odometer
        rows.append(VehicleRow(vehicle, len(refuels) + len(expenses), last))
    return rows


def _list_page(request: Request, session: Session, status: int = 200,
               errors: list[str] | None = None):
    every = records.list_vehicles(session, include_archived=True)
    return render(
        request, "vehicles/list.html", status,
        active=_rows(session, [v for v in every if not v.archived]),
        archived=_rows(session, [v for v in every if v.archived]),
        errors=errors or [],
    )


@router.get("")
def vehicle_list(request: Request, session: SessionDep):
    """List all vehicles; archived ones sit in a collapsible section."""
    return _list_page(request, session)


@router.get("/new")
def vehicle_new(request: Request, session: SessionDep):
    """Empty vehicle form."""
    return render(
        request, "vehicles/form.html", vehicle=None, errors=[],
        remind=_remind_values(session, None),
    )


@router.post("/new")
def vehicle_create(
    request: Request, session: SessionDep, form: Annotated[VehicleForm, Form()]
):
    """Create a vehicle, or show the form again with the validation messages."""
    try:
        vehicle = records.create_vehicle(session, _vehicle_input(form))
        _apply_reminders(session, vehicle, form)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        return _form_error(request, None, form, exc)
    session.commit()
    sync_after_save(request)
    return redirect(request, "/vehicles")


@router.get("/{vehicle_id}/edit")
def vehicle_edit(request: Request, vehicle_id: int, session: SessionDep):
    """Vehicle form filled with the current values."""
    vehicle = records.get_vehicle(session, vehicle_id)
    return render(
        request, "vehicles/form.html", vehicle=vehicle, errors=[],
        remind=_remind_values(session, vehicle),
    )


@router.post("/{vehicle_id}/edit")
def vehicle_update(
    request: Request,
    vehicle_id: int,
    session: SessionDep,
    form: Annotated[VehicleForm, Form()],
):
    """Save changes to a vehicle."""
    try:
        vehicle = records.update_vehicle(session, vehicle_id, _vehicle_input(form))
        _apply_reminders(session, vehicle, form)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        vehicle = records.get_vehicle(session, vehicle_id)
        return _form_error(request, vehicle, form, exc)
    session.commit()
    sync_after_save(request)
    return redirect(request, "/vehicles")


@router.post("/{vehicle_id}/archive")
def vehicle_archive(
    request: Request,
    vehicle_id: int,
    session: SessionDep,
    archived: Annotated[str, Form()] = "1",
):
    """Archive (``archived=1``) or restore (``archived=0``) a vehicle."""
    try:
        records.archive_vehicle(session, vehicle_id, archived == "1")
    except ValidationError as exc:
        session.rollback()
        return _list_page(request, session, 422, exc.messages)
    return redirect(request, "/vehicles")


@router.get("/{vehicle_id}/delete")
def vehicle_delete_confirm(request: Request, vehicle_id: int, session: SessionDep):
    """Confirmation page showing how many records would be deleted."""
    vehicle = records.get_vehicle(session, vehicle_id)
    counts = records.count_vehicle_records(session, vehicle_id)
    return render(request, "vehicles/delete.html", vehicle=vehicle, counts=counts)


@router.post("/{vehicle_id}/delete")
def vehicle_delete(
    request: Request,
    vehicle_id: int,
    session: SessionDep,
    confirm: Annotated[str, Form()] = "",
):
    """Delete the vehicle; records are deleted only with ``confirm=1``."""
    try:
        records.delete_vehicle(session, vehicle_id, confirm=confirm == "1")
    except ConfirmationRequired:
        session.rollback()
        return redirect(request, f"/vehicles/{vehicle_id}/delete")
    session.commit()
    sync_after_save(request)  # removes the calendar events of its reminders
    return redirect(request, "/vehicles")


def _form_error(request, vehicle, form: VehicleForm, exc):
    """Re-render the vehicle form with the entered values and messages."""
    messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
    detail_error = any(m.startswith(_DETAIL_MESSAGES) for m in messages)
    return render(request, "vehicles/form.html", 422, vehicle=vehicle,
                  entered=form.model_dump(), errors=messages,
                  detail_error=detail_error, remind=form.model_dump())
