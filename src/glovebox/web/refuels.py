"""Refuel pages: entry/edit form (a dialog) with warnings, delete."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.models import Refuel, Station
from glovebox.services import preferences, records, stats
from glovebox.services.records import RefuelInput, StationInput, ValidationError
from glovebox.services.stats import StatsFilter
from glovebox.web.common import SessionDep, load_chrome, redirect, render
from glovebox.web import formatting
from glovebox.web.formatting import parse_decimal, to_scaled_int

router = APIRouter(prefix="/refuels")
# The phone-first quick-add page lives at /quick and shares the code below.
quick_router = APIRouter()


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
    station_choice: str = ""
    new_station_name: str = ""
    new_station_brand: str = ""
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


def _form_page(request, session, entered, refuel_id=None, status=200, quick=False,
               **extra):
    """Render the refuel form (the quick-add page when ``quick``)."""
    chrome = load_chrome(session)
    vehicles = list(chrome.vehicles)
    selected = entered.get("vehicle_id", "")
    if selected and not any(str(v.id) == selected for v in vehicles):
        vehicles.append(records.get_vehicle(session, int(selected)))
    stations = records.list_stations(session)
    # Read-only display: the fuel type belongs to the vehicle, not to the refuel.
    fuel_types = {str(v.id): v.fuel_type for v in vehicles if v.fuel_type}
    if quick:
        extra.update(_quick_context(session, entered, stations))
    return render(
        request,
        "refuels/quick.html" if quick else "refuels/form.html",
        status,
        chrome=chrome,
        section="timeline",
        f=entered,
        refuel_id=refuel_id,
        vehicles=vehicles,
        fuel_types=fuel_types,
        fuel_type=fuel_types.get(selected, ""),
        stations=stations,
        brands=sorted({s.brand for s in stations if s.brand}),
        errors=extra.pop("errors", []),
        warnings=extra.pop("warnings", []),
        **extra,
    )


@router.get("/new")
def refuel_new(request: Request, session: SessionDep, vehicle: str = ""):
    """Empty form; the vehicle defaults to the app-bar choice (``?vehicle=`` wins)."""
    default = vehicle or load_chrome(session).form_vehicle
    entered = RefuelForm(
        vehicle_id=default, date=date.today().isoformat(), is_full="1"
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
        station_id=int(form.station_id) if form.station_id.isdigit() else None,
        is_full=form.is_full == "1",
        missed_previous=form.missed_previous == "1",
        notes=form.notes.strip() or None,
    )


def _save(request: Request, session: Session, form: RefuelForm, refuel_id: int | None,
          quick: bool = False):
    """Validate, show warnings once, then save (``quick``: the quick-add page)."""
    entered = form.model_dump()
    try:
        data = _parse_form(form)
        preview = records.preview_refuel(session, data, exclude_id=refuel_id)
        if preview.warnings and form.confirm_warnings != "1":
            return _form_page(request, session, entered, refuel_id, quick=quick,
                              warnings=preview.warnings, needs_confirm=True,
                              figures=preview.figures)
        if form.new_station_name.strip():
            station = records.create_station(session, StationInput(
                name=form.new_station_name.strip(),
                brand=form.new_station_brand.strip() or None,
                location=form.new_station_location.strip() or None,
            ))
            data = replace(data, station_id=station.id)
        if refuel_id is None:
            created = records.create_refuel(session, data)
            if quick:
                _flash_saved(request, session, created)
        else:
            records.update_refuel(session, refuel_id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _form_page(request, session, entered, refuel_id, 422, quick=quick,
                          errors=messages)
    return redirect(request, "/")


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
    return redirect(request, "/")


@router.post("/{refuel_id}/undo")
def refuel_undo(request: Request, refuel_id: int, session: SessionDep):
    """Delete the refuel a quick add just created (the snackbar's Undo)."""
    try:
        records.delete_refuel(session, refuel_id)
    except records.NotFoundError:
        pass  # Already gone (Undo pressed twice): nothing to undo.
    return redirect(request, "/")


# --- Quick add (phone-first) ----------------------------------------------


def _station_choices(session: Session, vehicle_id: int) -> list[Station]:
    """
    Stations to offer as chips: the last one used, then the two most frequent.

    Only this vehicle's history counts; the list is shorter when there is not
    enough history, and the first entry is the preselected one.
    """
    history = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
    used = [r.station_id for r in history if r.station_id is not None]
    if not used:
        return []
    recent = used[0]
    # Counter keeps first-seen (newest) order for equal counts.
    frequent = [i for i, _ in Counter(used).most_common() if i != recent][:2]
    return [records.get_station(session, i) for i in [recent, *frequent]]


def _quick_context(session: Session, entered: dict, stations: list[Station]) -> dict:
    """Extra template data of the quick page: station chips and odometer hint."""
    vehicle_id = entered.get("vehicle_id", "")
    today = date.today()
    try:
        day = date.fromisoformat(entered.get("date", ""))
    except ValueError:
        day = today
    day_text = formatting.short_date(day)
    chips: list[Station] = []
    last = None
    if vehicle_id.isdigit():
        chips = _station_choices(session, int(vehicle_id))
        history = records.list_refuels(session, StatsFilter(vehicles=(int(vehicle_id),)))
        last = history[0] if history else None
    return {
        "chips": chips,
        "last_km": last.odometer_km if last else None,
        "last_km_text": formatting.format_km(last.odometer_km, grouped=True) if last else "",
        "last_date_text": formatting.short_date(last.date) if last else "",
        "today": today.isoformat(),
        "date_text": f"Today, {day_text}" if day == today else day_text,
        "default_choice": str(chips[0].id) if chips else "other",
    }


def _flash_saved(request: Request, session: Session, refuel: Refuel) -> None:
    """
    Leave the Timeline's "Refuel saved" snackbar for the next page view.

    The text is litres, total and (when this tank has one) consumption.
    """
    currency = request.app.state.settings.currency
    parts = [
        formatting.with_unit(formatting.format_milli(refuel.litres_milli, 1), "L"),
        formatting.money(refuel.total_cents, currency),
    ]
    segment = consumption_by_refuel(session, {refuel.vehicle_id}).get(refuel.id)
    if segment is not None and segment.consumption is not None:
        figure = formatting.format_consumption(segment.consumption)
        parts.append(formatting.with_unit(figure, "L/100 km"))
    preferences.set_flash(
        session, "saved", undo=f"/refuels/{refuel.id}/undo",
        text="Refuel saved \u00b7 " + " \u00b7 ".join(parts),
    )


@quick_router.get("/quick")
def quick_new(request: Request, session: SessionDep, vehicle: str = ""):
    """Quick-add page; the vehicle is ``?vehicle=``, else the app-bar/last one."""
    chrome = load_chrome(session)
    if not chrome.vehicles:
        return redirect(request, "/")
    ids = {str(v.id) for v in chrome.vehicles}
    default = vehicle if vehicle in ids else chrome.form_vehicle
    default = default or str(chrome.vehicles[0].id)
    entered = RefuelForm(
        vehicle_id=default, date=date.today().isoformat(), is_full="1"
    ).model_dump()
    return _form_page(request, session, entered, quick=True)


@quick_router.post("/quick")
def quick_create(request: Request, session: SessionDep,
                 form: Annotated[RefuelForm, Form()]):
    """Create a refuel from the quick page; time is the current time."""
    form.time = datetime.now().strftime("%H:%M")
    if form.station_choice.isdigit():
        form.station_id = form.station_choice
        form.new_station_name = ""
    elif form.station_choice != "other":
        form.station_id = ""
    return _save(request, session, form, None, quick=True)
