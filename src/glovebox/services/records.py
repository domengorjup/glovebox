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

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from glovebox.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.services.stats import (
    StatsFilter,
    select_expenses,
    select_refuels,
)


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
    vin: str | None = None
    model_year: int | None = None
    engine: str | None = None
    tyre_size: str | None = None
    insurance_policy: str | None = None
    insurance_valid_until: date | None = None
    registration_valid_until: date | None = None


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
    """
    Fields of an expense. ``title`` must not be blank (enforced on save).
    Coverage dates: both or neither, end >= start.
    """

    vehicle_id: int
    date: date
    category: ExpenseCategory
    amount_cents: int
    title: str = ""
    odometer_km: float | None = None
    odometer_estimated: bool = False
    coverage_start: date | None = None
    coverage_end: date | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LastOdometer:
    """A vehicle's last known reading; ``date`` is ``None`` for the initial one."""

    km: float
    date: date | None


@dataclass(frozen=True)
class RecordCounts:
    """Number of records of a vehicle."""

    refuels: int
    expenses: int


# --- Helpers --------------------------------------------------------------

INCONSISTENCY_TOLERANCE = 0.01


FIRST_MODEL_YEAR = 1886  # Benz Patent-Motorwagen


def _clean(value: str | None) -> str | None:
    """Strip whitespace; empty strings become ``None``."""
    if value is None:
        return None
    return value.strip() or None


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half up (positive operands)."""
    return (2 * numerator + denominator) // (2 * denominator)


def _get_or_raise(session: Session, model: type, record_id: int, label: str):
    record = session.get(model, record_id)
    if record is None:
        raise NotFoundError(f"{label} {record_id} does not exist")
    return record


# --- Vehicles -------------------------------------------------------------


def list_vehicles(session: Session, include_archived: bool = False) -> list[Vehicle]:
    """List vehicles ordered by name; archived ones only if requested."""
    stmt = select(Vehicle).order_by(Vehicle.name, Vehicle.id)
    if not include_archived:
        stmt = stmt.where(Vehicle.archived.is_(False))
    return list(session.scalars(stmt))


def get_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    """Return a vehicle or raise ``NotFoundError``."""
    return _get_or_raise(session, Vehicle, vehicle_id, "Vehicle")


def _check_vehicle_name(
    session: Session, name: str, exclude_id: int | None = None
) -> str:
    name = name.strip()
    if not name:
        raise ValidationError(["Vehicle name is required"])
    stmt = select(Vehicle.id).where(
        Vehicle.name == name, Vehicle.archived.is_(False)
    )
    if exclude_id is not None:
        stmt = stmt.where(Vehicle.id != exclude_id)
    if session.scalars(stmt).first() is not None:
        raise ValidationError([f"A vehicle named '{name}' already exists"])
    return name


def _check_model_year(year: int | None) -> None:
    """Reject a model year before the first cars or after next year."""
    latest = date.today().year + 1
    if year is not None and not FIRST_MODEL_YEAR <= year <= latest:
        raise ValidationError(
            [f"Model year must be between {FIRST_MODEL_YEAR} and {latest}"]
        )


def _apply_vehicle(vehicle: Vehicle, name: str, data: VehicleInput) -> None:
    vehicle.name = name
    vehicle.make = _clean(data.make)
    vehicle.model = _clean(data.model)
    vehicle.plate = _clean(data.plate)
    vehicle.fuel_type = _clean(data.fuel_type)
    vehicle.initial_odometer = data.initial_odometer
    vehicle.notes = _clean(data.notes)
    vin = _clean(data.vin)
    vehicle.vin = None if vin is None else vin.upper()
    vehicle.model_year = data.model_year
    vehicle.engine = _clean(data.engine)
    vehicle.tyre_size = _clean(data.tyre_size)
    vehicle.insurance_policy = _clean(data.insurance_policy)
    vehicle.insurance_valid_until = data.insurance_valid_until
    vehicle.registration_valid_until = data.registration_valid_until


def create_vehicle(session: Session, data: VehicleInput) -> Vehicle:
    """Create a vehicle; ``ValidationError`` if the name is empty or taken
    by a non-archived vehicle."""
    vehicle = Vehicle(archived=False)
    _check_model_year(data.model_year)
    _apply_vehicle(vehicle, _check_vehicle_name(session, data.name), data)
    session.add(vehicle)
    session.flush()
    return vehicle


def update_vehicle(session: Session, vehicle_id: int, data: VehicleInput) -> Vehicle:
    """Update a vehicle with the same validation as ``create_vehicle``."""
    vehicle = get_vehicle(session, vehicle_id)
    exclude = None if vehicle.archived else vehicle.id
    name = _check_vehicle_name(session, data.name, exclude_id=exclude)
    _check_model_year(data.model_year)
    _apply_vehicle(vehicle, name, data)
    session.flush()
    return vehicle


def archive_vehicle(session: Session, vehicle_id: int, archived: bool = True) -> Vehicle:
    """Archive (or restore) a vehicle; restoring re-checks name uniqueness."""
    vehicle = get_vehicle(session, vehicle_id)
    if not archived:
        _check_vehicle_name(session, vehicle.name, exclude_id=vehicle.id)
    vehicle.archived = archived
    session.flush()
    return vehicle


def count_vehicle_records(session: Session, vehicle_id: int) -> RecordCounts:
    """Count a vehicle's refuels and expenses (for the delete confirmation)."""
    refuels = session.scalar(
        select(func.count()).select_from(Refuel).where(Refuel.vehicle_id == vehicle_id)
    )
    expenses = session.scalar(
        select(func.count())
        .select_from(Expense)
        .where(Expense.vehicle_id == vehicle_id)
    )
    return RecordCounts(refuels=refuels or 0, expenses=expenses or 0)


