"""Statistics dashboard at ``/``. All filters and the allocation mode are URL query."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from glovebox.models import ExpenseCategory
from glovebox.services import records, stats
from glovebox.services.stats import GroupBy, PeriodCost, Segment, StatsFilter
from glovebox.web.common import (
    SessionDep,
    effective_filter,
    filter_choices,
    parse_filters,
    render,
)

router = APIRouter()

COST_KEYS = ["fuel", *(c.value for c in ExpenseCategory)]


def _ms(day: date) -> int:
    """Milliseconds since the epoch at UTC midnight, the x value Chart.js uses."""
    moment = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def select_segments(
    segs: Sequence[Segment], flt: StatsFilter, station_brand: dict[int, str | None]
) -> list[Segment]:
    """Valid segments whose ending fill passes the date, station and brand filters."""
    keep = []
    for seg in segs:
        if not seg.valid:
            continue
        if flt.date_from and seg.end_date < flt.date_from:
            continue
        if flt.date_to and seg.end_date > flt.date_to:
            continue
        if flt.stations and seg.station_id not in flt.stations:
            continue
        if flt.brands and station_brand.get(seg.station_id) not in flt.brands:
            continue
        keep.append(seg)
    return keep


def consumption_chart_data(
    segs_by_vehicle: dict[str, list[Segment]],
) -> dict[str, Any]:
    """
    Build the consumption chart payload.

    Returns per-vehicle segment points and a monthly distance-weighted
    average over all given segments (not a mean of the segment values).
    """
    by_month: dict[tuple[int, int], list[Segment]] = defaultdict(list)
    points = []
    for name, segs in segs_by_vehicle.items():
        data = [
            {"x": _ms(s.end_date), "y": round(s.consumption, 2)} for s in segs
        ]
        points.append({"label": name, "data": sorted(data, key=lambda p: p["x"])})
        for seg in segs:
            by_month[(seg.end_date.year, seg.end_date.month)].append(seg)
    monthly = [
        {"x": _ms(date(year, month, 15)), "y": round(avg, 2)}
        for (year, month), group in sorted(by_month.items())
        if (avg := stats.avg_consumption(group)) is not None
    ]
    return {"segments": points, "monthly": monthly}


def cost_chart_data(series: Sequence[PeriodCost]) -> dict[str, Any]:
    """Labels plus one stacked data series per cost key (currency units)."""
    datasets = []
    for key in COST_KEYS:
        if key == "fuel":
            values = [p.fuel_cents / 100 for p in series]
        else:
            values = [p.by_category.get(ExpenseCategory(key), 0) / 100 for p in series]
        datasets.append({"key": key, "data": values})
    return {"labels": [p.period for p in series], "datasets": datasets}


def _segments_for(
    session: Session, flt: StatsFilter, vehicle_ids: Sequence[int]
) -> tuple[dict[str, list[Segment]], list[Segment]]:
    """Segments per vehicle name (filtered) and all of them flattened."""
    names = {v.id: v.name for v in records.list_vehicles(session, include_archived=True)}
    station_brand = {s.id: s.brand for s in records.list_stations(session)}
    per_vehicle: dict[str, list[Segment]] = {}
    for vehicle_id in vehicle_ids:
        # Segments need the full history; filtering happens afterwards.
        history = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
        chosen = select_segments(stats.segments(history), flt, station_brand)
        per_vehicle[names.get(vehicle_id, str(vehicle_id))] = chosen
    return per_vehicle, [s for segs in per_vehicle.values() for s in segs]


@router.get("/")
def dashboard(request: Request, session: SessionDep, group: str = "station"):
    """Charts, cost totals, cost per km and the station/brand comparison."""
    try:
        group_by = GroupBy(group)
    except ValueError:
        raise HTTPException(422, detail=f"group: '{group}' is not station or brand")
    view = parse_filters(request)
    flt = effective_filter(session, view.stats)
    breakdown = stats.cost_breakdown(session, flt, view.allocation)
    per_vehicle, all_segs = _segments_for(session, flt, flt.vehicles)
    chart_data = {
        "currency": request.app.state.settings.currency,
        "consumption": consumption_chart_data(per_vehicle),
        "monthly": cost_chart_data(breakdown.monthly),
        "yearly": cost_chart_data(breakdown.yearly),
    }
    return render(
        request,
        "dashboard.html",
        f=view.stats,
        allocation=view.allocation.value,
        breakdown=breakdown,
        cost_per_km=stats.cost_per_km(session, flt, view.allocation),
        avg_consumption=stats.avg_consumption(all_segs),
        segment_count=len(all_segs),
        station_rows=stats.station_stats(session, flt, group_by),
        group=group_by.value,
        chart_data=chart_data,
        choices=filter_choices(session),
        categories=[c.value for c in ExpenseCategory],
    )
