"""Timeline (home page): summary cards, type chips and month-grouped entries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from itertools import groupby

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from glovebox.models import Expense, ExpenseCategory, Refuel, Vehicle
from glovebox.services import periods, preferences, records, reminders, stats
from glovebox.services.stats import LastRefuel, Segment, StatsFilter
from glovebox.web import formatting
from glovebox.web.common import Chrome, SessionDep, load_chrome, render, view_filter
from glovebox.web.formatting import (
    NBSP,
    format_milli,
    money,
    month_label,
    short_date,
    with_unit,
)
from glovebox.web.refuels import consumption_by_refuel
from glovebox.web.reminders import build_rows

router = APIRouter()

DASH = "–"
NO_FULL_EARLIER = "No full earlier period to compare"
CONSUMPTION_UNIT = "L/100" + NBSP + "km"
TYPES = ("all", "refuel", "service", "expense")
CARD_LABELS = {
    "cost_month": "Cost",
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


@dataclass(frozen=True)
class Summary:
    """One summary block: its heading owner, period and cards."""

    owner: str  # vehicle id as text, or "combined"
    name: str
    choice: preferences.PeriodChoice
    period: periods.Period
    chip_label: str
    cards: dict[str, Card]


def long_date(day: date) -> str:
    """Return ``5 May 2026``."""
    return f"{short_date(day)} {day.year}"


def range_text(start: date, end: date) -> str:
    """Return ``1 Nov 2025 – 20 Oct 2026`` (no year on the start within a year)."""
    first = short_date(start) if start.year == end.year else long_date(start)
    return f"{first} {DASH} {long_date(end)}"


def _chip_label(period: periods.Period) -> str:
    """Name of the period; a custom range shows its dates, short."""
    if period.key != periods.CUSTOM:
        return dict(periods.PERIODS)[period.key]
    if period.start.year == period.end.year:
        return f"{short_date(period.start)} {DASH} {short_date(period.end)}"
    return (
        f"{short_date(period.start)} {period.start:%y} {DASH} "
        f"{short_date(period.end)} {period.end:%y}"
    )


def _first_record(session: Session, ids: tuple[int, ...]) -> date | None:
    """Date of the earliest refuelling or expense of the vehicles."""
    flt = StatsFilter(vehicles=ids)
    days = [r.date for r in records.list_refuels(session, flt)]
    days += [e.date for e in records.list_expenses(session, flt)]
    return min(days, default=None)


def _in_period_figures(
    session: Session, ids: tuple[int, ...], period: periods.Period
) -> dict:
    """Numbers behind the cards that follow the period."""
    flt = StatsFilter(vehicles=ids, date_from=period.start, date_to=period.end)
    segments: list[Segment] = []
    fuel_cents = litres_milli = 0
    for vehicle_id in ids:
        history = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
        inside = [r for r in history if period.start <= r.date <= period.end]
        segments += [
            s for s in stats.segments(history)
            if period.start <= s.end_date <= period.end
        ]
        fuel_cents += sum(r.total_cents for r in inside)
        litres_milli += sum(r.litres_milli for r in inside)
    previous_cents = None
    if period.previous:
        before = replace(flt, date_from=period.previous[0], date_to=period.previous[1])
        previous_cents = stats.cost_breakdown(session, before).total_cents
    return {
        "cost_cents": stats.cost_breakdown(session, flt).total_cents,
        "previous_cents": previous_cents,
        "per_km": stats.cost_per_km(session, flt).per_km,
        "consumption": stats.avg_consumption(segments),
        "fuel_cents": fuel_cents,
        "litres_milli": litres_milli,
    }


def _cost_hint(
    period: periods.Period, cost_cents: int, previous_cents: int | None, currency: str,
    first_record: date | None,
) -> str:
    """
    Comparison with the earlier period, or the range when there is none.

    The comparison is made only when the earliest record of the shown vehicles
    lies on or before the start of the earlier period, so a period that data
    covers only in part is never compared.
    """
    if period.previous is None or previous_cents is None:
        return range_text(period.start, period.end)
    if first_record is None or first_record > period.previous[0]:
        return NO_FULL_EARLIER
    diff = cost_cents - previous_cents
    sign = "+" if diff >= 0 else "-"
    return f"{sign}{money(abs(diff), currency)} vs {period.previous_text}"


def _latest_refuel(
    summaries: list[tuple[Vehicle, stats.VehicleSummary]],
) -> tuple[LastRefuel, str] | None:
    found = [(s.last_refuel, v.name) for v, s in summaries]
    found = [(last, name) for last, name in found if last is not None]
    return max(found, key=lambda pair: pair[0].date) if found else None


def _odometer_text(
    summaries: list[tuple[Vehicle, stats.VehicleSummary]],
) -> tuple[str, str, str]:
    """Value, unit and hint of the odometer card (initial reading as fallback)."""
    readings = [s.last_odometer_km for _, s in summaries]
    hint = "Latest entry"
    if not any(r is not None for r in readings):
        readings = [v.initial_odometer for v, _ in summaries]
        hint = "Initial odometer"
    readings = [r for r in readings if r is not None]
    if not readings:
        return DASH, "", "No odometer yet"
    if len(readings) == 1:
        return f"{readings[0]:,.0f}", "km", hint
    return " / ".join(f"{r / 1000:.1f}k" for r in readings), "", hint


def build_cards(
    session: Session, vehicles: list[Vehicle], period: periods.Period, today: date,
    currency: str, first_record: date | None = None,
) -> dict[str, Card]:
    """
    All summary cards for the vehicles (combined if several).

    Cost, consumption, cost per km and average price follow ``period``; last
    refuel and odometer are current values.
    """
    ids = tuple(v.id for v in vehicles)
    summaries = [(v, stats.vehicle_summary(session, v.id, today)) for v in vehicles]
    fig = _in_period_figures(session, ids, period)
    when = range_text(period.start, period.end)
    latest = _latest_refuel(summaries)
    odometer, odometer_unit, odometer_hint = _odometer_text(summaries)
    no_fuel = "" if fig["litres_milli"] else "No refuelling in period"
    consumption, per_km = fig["consumption"], fig["per_km"]

    def card(key: str, value: str | None, unit: str, hint: str) -> Card:
        shown = DASH if value is None else value
        label = CARD_LABELS[key]
        if key == "cost_month" and period.key == periods.MONTH:
            label = "Cost this month"
        return Card(key, label, shown, "" if value is None else unit, hint)

    cards = {
        "cost_month": card(
            "cost_month", money(fig["cost_cents"], currency), "",
            _cost_hint(
                period, fig["cost_cents"], fig["previous_cents"], currency, first_record
            ),
        ),
        "consumption": card(
            "consumption",
            None if consumption is None else formatting.format_consumption(consumption),
            CONSUMPTION_UNIT, no_fuel or when,
        ),
        "cost_km": card(
            "cost_km", None if per_km is None else f"{per_km:.2f}",
            f"{currency}/km", no_fuel or f"All costs, {when}",
        ),
        "avg_price": card(
            "avg_price",
            f"{fig['fuel_cents'] * 10 / fig['litres_milli']:.3f}"
            if fig["litres_milli"] else None,
            f"{currency}/L", no_fuel or when,
        ),
        "odometer": card("odometer", odometer, odometer_unit, odometer_hint),
    }
    if latest is None:
        cards["last_refuel"] = card("last_refuel", None, "", "No refuelling yet")
    else:
        last, name = latest
        where = f"{name} · " if len(vehicles) > 1 else ""
        cards["last_refuel"] = card(
            "last_refuel", format_milli(last.litres_milli, 2), "L",
            f"{where}{short_date(last.date)} · {money(last.total_cents, currency)}",
        )
    return cards


def build_summary(
    session: Session, vehicles: list[Vehicle], owner: str, name: str, today: date,
    currency: str,
) -> Summary:
    """Resolve the stored period of ``owner`` and compute the cards for it."""
    choice = preferences.get_period(session, owner)
    first = _first_record(session, tuple(v.id for v in vehicles))
    period = periods.resolve(choice.key, today, first, choice.date_from, choice.date_to)
    return Summary(
        owner, name, choice, period, _chip_label(period),
        build_cards(session, vehicles, period, today, currency, first),
    )


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
    if expense.odometer_estimated and expense.odometer_km is not None:
        estimate = "≈" + NBSP + with_unit(formatting.format_km(expense.odometer_km, grouped=True), "km")
        detail = f"{detail} · {estimate}" if detail else estimate
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


def _flash_warnings(notice: dict | None) -> list[str]:
    """Message for the one-time notice left by saving an expense or service."""
    if not notice:
        return []
    if notice.get("kind") == "estimated" and notice.get("km") is not None:
        km = with_unit(formatting.format_km(notice["km"], grouped=True), "km")
        return [f"Odometer not entered \u2014 used the last recorded {km}. "
                "Edit the entry if that's wrong."]
    if notice.get("kind") == "missing":
        return ["Odometer not entered. There is no earlier reading to use, "
                "so it was left empty. Entering it is recommended."]
    return []


def _flash_saved(notice: dict | None) -> dict | None:
    """The snackbar data (text and undo path) left by a quick-add page."""
    if notice and notice.get("undo"):
        return {"undo": notice["undo"], "text": notice["text"]}
    return None


@router.get("/")
def timeline(request: Request, session: SessionDep, type: str = "all"):
    """Summary cards, filter chips and the month-grouped entry list."""
    if type not in TYPES:
        raise HTTPException(422, detail=f"type: '{type}' is not one of {', '.join(TYPES)}")
    chrome = load_chrome(session)
    notice = preferences.pop_flash(session)
    today = date.today()
    currency = formatting.currency_symbol(request.app.state.settings.currency)
    everyone = chrome.vehicles + chrome.archived
    combined = not chrome.selected_ids
    shown = everyone if combined else [v for v in everyone if v.id == chrome.selected_ids[0]]
    title = "All vehicles" if combined else shown[0].name
    owner = preferences.COMBINED if combined else str(shown[0].id)
    summary = build_summary(session, shown, owner, title, today, currency) if shown else None
    groups = []
    if combined and len(chrome.vehicles) > 1:
        groups = [
            build_summary(session, [v], str(v.id), v.name, today, currency)
            for v in chrome.vehicles
        ]
    return render(
        request,
        "timeline.html",
        chrome=chrome,
        section="timeline",
        type=type,
        summary=summary,
        cards=summary.cards if summary else {},
        card_order=list(preferences.CARD_KEYS),
        card_labels=CARD_LABELS,
        chosen_cards=preferences.get_summary_cards(session),
        vehicle_groups=groups,
        period_options=periods.PERIODS,
        summary_options=(
            [(preferences.ALL_VEHICLES, "All vehicles (combined)")]
            + [(g.owner, g.name) for g in groups]
            if groups else []
        ),
        hidden_summaries=preferences.get_hidden_summaries(session),
        warnings=_flash_warnings(notice),
        saved=_flash_saved(notice),
        due_rows=build_rows(
            session, reminders.due_soon(session, today, chrome.selected_ids), today
        ),
        months=group_by_month(build_entries(session, chrome, type)),
        has_vehicles=bool(everyone),
        title=title,
    )


@router.get("/add")
def add_entry(request: Request, session: SessionDep):
    """Chooser dialog behind the floating + button."""
    return render(request, "add.html", section="timeline")