def delete_vehicle(session: Session, vehicle_id: int, *, confirm: bool = False) -> None:
    """Delete a vehicle and its records; raises ``ConfirmationRequired`` if it
    has records and ``confirm`` is false."""
    vehicle = get_vehicle(session, vehicle_id)
    counts = count_vehicle_records(session, vehicle_id)
    if (counts.refuels or counts.expenses) and not confirm:
        raise ConfirmationRequired(counts.refuels, counts.expenses)
    # Explicit deletes: do not depend on SQLite foreign-key enforcement.
    session.execute(delete(Refuel).where(Refuel.vehicle_id == vehicle_id))
    session.execute(delete(Expense).where(Expense.vehicle_id == vehicle_id))
    session.delete(vehicle)
    session.flush()


# --- Stations -------------------------------------------------------------


def list_stations(session: Session) -> list[Station]:
    """List stations ordered by name."""
    return list(session.scalars(select(Station).order_by(Station.name, Station.id)))


def get_station(session: Session, station_id: int) -> Station:
    """Return a station or raise ``NotFoundError``."""
    return _get_or_raise(session, Station, station_id, "Station")


def _check_station(
    session: Session, data: StationInput, exclude_id: int | None = None
) -> tuple[str, str | None]:
    name = data.name.strip()
    if not name:
        raise ValidationError(["Station name is required"])
    location = _clean(data.location)
    # SQL "= NULL" never matches, so compare NULL locations explicitly.
    location_match = (
        Station.location.is_(None) if location is None else Station.location == location
    )
    stmt = select(Station.id).where(Station.name == name, location_match)
    if exclude_id is not None:
        stmt = stmt.where(Station.id != exclude_id)
    if session.scalars(stmt).first() is not None:
        raise ValidationError([f"Station '{name}' already exists at this location"])
    return name, location


def create_station(session: Session, data: StationInput) -> Station:
    """Create a station; ``ValidationError`` on empty name or duplicate
    (name, location), including when location is NULL."""
    name, location = _check_station(session, data)
    station = Station(name=name, brand=_clean(data.brand), location=location)
    session.add(station)
    session.flush()
    return station


def update_station(session: Session, station_id: int, data: StationInput) -> Station:
    """Rename / relocate / set brand of one station."""
    station = get_station(session, station_id)
    station.name, station.location = _check_station(
        session, data, exclude_id=station_id
    )
    station.brand = _clean(data.brand)
    session.flush()
    return station


def set_brand_bulk(
    session: Session, station_ids: Sequence[int], brand: str | None
) -> list[Station]:
    """Set (or clear, with ``None``) the brand of several stations at once.
    Manual only: never infers a brand."""
    stations = [get_station(session, station_id) for station_id in station_ids]
    for station in stations:
        station.brand = _clean(brand)
    session.flush()
    return stations


