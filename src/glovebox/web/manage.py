"""Manage hub: links to vehicles, gas stations, import and export."""

from __future__ import annotations

from fastapi import APIRouter, Request

from glovebox.services import records
from glovebox.web.common import SessionDep, render

router = APIRouter()


@router.get("/manage")
def manage(request: Request, session: SessionDep):
    """List the management pages with a one-line summary each."""
    vehicles = records.list_vehicles(session, include_archived=True)
    stations = records.list_stations(session)
    brands = {s.brand for s in stations if s.brand}
    return render(
        request,
        "manage.html",
        vehicle_count=len(vehicles),
        vehicle_names=", ".join(v.name for v in vehicles if not v.archived),
        station_count=len(stations),
        brand_count=len(brands),
    )
