"""
Record services: CRUD, validation and price derivation. FROZEN SIGNATURES;
implemented in group 2.

All functions take a SQLAlchemy ``Session`` first, flush but do not commit (the
caller, e.g. ``db.get_session``, commits). Input dataclasses carry storage
units: ``litres_milli``, ``price_per_litre_milli``, cents.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, time

from sqlalchemy.orm import Session

from autotracker.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    Refuel,
    Station,
    Vehicle,
)
from autotracker.services.stats import StatsFilter


class RecordsError(Exception):
    """Base class for service errors."""


class NotFoundError(RecordsError):
    """The requested record does not exist."""


class ValidationError(RecordsError):
    """Invalid input; ``messages`` are user-presentable."""

    def __init__(self, messages: Sequence[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = list(messages)


class ConfirmationRequired(RecordsError):
    """A destructive action needs ``confirm=True``; carries the record counts."""

    def __init__(self, refuels: int, expenses: int) -> None:
        super().__init__(f"{refuels} refuels and {expenses} expenses would be deleted")
        self.refuels = refuels
        self.expenses = expenses


@dataclass(frozen=True)
class VehicleInput:
    """Fields of a vehicle (create/update)."""

    name: str
    make: str | None = None
    model: str | None = None
    plate: str | None = None
    fuel_type: str | None = None
    initial_odometer: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class StationInput:
    """Fields of a station (create/update). Brand is manual only."""

    name: str
    brand: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class RefuelInput:
    """
    Fields of a refuel. At least two of ``litres_milli``,
    ``price_per_litre_milli`` and ``total_cents`` must be given.
    """

    vehicle_id: int
    date: date
    odometer_km: float
    litres_milli: int | None = None
    price_per_litre_milli: int | None = None
    total_cents: int | None = None
    time: time | None = None
    station_id: int | None = None
    is_full: bool = True
    missed_previous: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class DerivedFigures:
    """The three price figures after derivation."""

    litres_milli: int
    price_per_litre_milli: int
    total_cents: int
    derived_field: DerivedField | None


@dataclass(frozen=True)
class RefuelPreview:
    """Derived figures and warnings, shown before saving (never blocks)."""

    figures: DerivedFigures
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExpenseInput:
    """Fields of an expense. Coverage dates: both or neither, end >= start."""

    vehicle_id: int
    date: date
    category: ExpenseCategory
    amount_cents: int
    title: str = ""
    odometer_km: float | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    notes: str | None = None


@dataclass(frozen=True)
class RecordCounts:
    """Number of records of a vehicle."""

    refuels: int
    expenses: int


# --- Vehicles -------------------------------------------------------------


def list_vehicles(session: Session, include_archived: bool = False) -> list[Vehicle]:
    """List vehicles ordered by name; archived ones only if requested."""
    raise NotImplementedError


def get_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    """Return a vehicle or raise ``NotFoundError``."""
    raise NotImplementedError


def create_vehicle(session: Session, data: VehicleInput) -> Vehicle:
    """Create a vehicle; ``ValidationError`` if the name is empty or taken
    by a non-archived vehicle."""
    raise NotImplementedError


def update_vehicle(session: Session, vehicle_id: int, data: VehicleInput) -> Vehicle:
    """Update a vehicle with the same validation as ``create_vehicle``."""
    raise NotImplementedError


def archive_vehicle(session: Session, vehicle_id: int, archived: bool = True) -> Vehicle:
    """Archive (or restore) a vehicle; restoring re-checks name uniqueness."""
    raise NotImplementedError


def count_vehicle_records(session: Session, vehicle_id: int) -> RecordCounts:
    """Count a vehicle's refuels and expenses (for the delete confirmation)."""
    raise NotImplementedError


def delete_vehicle(session: Session, vehicle_id: int, *, confirm: bool = False) -> None:
    """Delete a vehicle and its records; raises ``ConfirmationRequired`` if it
    has records and ``confirm`` is false."""
    raise NotImplementedError


# --- Stations -------------------------------------------------------------


def list_stations(session: Session) -> list[Station]:
    """List stations ordered by name."""
    raise NotImplementedError


def get_station(session: Session, station_id: int) -> Station:
    """Return a station or raise ``NotFoundError``."""
    raise NotImplementedError


def create_station(session: Session, data: StationInput) -> Station:
    """Create a station; ``ValidationError`` on empty name or duplicate
    (name, location), including when location is NULL."""
    raise NotImplementedError


def update_station(session: Session, station_id: int, data: StationInput) -> Station:
    """Rename / relocate / set brand of one station."""
    raise NotImplementedError


def set_brand_bulk(
    session: Session, station_ids: Sequence[int], brand: str | None
) -> list[Station]:
    """Set (or clear, with ``None``) the brand of several stations at once.
    Manual only: never infers a brand."""
    raise NotImplementedError


def merge_stations(session: Session, source_id: int, target_id: int) -> Station:
    """Point all refuels of ``source_id`` at ``target_id`` and delete the source."""
    raise NotImplementedError


def delete_station(session: Session, station_id: int) -> None:
    """Delete a station; its refuels keep existing with ``station_id`` NULL."""
    raise NotImplementedError


# --- Refuels --------------------------------------------------------------


def derive_price_figures(
    litres_milli: int | None,
    price_per_litre_milli: int | None,
    total_cents: int | None,
) -> DerivedFigures:
    """
    Derive the missing one of the three figures (pure function, no session).

    Also used by the import pipeline on commit.

    Raises
    ------
    ValidationError
        If fewer than two figures are given or a litres/price is not positive.
    """
    raise NotImplementedError


def preview_refuel(
    session: Session, data: RefuelInput, exclude_id: int | None = None
) -> RefuelPreview:
    """Derive figures and collect warnings (>1 % inconsistency, odometer
    order) without saving. ``exclude_id`` skips the record being edited."""
    raise NotImplementedError


def list_refuels(session: Session, flt: StatsFilter) -> list[Refuel]:
    """Refuels matching the filter, newest first."""
    raise NotImplementedError


def get_refuel(session: Session, refuel_id: int) -> Refuel:
    """Return a refuel or raise ``NotFoundError``."""
    raise NotImplementedError


def create_refuel(session: Session, data: RefuelInput) -> Refuel:
    """Save a refuel (warnings never block); records ``derived_field``."""
    raise NotImplementedError


def update_refuel(session: Session, refuel_id: int, data: RefuelInput) -> Refuel:
    """Update a refuel, re-deriving the price figures."""
    raise NotImplementedError


def delete_refuel(session: Session, refuel_id: int) -> None:
    """Delete a refuel."""
    raise NotImplementedError


# --- Expenses -------------------------------------------------------------


def list_expenses(session: Session, flt: StatsFilter) -> list[Expense]:
    """Expenses matching the filter (vehicle, dates, category), newest first."""
    raise NotImplementedError


def get_expense(session: Session, expense_id: int) -> Expense:
    """Return an expense or raise ``NotFoundError``."""
    raise NotImplementedError


def create_expense(session: Session, data: ExpenseInput) -> Expense:
    """Create an expense; ``ValidationError`` on a bad coverage range."""
    raise NotImplementedError


def update_expense(session: Session, expense_id: int, data: ExpenseInput) -> Expense:
    """Update an expense with the same validation as ``create_expense``."""
    raise NotImplementedError


def delete_expense(session: Session, expense_id: int) -> None:
    """Delete an expense."""
    raise NotImplementedError
