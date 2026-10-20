"""
Statistics service (design D4, D5). FROZEN SIGNATURES; implemented in group 2.

Used by both the HTML pages and ``/api/v1`` so numbers cannot diverge. Every
function is read-only: nothing here writes to the database.

Units: litres are ``litres_milli`` integers, money is integer cents, consumption
is a float in L/100 km.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from autotracker.models import ExpenseCategory, Refuel


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
    (D5). ``per_km`` is in currency units per km, ``None`` if distance <= 0.
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
    raise NotImplementedError


def avg_consumption(segs: Sequence[Segment]) -> float | None:
    """
    Distance-weighted average in L/100 km over the valid segments.

    Returns ``None`` when there is no valid segment. Not the mean of
    per-segment values.
    """
    raise NotImplementedError


def cost_breakdown(
    session: Session,
    flt: StatsFilter,
    allocation: Allocation = Allocation.SPREAD,
) -> CostBreakdown:
    """Totals plus monthly and yearly series by category (D5)."""
    raise NotImplementedError


def cost_per_km(
    session: Session,
    flt: StatsFilter,
    allocation: Allocation = Allocation.SPREAD,
) -> CostPerKm:
    """Cost per km using the same allocation as ``cost_breakdown`` (D5)."""
    raise NotImplementedError


def station_stats(
    session: Session,
    flt: StatsFilter,
    group_by: GroupBy = GroupBy.STATION,
) -> list[StationStat]:
    """Litre-weighted, min and max price plus single-source consumption (D4)."""
    raise NotImplementedError


def vehicle_summary(
    session: Session,
    vehicle_id: int,
    today: date,
    allocation: Allocation = Allocation.SPREAD,
) -> VehicleSummary:
    """
    Summary of one vehicle as of ``today``.

    Raises
    ------
    autotracker.services.records.NotFoundError
        If the vehicle does not exist.
    """
    raise NotImplementedError
