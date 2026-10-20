"""Vehicle pages: list, create/edit, archive, delete with confirmation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request

from autotracker.services import records
from autotracker.services.records import (
    ConfirmationRequired,
    ValidationError,
    VehicleInput,
)
from autotracker.web.formatting import parse_decimal
from autotracker.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/vehicles")


def _vehicle_input(
    name: str,
    make: str,
    model: str,
    plate: str,
    fuel_type: str,
    initial_odometer: str,
    notes: str,
) -> VehicleInput:
    """Build the service input from raw form text (blank means unset)."""
    odometer = parse_decimal(initial_odometer, "Initial odometer")
    return VehicleInput(
        name=name.strip(),
        make=make.strip() or None,
        model=model.strip() or None,
        plate=plate.strip() or None,
        fuel_type=fuel_type.strip() or None,
        initial_odometer=None if odometer is None else float(odometer),
        notes=notes.strip() or None,
    )


@router.get("")
def vehicle_list(request: Request, session: SessionDep):
    """List all vehicles, archived ones included."""
    vehicles = records.list_vehicles(session, include_archived=True)
    return render(request, "vehicles/list.html", vehicles=vehicles)


@router.get("/new")
def vehicle_new(request: Request):
    """Empty vehicle form."""
    return render(request, "vehicles/form.html", vehicle=None, errors=[])


@router.post("/new")
def vehicle_create(
    request: Request,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    make: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    plate: Annotated[str, Form()] = "",
    fuel_type: Annotated[str, Form()] = "",
    initial_odometer: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    """Create a vehicle, or show the form again with the validation messages."""
    try:
        data = _vehicle_input(
            name, make, model, plate, fuel_type, initial_odometer, notes
        )
        records.create_vehicle(session, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        return _form_error(request, None, name, make, model, plate, fuel_type,
                           initial_odometer, notes, exc)
    return redirect(request, "/vehicles")


@router.get("/{vehicle_id}/edit")
def vehicle_edit(request: Request, vehicle_id: int, session: SessionDep):
    """Vehicle form filled with the current values."""
    vehicle = records.get_vehicle(session, vehicle_id)
    return render(request, "vehicles/form.html", vehicle=vehicle, errors=[])


@router.post("/{vehicle_id}/edit")
def vehicle_update(
    request: Request,
    vehicle_id: int,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    make: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    plate: Annotated[str, Form()] = "",
    fuel_type: Annotated[str, Form()] = "",
    initial_odometer: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    """Save changes to a vehicle."""
    try:
        data = _vehicle_input(
            name, make, model, plate, fuel_type, initial_odometer, notes
        )
        records.update_vehicle(session, vehicle_id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        vehicle = records.get_vehicle(session, vehicle_id)
        return _form_error(request, vehicle, name, make, model, plate, fuel_type,
                           initial_odometer, notes, exc)
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
        vehicles = records.list_vehicles(session, include_archived=True)
        return render(request, "vehicles/list.html", 422,
                      vehicles=vehicles, errors=exc.messages)
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
    return redirect(request, "/vehicles")


def _form_error(request, vehicle, name, make, model, plate, fuel_type,
                initial_odometer, notes, exc):
    """Re-render the vehicle form with the entered values and messages."""
    messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
    entered = {
        "name": name, "make": make, "model": model, "plate": plate,
        "fuel_type": fuel_type, "initial_odometer": initial_odometer,
        "notes": notes,
    }
    return render(request, "vehicles/form.html", 422,
                  vehicle=vehicle, entered=entered, errors=messages)
