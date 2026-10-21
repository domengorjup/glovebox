"""Stats page: one filter bar, KPI cards, charts and the price-per-litre table."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from glovebox.models import ExpenseCategory
from glovebox.services import records, stats
from glovebox.services.stats import Allocation, GroupBy, PeriodCost, Segment, StatsFilter
from glovebox.web import formatting
from glovebox.web.common import Chrome, SessionDep, load_chrome, parse_date, render, view_filter
from glovebox.web.formatting import NBSP, format_milli, money, with_unit

router = APIRouter()

WHAT = ("all", "refuel", "service", "expense")
WHEN = ("3m", "12m", "ytd", "all", "custom")
EXPENSE_TYPES = (
    ExpenseCategory.INSURANCE,
    ExpenseCategory.REGISTRATION,
    ExpenseCategory.OTHER,
)
# Legend and bar order of the monthly cost chart; "service" is the maintenance category.
COST_KEYS = ("fuel", "service", "insurance", "registration", "other")
COST_LABELS = {
    "fuel": "Fuel", "service": "Service", "insurance": "Insurance",
    "registration": "Registration", "other": "Other",
}  # fmt: skip
CONSUMPTION_UNIT = "L/100" + NBSP + "km"


@dataclass(frozen=True)
class Query:
    """The user's choices in the filter bar, read from the URL."""

    what: str = "all"
    when: str = "12m"
    refine: str = ""
    allocation: Allocation = Allocation.SPREAD
    group: GroupBy = GroupBy.STATION
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class Kpi:
    """One KPI card."""

    label: str
    value: str
    unit: str = ""


def _choice(value: str, allowed: Sequence[str], name: str) -> str:
    if value not in allowed:
        raise HTTPException(422, detail=f"{name}: '{value}' is not one of {', '.join(allowed)}")
    return value


def parse_query(request: Request) -> Query:
    """Read and validate the filter bar parameters (422 on bad values)."""
    q = request.query_params
    try:
        allocation = Allocation(q.get("allocation") or Allocation.SPREAD)
        group = GroupBy(q.get("group") or GroupBy.STATION)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    return Query(
        what=_choice(q.get("what") or "all", WHAT, "what"),
        when=_choice(q.get("when") or "12m", WHEN, "when"),
        refine=q.get("refine") or "",
        allocation=allocation,
        group=group,
        date_from=parse_date(q.get("date_from"), "date_from"),
        date_to=parse_date(q.get("date_to"), "date_to"),
    )


