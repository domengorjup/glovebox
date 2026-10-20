"""Station management: rename, bulk brand, merge. Brands are set by hand only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request

from autotracker.services import records
from autotracker.services.records import StationInput, ValidationError
from autotracker.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/stations")


def _list_page(request: Request, session, status: int = 200,
               errors: list[str] | None = None):
    return render(request, "stations/list.html", status,
                  stations=records.list_stations(session), errors=errors or [])


@router.get("")
def station_list(request: Request, session: SessionDep):
    """All stations with bulk-brand and merge forms."""
    return _list_page(request, session)


@router.get("/{station_id}/edit")
def station_edit(request: Request, station_id: int, session: SessionDep):
    """Edit name, location and brand of one station."""
    station = records.get_station(session, station_id)
    return render(request, "stations/form.html", station=station, errors=[])


@router.post("/{station_id}/edit")
def station_update(
    request: Request,
    station_id: int,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    brand: Annotated[str, Form()] = "",
):
    """Save one station."""
    data = StationInput(
        name=name.strip(),
        brand=brand.strip() or None,
        location=location.strip() or None,
    )
    try:
        records.update_station(session, station_id, data)
    except ValidationError as exc:
        session.rollback()
        station = records.get_station(session, station_id)
        return render(request, "stations/form.html", 422, station=station,
                      entered=data, errors=exc.messages)
    return redirect(request, "/stations")


@router.post("/brand")
def station_bulk_brand(
    request: Request,
    session: SessionDep,
    station_ids: Annotated[list[int] | None, Form()] = None,
    brand: Annotated[str, Form()] = "",
    clear: Annotated[str, Form()] = "",
):
    """Set the brand of the selected stations, or clear it with ``clear=1``."""
    if not station_ids:
        return _list_page(request, session, 422, ["Select at least one station"])
    new_brand = None if clear == "1" else brand.strip() or None
    if clear != "1" and new_brand is None:
        return _list_page(request, session, 422, ["Enter a brand to set"])
    try:
        records.set_brand_bulk(session, station_ids, new_brand)
    except ValidationError as exc:
        session.rollback()
        return _list_page(request, session, 422, exc.messages)
    return redirect(request, "/stations")


@router.post("/merge")
def station_merge(
    request: Request,
    session: SessionDep,
    source_id: Annotated[int, Form()],
    target_id: Annotated[int, Form()],
):
    """Merge ``source_id`` into ``target_id``."""
    if source_id == target_id:
        return _list_page(request, session, 422, ["Choose two different stations"])
    try:
        records.merge_stations(session, source_id, target_id)
    except ValidationError as exc:
        session.rollback()
        return _list_page(request, session, 422, exc.messages)
    return redirect(request, "/stations")
