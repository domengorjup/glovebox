"""Timeline (home page): summary cards, type chips and month-grouped entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import groupby

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from glovebox.models import Expense, ExpenseCategory, Refuel, Vehicle
from glovebox.services import preferences, records, stats
from glovebox.services.stats import LastRefuel, Segment, StatsFilter
from glovebox.web import formatting
from glovebox.web.common import Chrome, SessionDep, load_chrome, render, view_filter
from glovebox.web.formatting import (
    MONTH_NAMES,
    NBSP,
    format_milli,
    money,
    month_label,
    short_date,
    with_unit,
)
from glovebox.web.refuels import consumption_by_refuel

router = APIRouter()

DASH = "–"
CONSUMPTION_UNIT = "L/100" + NBSP + "km"
TYPES = ("all", "refuel", "service", "expense")
CARD_LABELS = {
    "cost_month": "Cost this month",
    "consumption": "Avg consumption",
    "last_refuel": "Last refuel",
    "cost_km": "Cost per km",
    "avg_price": "Avg price per litre",
    "odometer": "Odometer",
}


@dataclass(frozen=True)
class Entry:
    """One row of the list."""

    kind: str  # refuel | service | expense
    id: int
    title: str
    detail: str
    amount_cents: int
    day: date
    vehicle: str
    edit_path: str


@dataclass(frozen=True)
class MonthGroup:
    """Entries of one calendar month."""

    label: str
    entries: list[Entry]
    total_cents: int


@dataclass(frozen=True)
class Card:
    """One summary card. ``unit`` is shown small after ``value``."""

    key: str
    label: str
    value: str
    unit: str = ""
    hint: str = ""


@dataclass
class _Figures:
    """Numbers of one vehicle behind the summary cards (last 12 months)."""

    vehicle: Vehicle
    summary: stats.VehicleSummary
    previous_month_cents: int
    window: stats.CostPerKm
    segments: list[Segment] = field(default_factory=list)
    fuel_cents: int = 0
    litres_milli: int = 0


def _window_start(today: date) -> date:
    """First day of the 12-month window, as in the vehicle summary."""
    try:
        return today.replace(year=today.year - 1) + timedelta(days=1)
    except ValueError:  # 29 February
        return today.replace(year=today.year - 1, day=28) + timedelta(days=1)


def _previous_month(today: date) -> tuple[date, date]:
    last = today.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def _figures(session: Session, vehicle: Vehicle, today: date) -> _Figures:
    start = _window_start(today)
    only = StatsFilter(vehicles=(vehicle.id,))
    first, last = _previous_month(today)
    history = records.list_refuels(session, only)
    in_window = [r for r in history if start <= r.date <= today]
    return _Figures(
        vehicle=vehicle,
        summary=stats.vehicle_summary(session, vehicle.id, today),
        previous_month_cents=stats.cost_breakdown(
            session, StatsFilter(vehicles=(vehicle.id,), date_from=first, date_to=last)
        ).total_cents,
        window=stats.cost_per_km(
            session, StatsFilter(vehicles=(vehicle.id,), date_from=start, date_to=today)
        ),
        segments=[
            s for s in stats.segments(history) if start <= s.end_date <= today
        ],
        fuel_cents=sum(r.total_cents for r in in_window),
        litres_milli=sum(r.litres_milli for r in in_window),
    )


def _per_km(figures: list[_Figures]) -> float | None:
    distance = sum(f.window.distance_km or 0 for f in figures)
    if distance <= 0:
        return None
    return sum(f.window.total_cents for f in figures) / 100 / distance


def _latest_refuel(figures: list[_Figures]) -> tuple[LastRefuel, str] | None:
    found = [(f.summary.last_refuel, f.vehicle.name) for f in figures]
    found = [(last, name) for last, name in found if last is not None]
    return max(found, key=lambda pair: pair[0].date) if found else None


def _odometer_text(figures: list[_Figures]) -> tuple[str, str, str]:
    """Value, unit and hint of the odometer card (initial reading as fallback)."""
    readings = [f.summary.last_odometer_km for f in figures]
    hint = "Latest entry"
    if not any(r is not None for r in readings):
        readings = [f.vehicle.initial_odometer for f in figures]
        hint = "Initial odometer"
    readings = [r for r in readings if r is not None]
    if not readings:
        return DASH, "", "No odometer yet"
    if len(readings) == 1:
        return f"{readings[0]:,.0f}", "km", hint
    return " / ".join(f"{r / 1000:.1f}k" for r in readings), "", hint


def build_cards(figures: list[_Figures], today: date, currency: str) -> dict[str, Card]:
    """All summary cards for the given vehicles (combined if several)."""
    this_month = sum(f.summary.cost_this_month_cents for f in figures)
    last_month = sum(f.previous_month_cents for f in figures)
    diff = this_month - last_month
    previous = MONTH_NAMES[_previous_month(today)[0].month - 1]
    sign = "+" if diff >= 0 else "-"
    consumption = stats.avg_consumption([s for f in figures for s in f.segments])
    per_km = _per_km(figures)
    litres = sum(f.litres_milli for f in figures)
    fuel = sum(f.fuel_cents for f in figures)
    latest = _latest_refuel(figures)
    odometer, odometer_unit, odometer_hint = _odometer_text(figures)
    no_fuel = "" if latest else "No refuelling yet"

    def card(key: str, value: str | None, unit: str, hint: str) -> Card:
        shown = DASH if value is None else value
        return Card(key, CARD_LABELS[key], shown, "" if value is None else unit, hint)

    cards = {
        "cost_month": card(
            "cost_month", money(this_month, currency), "",
            f"{sign}{money(abs(diff), currency)} vs {previous}",
        ),
        "consumption": card(
            "consumption",
            None if consumption is None else formatting.format_consumption(consumption),
            CONSUMPTION_UNIT, no_fuel or "Last 12 months",
        ),
        "cost_km": card(
            "cost_km", None if per_km is None else f"{per_km:.3f}",
            f"{currency}/km", "All costs, last 12 months",
        ),
        "avg_price": card(
            "avg_price", f"{fuel * 10 / litres / 1000:.3f}" if litres else None,
            f"{currency}/L", no_fuel or "Last 12 months",
        ),
        "odometer": card("odometer", odometer, odometer_unit, odometer_hint),
    }
    if latest is None:
        cards["last_refuel"] = card("last_refuel", None, "", "No refuelling yet")
    else:
        last, name = latest
        where = f"{name} · " if len(figures) > 1 else ""
        cards["last_refuel"] = card(
            "last_refuel", format_milli(last.litres_milli, 2), "L",
            f"{where}{short_date(last.date)} · {money(last.total_cents, currency)}",
        )
    return cards


def _refuel_entry(
    refuel: Refuel, names: dict[int, str], stations: dict[int, str],
    segments: dict[int, Segment],
) -> Entry:
    parts = [with_unit(format_milli(refuel.litres_milli, 2), "L")]
    if refuel.station_id in stations:
        parts.append(stations[refuel.station_id])
    segment = segments.get(refuel.id)
    if segment is not None and segment.valid:
        parts.append(with_unit(formatting.format_consumption(segment.consumption),
                               "L/100" + NBSP + "km"))
    return Entry(
        "refuel", refuel.id, "Refuelling", " · ".join(parts), refuel.total_cents,
        refuel.date, names.get(refuel.vehicle_id, ""), f"/refuels/{refuel.id}/edit",
    )


def _expense_entry(expense: Expense, names: dict[int, str]) -> Entry:
    service = expense.category is ExpenseCategory.MAINTENANCE
    if service:
        detail = expense.notes or ""
    else:
        label = expense.category.value.capitalize()
        if expense.coverage_start:
            detail = f"{label} · covers {expense.coverage_start} → {expense.coverage_end}"
        else:
            detail = f"{label} · {expense.notes}" if expense.notes else label
    return Entry(
        "service" if service else "expense", expense.id, expense.title, detail,
        expense.amount_cents, expense.date, names.get(expense.vehicle_id, ""),
        f"/expenses/{expense.id}/edit",
    )


def build_entries(session: Session, chrome: Chrome, kind: str) -> list[Entry]:
    """Entries of the selected vehicle(s), newest first, limited to ``kind``."""
    flt = view_filter(chrome)
    names = {v.id: v.name for v in chrome.vehicles + chrome.archived}
    entries: list[Entry] = []
    if kind in ("all", "refuel"):
        refuels = records.list_refuels(session, flt)
        stations = {s.id: s.name for s in records.list_stations(session)}
        segments = consumption_by_refuel(session, {r.vehicle_id for r in refuels})
        entries += [_refuel_entry(r, names, stations, segments) for r in refuels]
    if kind != "refuel":
        for expense in records.list_expenses(session, flt):
            entry = _expense_entry(expense, names)
            if kind == "all" or entry.kind == kind:
                entries.append(entry)
    return sorted(entries, key=lambda e: (e.day, e.kind, e.id), reverse=True)


def group_by_month(entries: list[Entry]) -> list[MonthGroup]:
    """Group newest-first entries by calendar month."""
    return [
        MonthGroup(month_label(*key), group, sum(e.amount_cents for e in group))
        for key, items in groupby(entries, key=lambda e: (e.day.year, e.day.month))
        for group in [list(items)]
    ]


@router.get("/")
def timeline(request: Request, session: SessionDep, type: str = "all"):
    """Summary cards, filter chips and the month-grouped entry list."""
    if type not in TYPES:
        raise HTTPException(422, detail=f"type: '{type}' is not one of {', '.join(TYPES)}")
    chrome = load_chrome(session)
    today = date.today()
    currency = request.app.state.settings.currency
    everyone = chrome.vehicles + chrome.archived
    combined = not chrome.selected_ids
    shown = everyone if combined else [v for v in everyone if v.id == chrome.selected_ids[0]]
    figures = [_figures(session, v, today) for v in shown]
    groups = []
    if combined and len(chrome.vehicles) > 1:
        groups = [
            (f.vehicle.name, build_cards([f], today, currency))
            for f in figures if not f.vehicle.archived
        ]
    return render(
        request,
        "timeline.html",
        chrome=chrome,
        section="timeline",
        type=type,
        cards=build_cards(figures, today, currency) if figures else {},
        card_order=list(preferences.CARD_KEYS),
        card_labels=CARD_LABELS,
        chosen_cards=preferences.get_summary_cards(session),
        vehicle_groups=groups,
        months=group_by_month(build_entries(session, chrome, type)),
        has_vehicles=bool(everyone),
        title="All vehicles" if combined else shown[0].name,
    )


@router.get("/add")
def add_entry(request: Request, session: SessionDep):
    """Chooser dialog behind the floating + button."""
    return render(request, "add.html", section="timeline")