def window(query: Query, today: date) -> tuple[date | None, date | None]:
    """Date range of the "When" choice; calendar months, ending today."""
    if query.when == "custom":
        return query.date_from, query.date_to
    if query.when == "all":
        return None, None
    if query.when == "ytd":
        return date(today.year, 1, 1), today
    count = 3 if query.when == "3m" else 12
    index = today.year * 12 + today.month - 1 - (count - 1)
    return date(index // 12, index % 12 + 1, 1), today


def build_filter(query: Query, chrome: Chrome, today: date) -> StatsFilter:
    """Translate the filter bar into a ``StatsFilter`` (422 on a bad refine)."""
    date_from, date_to = window(query, today)
    flt = replace(view_filter(chrome), date_from=date_from, date_to=date_to)
    if query.what == "service":
        return replace(flt, categories=(ExpenseCategory.MAINTENANCE,))
    if query.what == "expense":
        try:
            chosen = (ExpenseCategory(query.refine),) if query.refine else EXPENSE_TYPES
        except ValueError:
            raise HTTPException(422, detail=f"refine: '{query.refine}' is not an expense type") from None
        if any(c is ExpenseCategory.MAINTENANCE for c in chosen):
            raise HTTPException(422, detail="refine: service is chosen under What")
        return replace(flt, categories=chosen)
    if query.what == "refuel" and query.refine:
        kind, _, value = query.refine.partition(":")
        if kind == "st" and value.isdigit():
            return replace(flt, stations=(int(value),))
        if kind == "br" and value:
            return replace(flt, brands=(value,))
        raise HTTPException(422, detail=f"refine: '{query.refine}' is not st:<id> or br:<brand>")
    return flt


def _included(query: Query, flt: StatsFilter) -> tuple[bool, set[ExpenseCategory]]:
    """Whether fuel counts, and which expense categories count."""
    if query.what == "refuel":
        return True, set()
    if query.what == "all":
        return True, set(ExpenseCategory)
    return False, set(flt.categories)


def _cost_key(category: ExpenseCategory) -> str:
    return "service" if category is ExpenseCategory.MAINTENANCE else category.value


def _month_range(flt: StatsFilter, series: dict[str, PeriodCost]) -> list[str]:
    """Month labels (``YYYY-MM``) from the window start to its end."""
    known = sorted(series)
    start = flt.date_from.strftime("%Y-%m") if flt.date_from else (known[0] if known else None)
    end = flt.date_to.strftime("%Y-%m") if flt.date_to else (known[-1] if known else None)
    if start is None or end is None:
        return []
    year, month = map(int, start.split("-"))
    months = []
    while f"{year}-{month:02d}" <= end:
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def monthly_costs(
    breakdown: stats.CostBreakdown, flt: StatsFilter, fuel: bool, cats: set[ExpenseCategory]
) -> tuple[list[str], dict[str, list[float]]]:
    """Months and, per cost key that counts, the amount in each month."""
    series = {p.period: p for p in breakdown.monthly}
    months = _month_range(flt, series)
    values: dict[str, list[float]] = {}
    if fuel:
        values["fuel"] = [series[m].fuel_cents / 100 if m in series else 0 for m in months]
    for category in ExpenseCategory:
        if category in cats:
            values[_cost_key(category)] = [
                series[m].by_category[category] / 100 if m in series else 0 for m in months
            ]
    return months, {k: values[k] for k in COST_KEYS if k in values}


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


def consumption_segments(
    session: Session, flt: StatsFilter, chrome: Chrome
) -> dict[str, list[Segment]]:
    """Filtered valid segments per vehicle name (segments need full history)."""
    names = {v.id: v.name for v in chrome.vehicles + chrome.archived}
    station_brand = {s.id: s.brand for s in records.list_stations(session)}
    result: dict[str, list[Segment]] = {}
    vehicle_ids = flt.vehicles or tuple(v.id for v in chrome.vehicles + chrome.archived)
    for vehicle_id in vehicle_ids:
        history = records.list_refuels(session, StatsFilter(vehicles=(vehicle_id,)))
        chosen = select_segments(stats.segments(history), flt, station_brand)
        result[names.get(vehicle_id, str(vehicle_id))] = chosen
    return result


def consumption_points(per_vehicle: dict[str, list[Segment]]) -> list[dict]:
    """Chart payload: one series of dated L/100 km values per vehicle."""
    return [
        {
            "name": name,
            "points": [
                {"date": s.end_date.isoformat(), "value": round(s.consumption, 2)}
                for s in sorted(segs, key=lambda s: s.end_date)
            ],
        }
        for name, segs in per_vehicle.items()
        if segs
    ]


@dataclass(frozen=True)
class PriceRow:
    """One station or brand in the price table."""

    label: str
    sub: str
    fills: int
    litres: str
    average: str
    lowest: str
    highest: str
    consumption: str
    difference: str  # "" for the cheapest
    bar: int  # percent width of the price bar
    cheapest: bool


def price_rows(
    session: Session, flt: StatsFilter, group: GroupBy
) -> list[PriceRow]:
    """Station/brand rows, cheapest first, with the gap to the cheapest."""
    plain = replace(flt, stations=(), brands=(), categories=())
    brands = {s.id: s.brand or "" for s in records.list_stations(session)}
    found = stats.station_stats(session, plain, group)
    priced = [s for s in found if s.avg_price_per_litre_milli is not None]
    priced.sort(key=lambda s: s.avg_price_per_litre_milli)
    if not priced:
        return []
    low = priced[0].avg_price_per_litre_milli
    high = priced[-1].avg_price_per_litre_milli
    rows = []
    for i, s in enumerate(priced):
        avg = s.avg_price_per_litre_milli
        spread = max(high - low, 1)
        consumption = formatting.format_consumption(s.consumption)
        rows.append(PriceRow(
            label=s.label,
            sub=brands.get(s.key, "") if group is GroupBy.STATION else "",
            fills=s.fills,
            litres=format_milli(s.litres_milli, 2),
            average=format_milli(avg, 3),
            lowest=format_milli(s.min_price_per_litre_milli, 3),
            highest=format_milli(s.max_price_per_litre_milli, 3),
            consumption=f"{consumption} ({s.consumption_segments})",
            difference="" if i == 0 else "+" + format_milli(avg - low, 3),
            bar=round(30 + 70 * (avg - low) / spread),
            cheapest=i == 0,
        ))
    return rows


def build_kpis(
    query: Query, currency: str, total_cents: int, fuel_cents: int,
    cost: stats.CostPerKm, consumption: float | None, litres_milli: int,
    month_totals: list[float],
) -> list[Kpi]:
    """The four KPI cards that suit the "What" choice."""
    distance = cost.distance_km
    avg = Kpi("Avg consumption", formatting.format_consumption(consumption),
              CONSUMPTION_UNIT if consumption is not None else "")

    def per(cents: int, label: str) -> Kpi:
        value = cents / 100 / distance if distance and distance > 0 else None
        return Kpi(label, "n/a" if value is None else f"{value:.2f}",
                   "" if value is None else f"{currency}/km")

    if query.what == "refuel":
        price = f"{fuel_cents * 10 / litres_milli / 1000:.3f}" if litres_milli else "n/a"
        return [
            Kpi("Fuel cost", money(fuel_cents, currency)),
            avg,
            Kpi("Avg price per litre", price, f"{currency}/L" if litres_milli else ""),
            per(fuel_cents, "Cost per km"),
        ]
    if query.what == "all":
        km = "n/a" if distance is None else f"{distance:,.0f}"
        return [
            Kpi("Total cost", money(total_cents, currency)),
            Kpi("Cost per km", "n/a" if cost.per_km is None else f"{cost.per_km:.2f}",
                "" if cost.per_km is None else f"{currency}/km"),
            avg,
            Kpi("Distance", km, "" if distance is None else "km"),
        ]
    months = len(month_totals)
    per_month = round(total_cents / months) if months else None
    largest = round(max(month_totals, default=0) * 100)
    return [
        Kpi("Total cost", money(total_cents, currency)),
        Kpi("Per month", money(per_month, currency)),
        Kpi("Months", str(months)),
        Kpi("Largest month", money(largest, currency)),
    ]


@router.get("/stats")
def stats_page(request: Request, session: SessionDep):
    """Filter bar, KPIs, consumption and monthly-cost charts, price table."""
    query = parse_query(request)
    chrome = load_chrome(session)
    today = date.today()
    flt = build_filter(query, chrome, today)
    currency = formatting.currency_symbol(request.app.state.settings.currency)
    fuel, cats = _included(query, flt)

    breakdown = stats.cost_breakdown(session, flt, query.allocation)
    months, costs = monthly_costs(breakdown, flt, fuel, cats)
    totals_cents = {
        k: breakdown.fuel_cents if k == "fuel" else breakdown.by_category[
            ExpenseCategory.MAINTENANCE if k == "service" else ExpenseCategory(k)
        ]
        for k in costs
    }
    total_cents = sum(totals_cents.values())
    month_totals = [sum(costs[k][i] for k in costs) for i in range(len(months))]

    show_fuel_stats = query.what in ("all", "refuel")
    per_vehicle = consumption_segments(session, flt, chrome) if show_fuel_stats else {}
    all_segments = [s for segs in per_vehicle.values() for s in segs]
    consumption = stats.avg_consumption(all_segments)
    cost = stats.cost_per_km(session, flt, query.allocation)
    litres = sum(r.litres_milli for r in records.list_refuels(session, flt)) if show_fuel_stats else 0

    chart_data = {
        "currency": currency,
        "consumption": consumption_points(per_vehicle),
        "months": months,
        "costs": [
            {"key": k, "label": COST_LABELS[k], "values": v} for k, v in costs.items()
        ],
    }
    stations = records.list_stations(session)
    legend = [
        {"key": k, "label": COST_LABELS[k], "total": money(totals_cents[k], currency)}
        for k in costs
    ]
    title = "All vehicles" if not chrome.selected_ids else next(
        (v.name for v in chrome.vehicles + chrome.archived if v.id == chrome.selected_ids[0]), ""
    )
    return render(
        request,
        "stats.html",
        chrome=chrome,
        section="stats",
        q=query,
        title=title,
        kpis=build_kpis(query, currency, total_cents, breakdown.fuel_cents if fuel else 0,
                        cost, consumption, litres, month_totals),
        legend=legend,
        shows_expenses=bool(cats),
        shows_fuel_stats=show_fuel_stats,
        has_consumption=bool(chart_data["consumption"]),
        has_costs=any(any(v) for v in costs.values()),
        chart_data=chart_data,
        price_rows=price_rows(session, flt, query.group) if show_fuel_stats else [],
        segment_count=len(all_segments),
        brands=sorted({s.brand for s in stations if s.brand}),
        stations=stations,
        expense_types=[c.value for c in EXPENSE_TYPES],
    )