def merge_stations(session: Session, source_id: int, target_id: int) -> Station:
    """Point all refuels of ``source_id`` at ``target_id`` and delete the source."""
    if source_id == target_id:
        raise ValidationError(["Cannot merge a station into itself"])
    source = get_station(session, source_id)
    target = get_station(session, target_id)
    session.execute(
        update(Refuel).where(Refuel.station_id == source_id).values(station_id=target_id)
    )
    session.delete(source)
    session.flush()
    return target


def count_station_refuels(session: Session, station_id: int) -> int:
    """Count the refuels that use a station (for the delete confirmation)."""
    return (
        session.scalar(
            select(func.count()).select_from(Refuel).where(Refuel.station_id == station_id)
        )
        or 0
    )


def station_move_targets(session: Session, station_id: int) -> list[Station]:
    """Other stations a deleted station's refuels can move to: same brand first
    (when the brand is set), then by name."""
    station = get_station(session, station_id)
    others = [s for s in list_stations(session) if s.id != station_id]
    brand = station.brand

    def sort_key(other: Station) -> tuple[bool, str, int]:
        return (brand is None or other.brand != brand, other.name.lower(), other.id)

    return sorted(others, key=sort_key)


def delete_station(
    session: Session, station_id: int, move_to_id: int | None = None
) -> None:
    """Delete a station; its refuels move to ``move_to_id``, or get no station
    (``station_id`` NULL) when it is ``None``. Both happen in one transaction."""
    station = get_station(session, station_id)
    if move_to_id == station_id:
        raise ValidationError(["Choose a different station to move the refuels to"])
    if move_to_id is not None and session.get(Station, move_to_id) is None:
        raise ValidationError(["The station to move the refuels to does not exist"])
    session.execute(
        update(Refuel)
        .where(Refuel.station_id == station_id)
        .values(station_id=move_to_id)
    )
    session.delete(station)
    session.flush()


# --- Refuels --------------------------------------------------------------


def derive_price_figures(
    litres_milli: int | None,
    price_per_litre_milli: int | None,
    total_cents: int | None,
) -> DerivedFigures:
    """
    Derive the missing one of the three figures (pure function, no session).

    Also used by the import pipeline on commit.

    Units: litres in thousandths, price per litre in milli-units of currency,
    total in cents, so ``total_cents = litres_milli * price_milli / 10000``.
    When all three are given they are returned unchanged with
    ``derived_field=None``.

    Raises
    ------
    ValidationError
        If fewer than two figures are given or a litres/price is not positive.
    """
    given = [v for v in (litres_milli, price_per_litre_milli, total_cents) if v is not None]
    if len(given) < 2:
        raise ValidationError(
            ["Enter at least two of litres, price per litre and total price"]
        )
    errors = []
    if litres_milli is not None and litres_milli <= 0:
        errors.append("Litres must be positive")
    if price_per_litre_milli is not None and price_per_litre_milli <= 0:
        errors.append("Price per litre must be positive")
    if total_cents is not None and total_cents < 0:
        errors.append("Total price must not be negative")
    if errors:
        raise ValidationError(errors)

    if len(given) == 3:
        return DerivedFigures(litres_milli, price_per_litre_milli, total_cents, None)
    if total_cents is None:
        total = _round_div(litres_milli * price_per_litre_milli, 10_000)
        return DerivedFigures(
            litres_milli, price_per_litre_milli, total, DerivedField.TOTAL
        )
    if price_per_litre_milli is None:
        price = _round_div(total_cents * 10_000, litres_milli)
        return DerivedFigures(
            litres_milli, price, total_cents, DerivedField.PRICE_PER_LITRE
        )
    litres = _round_div(total_cents * 10_000, price_per_litre_milli)
    return DerivedFigures(litres, price_per_litre_milli, total_cents, DerivedField.LITRES)


def _inconsistency_warning(data: RefuelInput) -> list[str]:
    """Warn if all three figures were entered and disagree by more than 1 %."""
    if None in (data.litres_milli, data.price_per_litre_milli, data.total_cents):
        return []
    expected = data.litres_milli * data.price_per_litre_milli / 10_000
    if abs(data.total_cents - expected) > INCONSISTENCY_TOLERANCE * expected:
        return [
            f"Total {data.total_cents / 100:.2f} differs from litres x price "
            f"({expected / 100:.2f}) by more than 1 %"
        ]
    return []


