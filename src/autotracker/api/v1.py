"""
Stats API under ``/api/v1`` (design D10).

Read-only JSON. Every number comes from ``autotracker.services.stats`` so the
API and the HTML pages cannot diverge. Money is reported in currency units
(cents / 100), litres as litres, prices per litre in currency units.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from autotracker.db import get_session
from autotracker.services import records, stats
from autotracker.services.stats import Allocation, GroupBy, StatsFilter

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _money(cents: int | None) -> float | None:
    """Convert integer cents to currency units."""
    return None if cents is None else round(cents / 100, 2)


def _litres(milli: int | None) -> float | None:
    """Convert integer millilitres to litres."""
    return None if milli is None else round(milli / 1000, 3)


def _price(milli: int | None) -> float | None:
    """Convert a milli-unit price per litre to currency units."""
    return None if milli is None else round(milli / 1000, 3)


def _check_range(date_from: date | None, date_to: date | None) -> None:
    """Raise 422 when the range is reversed."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")


def _require_vehicle(session: Session, vehicle_id: int) -> None:
    """Raise a JSON 404 when the vehicle does not exist."""
    try:
        records.get_vehicle(session, vehicle_id)
    except records.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "Vehicle not found")


@router.get("/vehicles")
def list_vehicles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """List non-archived vehicles."""
    return [
        {
            "id": v.id,
            "name": v.name,
            "make": v.make,
            "model": v.model,
            "plate": v.plate,
            "fuel_type": v.fuel_type,
        }
        for v in records.list_vehicles(session)
    ]


@router.get("/vehicles/{vehicle_id}/summary")
def vehicle_summary(
    vehicle_id: int,
    request: Request,
    allocation: Allocation = Allocation.SPREAD,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Summary of one vehicle; cost fields follow ``allocation``."""
    try:
        s = stats.vehicle_summary(session, vehicle_id, date.today(), allocation)
    except records.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "Vehicle not found")
    last = s.last_refuel
    return {
        "vehicle_id": s.vehicle_id,
        "name": s.name,
        "currency": request.app.state.settings.currency,
        "allocation": s.allocation.value,
        "last_odometer_km": s.last_odometer_km,
        "last_refuel": None
        if last is None
        else {
            "date": last.date.isoformat(),
            "litres": _litres(last.litres_milli),
            "price_per_litre": _price(last.price_per_litre_milli),
            "total": _money(last.total_cents),
            "station": last.station_name,
        },
        "last_consumption": s.last_consumption,
        "avg_consumption_12m": s.avg_consumption_12m,
        "cost_this_month": _money(s.cost_this_month_cents),
        "cost_this_year": _money(s.cost_this_year_cents),
        "cost_per_km_12m": s.cost_per_km_12m,
    }


@router.get("/vehicles/{vehicle_id}/consumption")
def vehicle_consumption(
    vehicle_id: int,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Full-to-full segments (by closing date) and their weighted average."""
    _check_range(date_from, date_to)
    _require_vehicle(session, vehicle_id)
    # Segments need the earlier fills, so build from all refuels and filter after.
    refuels = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
    selected = [
        seg
        for seg in stats.segments(refuels)
        if (date_from is None or seg.end_date >= date_from)
        and (date_to is None or seg.end_date <= date_to)
    ]
    return {
        "vehicle_id": vehicle_id,
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "avg_consumption": stats.avg_consumption(selected),
        "segments": [
            {
                "end_date": seg.end_date.isoformat(),
                "station_id": seg.station_id,
                "distance_km": seg.distance_km,
                "litres": _litres(seg.litres_milli),
                "consumption": seg.consumption,
                "valid": seg.valid,
                "invalid_reason": seg.invalid_reason,
            }
            for seg in selected
        ],
    }


@router.get("/stations/stats")
def station_stats(
    vehicle: int | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_by: GroupBy = GroupBy.STATION,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Price and single-source consumption statistics per station or brand."""
    _check_range(date_from, date_to)
    if vehicle is not None:
        _require_vehicle(session, vehicle)
    flt = StatsFilter(
        vehicles=(vehicle,) if vehicle is not None else (),
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "vehicle_id": vehicle,
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "group_by": group_by.value,
        "stations": [
            {
                "key": row.key,
                "label": row.label,
                "fills": row.fills,
                "litres": _litres(row.litres_milli),
                "avg_price_per_litre": _price(row.avg_price_per_litre_milli),
                "min_price_per_litre": _price(row.min_price_per_litre_milli),
                "max_price_per_litre": _price(row.max_price_per_litre_milli),
                "consumption": row.consumption,
                "consumption_segments": row.consumption_segments,
            }
            for row in stats.station_stats(session, flt, group_by)
        ],
    }
