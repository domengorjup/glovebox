"""
Statistics service (design D4, D5). FROZEN SIGNATURES; implemented in group 2.

Used by both the HTML pages and ``/api/v1`` so numbers cannot diverge. Every
function is read-only: nothing here writes to the database.

Units: litres are ``litres_milli`` integers, money is integer cents, consumption
is a float in L/100 km.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, time, timedelta
from enum import StrEnum

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from glovebox.models import Expense, ExpenseCategory, Refuel, Station, Vehicle


class Allocation(StrEnum):
    """How expenses with coverage dates are assigned to periods (D5)."""

    SPREAD = "spread"
    PAID = "paid"


class GroupBy(StrEnum):
    """Grouping of station statistics."""

    STATION = "station"
    BRAND = "brand"


@dataclass(frozen=True)
class StatsFilter:
    """
    Selection of records. Empty tuples / ``None`` mean "no restriction".

    Attributes
    ----------
    vehicles : tuple[int, ...]
        Vehicle ids.
    date_from, date_to : date | None
        Inclusive date range.
    categories : tuple[ExpenseCategory, ...]
        Expense categories.
    stations : tuple[int, ...]
        Station ids.
    brands : tuple[str, ...]
        Station brands.
    """

    vehicles: tuple[int, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    categories: tuple[ExpenseCategory, ...] = ()
    stations: tuple[int, ...] = ()
    brands: tuple[str, ...] = ()


@dataclass(frozen=True)
class Segment:
    """
    One full-to-full consumption segment of a single vehicle.

    Attributes
    ----------
    vehicle_id : int
    start_refuel_id : int | None
        The earlier full fill ``F_j``; ``None`` if there is none.
    end_refuel_id : int
        The full fill ``F_k`` that closes the segment.
    end_date : date
        Date of ``F_k``; the segment belongs to this date.
    station_id : int | None
        Station of ``F_k``.
    single_station : bool
        True if every fill in ``(F_j, F_k]`` has the same station.
    distance_km : float | None
        ``odo(F_k) - odo(F_j)``; ``None`` when there is no ``F_j``.
    litres_milli : int
        Fuel of all fills in ``(F_j, F_k]``.
    consumption : float | None
        L/100 km; ``None`` (shown as "n/a") when the segment is invalid.
    valid : bool
    invalid_reason : str | None
        One of ``"missed"``, ``"no_previous_full"``, ``"non_positive_distance"``.
    """

    vehicle_id: int
    start_refuel_id: int | None
    end_refuel_id: int
    end_date: date
    station_id: int | None
    single_station: bool
    distance_km: float | None
    litres_milli: int
    consumption: float | None
    valid: bool
    invalid_reason: str | None = None


@dataclass(frozen=True)
class PeriodCost:
    """Cost of one month (``period="2026-03"``) or year (``"2026"``) in cents."""

    period: str
    fuel_cents: int
    by_category: dict[ExpenseCategory, int]

    @property
    def total_cents(self) -> int:
        """Fuel plus all expense categories."""
        return self.fuel_cents + sum(self.by_category.values())


@dataclass(frozen=True)
class CostBreakdown:
    """Totals and monthly/yearly series for a filter and allocation mode."""

    allocation: Allocation
    fuel_cents: int
    by_category: dict[ExpenseCategory, int]
    monthly: list[PeriodCost] = field(default_factory=list)
    yearly: list[PeriodCost] = field(default_factory=list)

    @property
    def total_cents(self) -> int:
        """Fuel plus all expense categories."""
        return self.fuel_cents + sum(self.by_category.values())


@dataclass(frozen=True)
class CostPerKm:
    """
    Cost per km for a filter.

    ``distance_km`` is max minus min odometer over all records in the period
    (D5), not counting estimated expense odometers. ``per_km`` is in currency units per km, ``None`` if distance <= 0.
    """

    allocation: Allocation
    total_cents: int
    distance_km: float | None
    per_km: float | None


@dataclass(frozen=True)
class StationStat:
    """
    Statistics of one station or brand group.

    ``key`` is the station id (``GroupBy.STATION``) or the brand string
    (``GroupBy.BRAND``); ``label`` is the display name. Prices are
    milli-units per litre. Consumption uses single-source segments only and is
    ``None`` when ``consumption_segments`` < 2.
    """

    key: int | str | None
    label: str
    fills: int
    litres_milli: int
    avg_price_per_litre_milli: int | None
    min_price_per_litre_milli: int | None
    max_price_per_litre_milli: int | None
    consumption: float | None
    consumption_segments: int


@dataclass(frozen=True)
class LastRefuel:
    """Last refuel as reported in the summary."""

    date: date
    litres_milli: int
    price_per_litre_milli: int
    total_cents: int
    station_name: str | None


@dataclass(frozen=True)
class VehicleSummary:
    """
    Per-vehicle summary behind ``GET /api/v1/vehicles/{id}/summary``.

    Values that cannot be computed are ``None``; both costs are 0 for a
    vehicle without records. Cost fields follow ``allocation``.
    """

    vehicle_id: int
    name: str
    allocation: Allocation
    last_odometer_km: float | None
    last_refuel: LastRefuel | None
    last_consumption: float | None
    avg_consumption_12m: float | None
    cost_this_month_cents: int
    cost_this_year_cents: int
    cost_per_km_12m: float | None


# --- Queries --------------------------------------------------------------


def select_refuels(flt: StatsFilter) -> Select:
    """Statement for refuels matching ``flt``, newest first."""
    stmt = select(Refuel)
    if flt.vehicles:
        stmt = stmt.where(Refuel.vehicle_id.in_(flt.vehicles))
    if flt.date_from is not None:
        stmt = stmt.where(Refuel.date >= flt.date_from)
    if flt.date_to is not None:
        stmt = stmt.where(Refuel.date <= flt.date_to)
    if flt.stations:
        stmt = stmt.where(Refuel.station_id.in_(flt.stations))
    if flt.brands:
        stmt = stmt.join(Station, Station.id == Refuel.station_id).where(
            Station.brand.in_(flt.brands)
        )
    return stmt.order_by(Refuel.date.desc(), Refuel.odometer_km.desc(), Refuel.id.desc())


def select_expenses(flt: StatsFilter, by_date: bool = True) -> Select:
    """Statement for expenses matching ``flt``, newest first.

    ``by_date=False`` ignores the date range (spread allocation needs
    expenses whose coverage, not payment date, overlaps the range). Station
    and brand filters do not apply: expenses have no station.
    """
    stmt = select(Expense)
    if flt.vehicles:
        stmt = stmt.where(Expense.vehicle_id.in_(flt.vehicles))
    if flt.categories:
        stmt = stmt.where(Expense.category.in_(flt.categories))
    if by_date and flt.date_from is not None:
        stmt = stmt.where(Expense.date >= flt.date_from)
    if by_date and flt.date_to is not None:
        stmt = stmt.where(Expense.date <= flt.date_to)
    return stmt.order_by(Expense.date.desc(), Expense.id.desc())


def _sort_key(refuel: Refuel) -> tuple:
    return (refuel.odometer_km, refuel.date, refuel.time or _MIDNIGHT, refuel.id or 0)


_MIDNIGHT = time(0, 0)


# --- Consumption ----------------------------------------------------------


def segments(refuels: Sequence[Refuel]) -> list[Segment]:
    """
    Build consumption segments from the refuels of ONE vehicle (D4).

    Parameters
    ----------
    refuels : Sequence[Refuel]
        Refuels in any order; sorted internally by (odometer, date).

    Returns
    -------
    list[Segment]
        One segment per full fill, including invalid ones (``valid=False``).
    """
    result: list[Segment] = []
    previous_full: Refuel | None = None
    pending: list[Refuel] = []  # fills after previous_full, up to the current one
    for refuel in sorted(refuels, key=_sort_key):
        pending.append(refuel)
        if not refuel.is_full:
            continue
        result.append(_build_segment(previous_full, pending))
        previous_full, pending = refuel, []
    return result


def _build_segment(start: Refuel | None, fills: list[Refuel]) -> Segment:
    end = fills[-1]
    distance = None if start is None else end.odometer_km - start.odometer_km
    litres = sum(f.litres_milli for f in fills)
    if start is None:
        reason = "no_previous_full"
    elif any(f.missed_previous for f in fills):
        reason = "missed"
    elif distance <= 0:
        reason = "non_positive_distance"
    else:
        reason = None
    consumption = litres / 1000 / distance * 100 if reason is None else None
    return Segment(
        vehicle_id=end.vehicle_id,
        start_refuel_id=None if start is None else start.id,
        end_refuel_id=end.id,
        end_date=end.date,
        station_id=end.station_id,
        single_station=len({f.station_id for f in fills}) == 1,
        distance_km=distance,
        litres_milli=litres,
        consumption=consumption,
        valid=reason is None,
        invalid_reason=reason,
    )


def avg_consumption(segs: Sequence[Segment]) -> float | None:
    """
    Distance-weighted average in L/100 km over the valid segments.

    Returns ``None`` when there is no valid segment. Not the mean of
    per-segment values.
    """
    valid = [s for s in segs if s.valid]
    if not valid:
        return None
    litres = sum(s.litres_milli for s in valid) / 1000
    return litres / sum(s.distance_km for s in valid) * 100


def _vehicle_refuels(session: Session, flt: StatsFilter) -> dict[int, list[Refuel]]:
    """All refuels per vehicle (vehicle filter only): segments need history."""
    stmt = select(Refuel)
    if flt.vehicles:
        stmt = stmt.where(Refuel.vehicle_id.in_(flt.vehicles))
    grouped: dict[int, list[Refuel]] = defaultdict(list)
    for refuel in session.scalars(stmt):
        grouped[refuel.vehicle_id].append(refuel)
    return grouped


def _in_range(day: date, flt: StatsFilter) -> bool:
    return (flt.date_from is None or day >= flt.date_from) and (
        flt.date_to is None or day <= flt.date_to
    )


# --- Costs ----------------------------------------------------------------


def _month_parts(
    amount: int, start: date, end: date
) -> list[tuple[int, int, int, int]]:
    """
    Split ``amount`` over the months of an inclusive coverage range.

    Largest-remainder method on integer cents, so the parts sum exactly to
    ``amount``. Returns ``(year, month, cents, covered_days)`` tuples.
    """
    total_days = (end - start).days + 1
    days_per_month: dict[tuple[int, int], int] = {}
    day = start
    while day <= end:
        last = date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])
        stop = min(last, end)
        days_per_month[(day.year, day.month)] = (stop - day).days + 1
        day = stop + timedelta(days=1)

    floors = {k: amount * d // total_days for k, d in days_per_month.items()}
    remainders = {k: amount * d % total_days for k, d in days_per_month.items()}
    leftover = amount - sum(floors.values())
    # Ties go to the earlier month (stable sort over insertion order).
    for key in sorted(remainders, key=lambda k: -remainders[k])[:leftover]:
        floors[key] += 1
    return [(y, m, floors[(y, m)], d) for (y, m), d in days_per_month.items()]


def _overlap_days(
    year: int, month: int, start: date, end: date, flt: StatsFilter
) -> int:
    """Days of coverage inside month and filter range."""
    first = max(start, date(year, month, 1), flt.date_from or date.min)
    last = min(
        end,
        date(year, month, calendar.monthrange(year, month)[1]),
        flt.date_to or date.max,
    )
    return max((last - first).days + 1, 0)


def _allocate_expense(
    expense: Expense, flt: StatsFilter, allocation: Allocation
) -> list[tuple[int, int, int]]:
    """``(year, month, cents)`` parts of one expense inside the filter range."""
    spread = allocation is Allocation.SPREAD and expense.coverage_start is not None
    if not spread:
        if not _in_range(expense.date, flt):
            return []
        return [(expense.date.year, expense.date.month, expense.amount_cents)]
    start, end = expense.coverage_start, expense.coverage_end
    parts = []
    for year, month, cents, covered in _month_parts(expense.amount_cents, start, end):
        inside = _overlap_days(year, month, start, end, flt)
        if inside == 0:
            continue
        # Exact when the whole month is inside the range; a range cutting a
        # month takes that month's share pro rata.
        if inside < covered:
            cents = (2 * cents * inside + covered) // (2 * covered)
        parts.append((year, month, cents))
    return parts


def _empty_categories() -> dict[ExpenseCategory, int]:
    return {category: 0 for category in ExpenseCategory}


def cost_breakdown(
    session: Session,
    flt: StatsFilter,
    allocation: Allocation = Allocation.SPREAD,
) -> CostBreakdown:
    """
    Totals plus monthly and yearly series by category (D5).

    Fuel honours every filter field; expenses honour vehicle, category and
    date range (by allocation) and are left out when a station or brand
    filter is active, since they have no station. Series contain only
    periods with a cost.
    """
    allocation = Allocation(allocation)
    months: dict[str, PeriodCost] = {}
    years: dict[str, PeriodCost] = {}

    def add(year: int, month: int, category: ExpenseCategory | None, cents: int):
        for series, label in ((months, f"{year}-{month:02d}"), (years, str(year))):
            period = series.setdefault(label, PeriodCost(label, 0, _empty_categories()))
            if category is None:
                series[label] = PeriodCost(label, period.fuel_cents + cents, period.by_category)
            else:
                period.by_category[category] += cents

    for refuel in session.scalars(select_refuels(flt)):
        add(refuel.date.year, refuel.date.month, None, refuel.total_cents)
    if not (flt.stations or flt.brands):
        for expense in session.scalars(select_expenses(flt, by_date=False)):
            for year, month, cents in _allocate_expense(expense, flt, allocation):
                add(year, month, expense.category, cents)

    by_category = _empty_categories()
    for period in years.values():
        for category, cents in period.by_category.items():
            by_category[category] += cents
    return CostBreakdown(
        allocation=allocation,
        fuel_cents=sum(p.fuel_cents for p in years.values()),
        by_category=by_category,
        monthly=[months[k] for k in sorted(months)],
        yearly=[years[k] for k in sorted(years)],
    )


def _distance_driven(session: Session, flt: StatsFilter) -> float | None:
    """Odometer span (max - min) per vehicle over records in the range, summed."""
    readings: dict[int, list[float]] = defaultdict(list)
    for refuel in session.scalars(select_refuels(flt)):
        readings[refuel.vehicle_id].append(refuel.odometer_km)
    if not (flt.stations or flt.brands):
        for expense in session.scalars(select_expenses(flt)):
            # An estimated odometer is a copy of an earlier reading; leaving it
            # out keeps it from stretching the span (D5).
            if expense.odometer_km is not None and not expense.odometer_estimated:
                readings[expense.vehicle_id].append(expense.odometer_km)
    if not readings:
        return None
    return sum(max(v) - min(v) for v in readings.values())


def cost_per_km(
    session: Session,
    flt: StatsFilter,
    allocation: Allocation = Allocation.SPREAD,
) -> CostPerKm:
    """
    Cost per km using the same allocation as ``cost_breakdown`` (D5).

    The distance is the odometer span of each vehicle; with several
    vehicles the spans are added (one max - min across cars is meaningless).
    """
    breakdown = cost_breakdown(session, flt, allocation)
    distance = _distance_driven(session, flt)
    per_km = None
    if distance is not None and distance > 0:
        per_km = breakdown.total_cents / 100 / distance
    return CostPerKm(
        allocation=breakdown.allocation,
        total_cents=breakdown.total_cents,
        distance_km=distance,
        per_km=per_km,
    )


# --- Stations -------------------------------------------------------------


def station_stats(
    session: Session,
    flt: StatsFilter,
    group_by: GroupBy = GroupBy.STATION,
) -> list[StationStat]:
    """
    Litre-weighted, min and max price plus single-source consumption (D4).

    Fills without a station (or, when grouping by brand, without a brand)
    form a group with key ``None``. Consumption uses valid segments ending in
    the date range in which every fill came from the group.
    """
    stations = {s.id: s for s in session.scalars(select(Station))}

    def key_of(station_id: int | None) -> int | str | None:
        if group_by is GroupBy.STATION:
            return station_id
        station = stations.get(station_id)
        return station.brand if station else None

    def label_of(key: int | str | None) -> str:
        if key is None:
            return "(no station)" if group_by is GroupBy.STATION else "(no brand)"
        return stations[key].name if group_by is GroupBy.STATION else str(key)

    fills: dict[int | str | None, list[Refuel]] = defaultdict(list)
    for refuel in session.scalars(select_refuels(flt)):
        fills[key_of(refuel.station_id)].append(refuel)

    seg_fuel: dict[int | str | None, list[Segment]] = defaultdict(list)
    for refuels in _vehicle_refuels(session, flt).values():
        ordered = sorted(refuels, key=_sort_key)
        position = {r.id: i for i, r in enumerate(ordered)}
        for seg in segments(ordered):
            if not seg.valid or not _in_range(seg.end_date, flt):
                continue
            start, end = position[seg.start_refuel_id], position[seg.end_refuel_id]
            keys = {key_of(r.station_id) for r in ordered[start + 1 : end + 1]}
            if len(keys) == 1:
                seg_fuel[keys.pop()].append(seg)

    stats = []
    for key, group in fills.items():
        litres = sum(r.litres_milli for r in group)
        prices = [r.price_per_litre_milli for r in group]
        weighted = sum(r.litres_milli * r.price_per_litre_milli for r in group)
        qualifying = seg_fuel.get(key, [])
        enough = len(qualifying) >= 2
        stats.append(
            StationStat(
                key=key,
                label=label_of(key),
                fills=len(group),
                litres_milli=litres,
                avg_price_per_litre_milli=round(weighted / litres) if litres else None,
                min_price_per_litre_milli=min(prices),
                max_price_per_litre_milli=max(prices),
                consumption=avg_consumption(qualifying) if enough else None,
                consumption_segments=len(qualifying),
            )
        )
    return sorted(stats, key=lambda s: (s.key is None, s.label.lower()))


# --- Summary --------------------------------------------------------------


def _years_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


def vehicle_summary(
    session: Session,
    vehicle_id: int,
    today: date,
    allocation: Allocation = Allocation.SPREAD,
) -> VehicleSummary:
    """
    Summary of one vehicle as of ``today``.

    "Last 12 months" is the window from one year before ``today`` (exclusive)
    to ``today``. "This month" and "this year" are the full calendar periods,
    so spread costs of the whole period count.

    Raises
    ------
    glovebox.services.records.NotFoundError
        If the vehicle does not exist.
    """
    from glovebox.services.records import NotFoundError  # circular import

    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} does not exist")
    allocation = Allocation(allocation)
    base = StatsFilter(vehicles=(vehicle_id,))

    refuels = list(session.scalars(select(Refuel).where(Refuel.vehicle_id == vehicle_id)))
    segs = segments(refuels)
    window_start = _years_before(today) + timedelta(days=1)
    recent = [s for s in segs if window_start <= s.end_date <= today]
    last_valid = [s for s in segs if s.valid]

    month_flt = replace(
        base,
        date_from=today.replace(day=1),
        date_to=today.replace(day=calendar.monthrange(today.year, today.month)[1]),
    )
    year_flt = replace(base, date_from=date(today.year, 1, 1), date_to=date(today.year, 12, 31))
    window_flt = replace(base, date_from=window_start, date_to=today)

    return VehicleSummary(
        vehicle_id=vehicle_id,
        name=vehicle.name,
        allocation=allocation,
        last_odometer_km=_last_odometer(session, vehicle_id, refuels),
        last_refuel=_last_refuel(session, refuels),
        last_consumption=last_valid[-1].consumption if last_valid else None,
        avg_consumption_12m=avg_consumption(recent),
        cost_this_month_cents=cost_breakdown(session, month_flt, allocation).total_cents,
        cost_this_year_cents=cost_breakdown(session, year_flt, allocation).total_cents,
        cost_per_km_12m=cost_per_km(session, window_flt, allocation).per_km,
    )


def _last_odometer(
    session: Session, vehicle_id: int, refuels: Sequence[Refuel]
) -> float | None:
    readings = [r.odometer_km for r in refuels]
    expense_odos = session.scalars(
        select(Expense.odometer_km).where(
            Expense.vehicle_id == vehicle_id,
            Expense.odometer_km.is_not(None),
            Expense.odometer_estimated.is_(False),
        )
    )
    readings.extend(expense_odos)
    return max(readings) if readings else None


def _last_refuel(session: Session, refuels: Sequence[Refuel]) -> LastRefuel | None:
    if not refuels:
        return None
    last = max(refuels, key=lambda r: (r.date, r.time or _MIDNIGHT, r.odometer_km, r.id))
    station = session.get(Station, last.station_id) if last.station_id else None
    return LastRefuel(
        date=last.date,
        litres_milli=last.litres_milli,
        price_per_litre_milli=last.price_per_litre_milli,
        total_cents=last.total_cents,
        station_name=station.name if station else None,
    )