def _odometer_warnings(
    session: Session, data: RefuelInput, exclude_id: int | None
) -> list[str]:
    stmt = select(Refuel).where(Refuel.vehicle_id == data.vehicle_id)
    if exclude_id is not None:
        stmt = stmt.where(Refuel.id != exclude_id)
    warnings = []
    for other in session.scalars(stmt):
        too_low = other.date < data.date and other.odometer_km > data.odometer_km
        too_high = other.date > data.date and other.odometer_km < data.odometer_km
        if too_low or too_high:
            warnings.append(
                f"Odometer {data.odometer_km:g} is out of order compared with the "
                f"refuel on {other.date.isoformat()} at {other.odometer_km:g} km"
            )
    return warnings


def preview_refuel(
    session: Session, data: RefuelInput, exclude_id: int | None = None
) -> RefuelPreview:
    """Derive figures and collect warnings (>1 % inconsistency, odometer
    order) without saving. ``exclude_id`` skips the record being edited."""
    figures = derive_price_figures(
        data.litres_milli, data.price_per_litre_milli, data.total_cents
    )
    warnings = _inconsistency_warning(data)
    warnings += _odometer_warnings(session, data, exclude_id)
    return RefuelPreview(figures=figures, warnings=warnings)


def list_refuels(session: Session, flt: StatsFilter) -> list[Refuel]:
    """Refuels matching the filter, newest first."""
    return list(session.scalars(select_refuels(flt)))


def get_refuel(session: Session, refuel_id: int) -> Refuel:
    """Return a refuel or raise ``NotFoundError``."""
    return _get_or_raise(session, Refuel, refuel_id, "Refuel")


def _apply_refuel(session: Session, refuel: Refuel, data: RefuelInput) -> None:
    get_vehicle(session, data.vehicle_id)
    if data.station_id is not None:
        get_station(session, data.station_id)
    if data.odometer_km < 0:
        raise ValidationError(["Odometer must not be negative"])
    figures = derive_price_figures(
        data.litres_milli, data.price_per_litre_milli, data.total_cents
    )
    refuel.vehicle_id = data.vehicle_id
    refuel.date = data.date
    refuel.time = data.time
    refuel.odometer_km = data.odometer_km
    refuel.litres_milli = figures.litres_milli
    refuel.price_per_litre_milli = figures.price_per_litre_milli
    refuel.total_cents = figures.total_cents
    refuel.derived_field = figures.derived_field
    refuel.station_id = data.station_id
    refuel.is_full = data.is_full
    refuel.missed_previous = data.missed_previous
    refuel.notes = _clean(data.notes)


def create_refuel(session: Session, data: RefuelInput) -> Refuel:
    """Save a refuel (warnings never block); records ``derived_field``."""
    refuel = Refuel(source="manual")
    _apply_refuel(session, refuel, data)
    session.add(refuel)
    session.flush()
    return refuel


def update_refuel(session: Session, refuel_id: int, data: RefuelInput) -> Refuel:
    """Update a refuel, re-deriving the price figures."""
    refuel = get_refuel(session, refuel_id)
    _apply_refuel(session, refuel, data)
    session.flush()
    return refuel


def delete_refuel(session: Session, refuel_id: int) -> None:
    """Delete a refuel."""
    session.delete(get_refuel(session, refuel_id))
    session.flush()


# --- Expenses -------------------------------------------------------------


def list_expenses(session: Session, flt: StatsFilter) -> list[Expense]:
    """Expenses matching the filter (vehicle, dates, category), newest first."""
    return list(session.scalars(select_expenses(flt)))


def get_expense(session: Session, expense_id: int) -> Expense:
    """Return an expense or raise ``NotFoundError``."""
    return _get_or_raise(session, Expense, expense_id, "Expense")


