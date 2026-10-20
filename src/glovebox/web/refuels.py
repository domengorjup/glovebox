"""Refuel pages: filtered list, entry/edit form with warnings, delete."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.models import Refuel
from glovebox.services import records, stats
from glovebox.services.records import RefuelInput, StationInput, ValidationError
from glovebox.services.stats import StatsFilter
from glovebox.web.common import (
    SessionDep,
    effective_filter,
    filter_choices,
    parse_filters,
    redirect,
    render,
)
from glovebox.web.formatting import parse_decimal, to_scaled_int

router = APIRouter(prefix="/refuels")


class RefuelForm(BaseModel):
    """Raw (string) form fields; parsing and errors are handled in one place."""

    vehicle_id: str = ""
    date: str = ""
    time: str = ""
    odometer_km: str = ""
    litres: str = ""
    price_per_litre: str = ""
    total: str = ""
    station_id: str = ""
    new_station_name: str = ""
    new_station_location: str = ""
    is_full: str = ""
    missed_previous: str = ""
    notes: str = ""
    confirm_warnings: str = ""


def consumption_by_refuel(session: Session, vehicle_ids: set[int]) -> dict[int, stats.Segment]:
    """
    Map ending-refuel id to its segment.

    Segments need the whole history of a vehicle, so the refuels are loaded
    unfiltered.
    """
    result: dict[int, stats.Segment] = {}
    for vehicle_id in vehicle_ids:
        history = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
        for segment in stats.segments(history):
            result[segment.end_refuel_id] = segment
    return result


@router.get("")
def refuel_list(request: Request, session: SessionDep):
    """Refuels newest first, with per-row consumption (or n/a)."""
    view = parse_filters(request)
    rows = records.list_refuels(session, effective_filter(session, view.stats))
    choices = filter_choices(session)
    return render(
        request,
        "refuels/list.html",
        rows=rows,
        segments=consumption_by_refuel(session, {r.vehicle_id for r in rows}),
        vehicle_names={v.id: v.name for v in choices["all_vehicles"]},
        station_names={s.id: s.name for s in choices["all_stations"]},
        f=view.stats,
        choices=choices,
    )


def _form_from_refuel(refuel: Refuel) -> dict[str, str]:
    """Fill form fields from a stored refuel."""
    return RefuelForm(
        vehicle_id=str(refuel.vehicle_id),
        date=refuel.date.isoformat(),
        time=refuel.time.strftime("%H:%M") if refuel.time else "",
        odometer_km=f"{refuel.odometer_km:g}",
        litres=f"{refuel.litres_milli / 1000:g}",
        price_per_litre=f"{refuel.price_per_litre_milli / 1000:g}",
        total=f"{refuel.total_cents / 100:.2f}",
        station_id=str(refuel.station_id or ""),
        is_full="1" if refuel.is_full else "",
        missed_previous="1" if refuel.missed_previous else "",
        notes=refuel.notes or "",
    ).model_dump()


def _form_page(request, session, entered, refuel_id=None, status=200, **extra):
    """Render the refuel form."""
    vehicles = records.list_vehicles(session)
    selected = entered.get("vehicle_id", "")
    if selected and not any(str(v.id) == selected for v in vehicles):
        vehicles.append(records.get_vehicle(session, int(selected)))
    return render(
        request,
        "refuels/form.html",
        status,
        f=entered,
        refuel_id=refuel_id,
        vehicles=vehicles,
        stations=records.list_stations(session),
        errors=extra.pop("errors", []),
        warnings=extra.pop("warnings", []),
        **extra,
    )


@router.get("/new")
def refuel_new(request: Request, session: SessionDep, vehicle: str = ""):
    """Empty form; ``?vehicle=`` preselects a vehicle."""
    entered = RefuelForm(
        vehicle_id=vehicle, date=date.today().isoformat(), is_full="1"
    ).model_dump()
    return _form_page(request, session, entered)


@router.get("/{refuel_id}/edit")
def refuel_edit(request: Request, refuel_id: int, session: SessionDep):
    """Form filled from a stored refuel."""
    refuel = records.get_refuel(session, refuel_id)
    return _form_page(request, session, _form_from_refuel(refuel), refuel_id)


def _parse_form(form: RefuelForm) -> RefuelInput:
    """
    Convert raw form text to a service input (without the station).

    Raises
    ------
    ValueError
        With a user-presentable message for missing or malformed fields.
    """
    if not form.vehicle_id:
        raise ValueError("Choose a vehicle")
    try:
        day = date.fromisoformat(form.date)
    except ValueError:
        raise ValueError("Date: enter a valid date") from None
    odometer = parse_decimal(form.odometer_km, "Odometer")
    if odometer is None:
        raise ValueError("Odometer is required")
    try:
        at = time.fromisoformat(form.time) if form.time else None
    except ValueError:
        raise ValueError("Time: enter a valid time") from None
    return RefuelInput(
        vehicle_id=int(form.vehicle_id),
        date=day,
        time=at,
        odometer_km=float(odometer),
        litres_milli=to_scaled_int(parse_decimal(form.litres, "Litres"), 1000),
        price_per_litre_milli=to_scaled_int(
            parse_decimal(form.price_per_litre, "Price per litre"), 1000
        ),
        total_cents=to_scaled_int(parse_decimal(form.total, "Total"), 100),
        station_id=int(form.station_id) if form.station_id else None,
        is_full=form.is_full == "1",
        missed_previous=form.missed_previous == "1",
        notes=form.notes.strip() or None,
    )


def _save(request: Request, session: Session, form: RefuelForm, refuel_id: int | None):
    """Validate, show warnings once, then save."""
    entered = form.model_dump()
    try:
        data = _parse_form(form)
        preview = records.preview_refuel(session, data, exclude_id=refuel_id)
        if preview.warnings and form.confirm_warnings != "1":
            return _form_page(request, session, entered, refuel_id,
                              warnings=preview.warnings, needs_confirm=True,
                              figures=preview.figures)
        if form.new_station_name.strip():
            station = records.create_station(session, StationInput(
                name=form.new_station_name.strip(),
                location=form.new_station_location.strip() or None,
            ))
            data = replace(data, station_id=station.id)
        if refuel_id is None:
            records.create_refuel(session, data)
        else:
            records.update_refuel(session, refuel_id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _form_page(request, session, entered, refuel_id, 422, errors=messages)
    return redirect(request, "/refuels")


@router.post("/new")
def refuel_create(request: Request, session: SessionDep,
                  form: Annotated[RefuelForm, Form()]):
    """Create a refuel (after the one-time warning confirmation)."""
    return _save(request, session, form, None)


@router.post("/{refuel_id}/edit")
def refuel_update(request: Request, refuel_id: int, session: SessionDep,
                  form: Annotated[RefuelForm, Form()]):
    """Update a refuel."""
    return _save(request, session, form, refuel_id)


@router.post("/{refuel_id}/delete")
def refuel_delete(request: Request, refuel_id: int, session: SessionDep):
    """Delete a refuel."""
    records.delete_refuel(session, refuel_id)
    return redirect(request, "/refuels")