def _apply_expense(session: Session, expense: Expense, data: ExpenseInput) -> None:
    get_vehicle(session, data.vehicle_id)
    errors = []
    try:
        category = ExpenseCategory(data.category)
    except ValueError:
        allowed = ", ".join(c.value for c in ExpenseCategory)
        errors.append(f"Unknown category '{data.category}' (allowed: {allowed})")
        category = None
    if not data.title.strip():
        errors.append("Title is required")
    if data.amount_cents < 0:
        errors.append("Amount must not be negative")
    start, end = data.coverage_start, data.coverage_end
    if (start is None) != (end is None):
        errors.append("Coverage start and end must be set together")
    elif start is not None and end < start:
        errors.append("Coverage end must not be before coverage start")
    if errors:
        raise ValidationError(errors)
    expense.vehicle_id = data.vehicle_id
    expense.date = data.date
    expense.category = category
    expense.title = data.title.strip()
    expense.amount_cents = data.amount_cents
    expense.odometer_km = data.odometer_km
    expense.odometer_estimated = data.odometer_estimated and data.odometer_km is not None
    expense.coverage_start = start
    expense.coverage_end = end
    expense.notes = _clean(data.notes)


def last_known_odometer(
    session: Session,
    vehicle_id: int,
    on_date: date,
    exclude_expense_id: int | None = None,
) -> LastOdometer | None:
    """
    Highest real reading of the vehicle on or before ``on_date``.

    Refuels and expenses with an entered odometer count; estimated ones do
    not, so an estimate never feeds the next one. The vehicle's initial
    odometer is the fallback. ``None`` if there is nothing at all.
    """
    best: LastOdometer | None = None
    refuels = select(Refuel.odometer_km, Refuel.date).where(
        Refuel.vehicle_id == vehicle_id, Refuel.date <= on_date
    )
    expenses = select(Expense.odometer_km, Expense.date).where(
        Expense.vehicle_id == vehicle_id,
        Expense.date <= on_date,
        Expense.odometer_km.is_not(None),
        Expense.odometer_estimated.is_(False),
    )
    if exclude_expense_id is not None:
        expenses = expenses.where(Expense.id != exclude_expense_id)
    for km, day in [*session.execute(refuels), *session.execute(expenses)]:
        if best is None or km > best.km:
            best = LastOdometer(km, day)
    initial = get_vehicle(session, vehicle_id).initial_odometer
    if initial is not None and (best is None or initial > best.km):
        best = LastOdometer(initial, None)
    return best


def odometer_steps(
    session: Session, vehicle_ids: Sequence[int], exclude_expense_id: int | None = None
) -> dict[int, list[tuple[date | None, float]]]:
    """
    Per vehicle, the dates at which its last known odometer rises.

    The same readings as ``last_known_odometer``, reduced to the points where
    the running maximum increases (oldest first; ``None`` is the initial
    odometer). The last point on or before a date is the answer for that date,
    so a form can follow a changing date without asking the server.
    """
    steps: dict[int, list[tuple[date | None, float]]] = {}
    for vehicle_id in vehicle_ids:
        readings = list(session.execute(
            select(Refuel.date, Refuel.odometer_km).where(Refuel.vehicle_id == vehicle_id)
        ))
        expenses = select(Expense.date, Expense.odometer_km).where(
            Expense.vehicle_id == vehicle_id,
            Expense.odometer_km.is_not(None),
            Expense.odometer_estimated.is_(False),
        )
        if exclude_expense_id is not None:
            expenses = expenses.where(Expense.id != exclude_expense_id)
        readings += list(session.execute(expenses))
        initial = get_vehicle(session, vehicle_id).initial_odometer
        points: list[tuple[date | None, float]] = [] if initial is None else [(None, initial)]
        top = initial
        for day, km in sorted(readings, key=lambda r: r[0]):
            if top is None or km > top:
                points.append((day, km))
                top = km
        steps[vehicle_id] = points
    return steps


def create_expense(session: Session, data: ExpenseInput) -> Expense:
    """Create an expense; ``ValidationError`` on a bad coverage range."""
    expense = Expense(source="manual")
    _apply_expense(session, expense, data)
    session.add(expense)
    session.flush()
    return expense


def update_expense(session: Session, expense_id: int, data: ExpenseInput) -> Expense:
    """Update an expense with the same validation as ``create_expense``."""
    expense = get_expense(session, expense_id)
    _apply_expense(session, expense, data)
    session.flush()
    return expense


def delete_expense(session: Session, expense_id: int) -> None:
    """Delete an expense."""
    session.delete(get_expense(session, expense_id))
    session.flush()
