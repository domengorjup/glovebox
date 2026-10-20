"""
Import pipeline (D6): detect, parse, dedupe, preview, commit, undo.
FROZEN SIGNATURES; implemented in group 3. The web UI calls only this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from autotracker.importers.base import (
    Ambiguity,
    CanonicalExpense,
    CanonicalRefuel,
    CanonicalVehicleRef,
    HeaderMismatch,
    ImportOptions,
    ImporterAdapter,
    ImportResult,
)
from autotracker.importers.drivvo import DrivvoAdapter
from autotracker.importers.fuelio import FuelioAdapter
from autotracker.importers.fuelly import FuellyAdapter
from autotracker.importers.native import NativeAdapter
from autotracker.models import (
    Expense,
    ExpenseCategory,
    ImportBatch,
    Refuel,
    Station,
    Vehicle,
)
from autotracker.services.records import (
    DerivedFigures,
    NotFoundError,
    ValidationError,
    derive_price_figures,
)

HEAD_BYTES = 64 * 1024
_ADAPTERS: list[ImporterAdapter] = [
    DrivvoAdapter(),
    FuelioAdapter(),
    FuellyAdapter(),
    NativeAdapter(),
]
_VEHICLE_EXTRAS = (
    "make",
    "model",
    "plate",
    "fuel_type",
    "initial_odometer",
    "archived",
    "notes",
)


@dataclass
class ImportPreview:
    """
    What would happen on commit; ``preview_import`` writes nothing.

    ``duplicate_*`` are counted against existing rows (D6 keys). A preview
    with ``errors`` or ``header_mismatch`` cannot be committed.
    """

    format: str
    vehicle_names: list[str]
    new_refuels: int
    new_expenses: int
    duplicate_refuels: int
    duplicate_expenses: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)
    header_mismatch: HeaderMismatch | None = None


@dataclass(frozen=True)
class VehicleMapping:
    """File vehicle name -> existing vehicle id, or ``None`` to create it.
    ``default_vehicle_id`` serves files without vehicle names."""

    by_name: dict[str, int | None] = field(default_factory=dict)
    default_vehicle_id: int | None = None


@dataclass
class _Plan:
    """Parsed, mapped and de-duplicated import, ready to preview or commit."""

    format: str
    preview: ImportPreview
    vehicles: list[CanonicalVehicleRef] = field(default_factory=list)
    refuels: list[tuple[CanonicalRefuel, DerivedFigures, int | str]] = field(
        default_factory=list
    )
    expenses: list[tuple[CanonicalExpense, int | str]] = field(default_factory=list)
    vehicle_ids: dict[str, int | None] = field(default_factory=dict)
    stations: list = field(default_factory=list)  # native: every station row

    @property
    def blocked(self) -> bool:
        """True if the preview has errors or unanswered questions."""
        return bool(self.preview.errors or self.preview.ambiguities)


def available_formats() -> list[ImporterAdapter]:
    """Registered adapters (drivvo, fuelio, fuelly, native)."""
    return list(_ADAPTERS)


def detect_format(data: bytes) -> str | None:
    """Return the best-matching adapter name, or ``None`` if none matches."""
    head = data[:HEAD_BYTES]
    scored = [(adapter.detect(head), adapter.name) for adapter in _ADAPTERS]
    confidence, name = max(scored, key=lambda pair: pair[0])
    return name if confidence > 0 else None


def preview_import(
    session: Session,
    data: bytes,
    *,
    format: str | None = None,
    options: ImportOptions | None = None,
    mapping: VehicleMapping | None = None,
) -> ImportPreview:
    """
    Parse and count without writing. ``format`` overrides detection.

    A file vehicle name that is not mapped is matched to the active vehicle
    of the same name, or else counted as a vehicle to create. Records of a
    file without vehicle names need ``mapping.default_vehicle_id``; without
    it the preview carries an error.
    """
    return _plan(session, data, format, options, mapping).preview


def commit_import(
    session: Session,
    data: bytes,
    filename: str,
    mapping: VehicleMapping,
    *,
    format: str | None = None,
    options: ImportOptions | None = None,
) -> ImportBatch:
    """
    Write all new records in one transaction under a new ``ImportBatch``;
    duplicates are skipped and counted.

    Raises
    ------
    ValidationError
        If the preview has errors or unanswered questions.
    """
    plan = _plan(session, data, format, options, mapping)
    if plan.blocked:
        raise ValidationError(plan.preview.errors or ["Unanswered import questions"])
    try:
        batch = _write(session, plan, filename)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return batch


def list_batches(session: Session) -> list[ImportBatch]:
    """Import batches, newest first."""
    query = select(ImportBatch).order_by(
        ImportBatch.created_at.desc(), ImportBatch.id.desc()
    )
    return list(session.scalars(query))


def undo_batch(session: Session, batch_id: int) -> None:
    """
    Delete the batch's refuels, expenses and stations created only by it.

    A station created by the batch survives if a refuel outside the batch
    uses it. Vehicles created by the import are kept.
    """
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"Import batch {batch_id} not found")
    session.execute(delete(Refuel).where(Refuel.import_batch_id == batch_id))
    session.execute(delete(Expense).where(Expense.import_batch_id == batch_id))
    in_use = select(Refuel.station_id).where(Refuel.station_id.is_not(None))
    session.execute(
        delete(Station).where(
            Station.import_batch_id == batch_id, Station.id.not_in(in_use)
        )
    )
    session.execute(
        update(Station)
        .where(Station.import_batch_id == batch_id)
        .values(import_batch_id=None)
    )
    session.delete(batch)
    session.commit()


# --- Planning --------------------------------------------------------------


def _plan(
    session: Session,
    data: bytes,
    format: str | None,
    options: ImportOptions | None,
    mapping: VehicleMapping | None,
) -> _Plan:
    name = format or detect_format(data)
    adapter = next((a for a in _ADAPTERS if a.name == name), None)
    preview = ImportPreview(name or "", [], 0, 0, 0, 0)
    plan = _Plan(preview.format, preview)
    if adapter is None:
        preview.errors.append("The file format was not recognised.")
        return plan
    result = adapter.parse(data, options or ImportOptions())
    preview.warnings.extend(result.warnings)
    preview.errors.extend(result.errors)
    preview.ambiguities.extend(result.ambiguities)
    preview.header_mismatch = result.header_mismatch
    preview.vehicle_names = _vehicle_names(result)
    plan.vehicles = result.vehicles
    plan.stations = getattr(result, "stations", [])
    if not plan.blocked:
        _map_and_dedupe(session, result, mapping or VehicleMapping(), plan)
    return plan


def _vehicle_names(result: ImportResult) -> list[str]:
    names = [v.name for v in result.vehicles]
    for record in [*result.refuels, *result.expenses]:
        if record.vehicle_name and record.vehicle_name not in names:
            names.append(record.vehicle_name)
    return names


def _map_and_dedupe(
    session: Session, result: ImportResult, mapping: VehicleMapping, plan: _Plan
) -> None:
    preview = plan.preview
    for name in preview.vehicle_names:
        plan.vehicle_ids[name] = _resolve_vehicle(session, name, mapping)
    needs_default = any(
        r.vehicle_name is None for r in [*result.refuels, *result.expenses]
    )
    if needs_default and mapping.default_vehicle_id is None:
        preview.errors.append("Choose a target vehicle for this file.")
        return
    refuel_keys: set[tuple] = set()
    expense_keys: set[tuple] = set()
    known = _ExistingKeys(session)
    for refuel in result.refuels:
        target = _target(refuel.vehicle_name, plan, mapping)
        try:
            figures = derive_price_figures(
                refuel.litres_milli,
                refuel.price_per_litre_milli,
                refuel.total_cents,
            )
        except ValidationError as error:
            preview.warnings.append(
                f"Refuel on {refuel.date} skipped: {error}"
            )
            continue
        key = (target, refuel.date, round(refuel.odometer_km, 3), _hundredths(figures))
        if key in refuel_keys or key in known.refuels(target):
            preview.duplicate_refuels += 1
            continue
        refuel_keys.add(key)
        plan.refuels.append((refuel, figures, target))
    for expense in result.expenses:
        target = _target(expense.vehicle_name, plan, mapping)
        key = (target, expense.date, expense.category, expense.amount_cents)
        if key in expense_keys or key in known.expenses(target):
            preview.duplicate_expenses += 1
            continue
        expense_keys.add(key)
        plan.expenses.append((expense, target))
    preview.new_refuels = len(plan.refuels)
    preview.new_expenses = len(plan.expenses)


def _hundredths(figures: DerivedFigures) -> int:
    """Litres rounded to 0.01 L (half up), as an integer."""
    return (figures.litres_milli + 5) // 10


def _resolve_vehicle(
    session: Session, name: str, mapping: VehicleMapping
) -> int | None:
    """Mapped id, else the active vehicle with that name, else ``None``."""
    if mapping.by_name.get(name) is not None:
        return mapping.by_name[name]
    return session.scalar(
        select(Vehicle.id).where(Vehicle.name == name, Vehicle.archived.is_(False))
    )


def _target(name: str | None, plan: _Plan, mapping: VehicleMapping) -> int | str:
    """Existing vehicle id, or the file's vehicle name if it will be created."""
    if name is None:
        return mapping.default_vehicle_id  # type: ignore[return-value]
    vehicle_id = plan.vehicle_ids[name]
    return name if vehicle_id is None else vehicle_id


class _ExistingKeys:
    """Duplicate keys of rows already in the database, loaded per vehicle."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._refuels: dict[int, set[tuple]] = {}
        self._expenses: dict[int, set[tuple]] = {}

    def refuels(self, target: int | str) -> set[tuple]:
        if isinstance(target, str):
            return set()
        if target not in self._refuels:
            rows = self._session.execute(
                select(
                    Refuel.date, Refuel.odometer_km, Refuel.litres_milli
                ).where(Refuel.vehicle_id == target)
            )
            self._refuels[target] = {
                (target, d, round(odo, 3), (litres + 5) // 10)
                for d, odo, litres in rows
            }
        return self._refuels[target]

    def expenses(self, target: int | str) -> set[tuple]:
        if isinstance(target, str):
            return set()
        if target not in self._expenses:
            rows = self._session.execute(
                select(
                    Expense.date, Expense.category, Expense.amount_cents
                ).where(Expense.vehicle_id == target)
            )
            self._expenses[target] = {(target, d, c, a) for d, c, a in rows}
        return self._expenses[target]


# --- Writing ---------------------------------------------------------------


def _write(session: Session, plan: _Plan, filename: str) -> ImportBatch:
    batch = ImportBatch(
        format=plan.format,
        filename=filename[:255],
        refuels_imported=len(plan.refuels),
        expenses_imported=len(plan.expenses),
        duplicates_skipped=plan.preview.duplicate_refuels
        + plan.preview.duplicate_expenses,
    )
    session.add(batch)
    session.flush()
    created = _create_vehicles(session, plan)
    stations: dict[tuple[str, str | None], int] = {}
    for station in plan.stations:
        _get_or_create_station(
            session, station.name, station.brand, station.location, batch.id, stations
        )
    for record, figures, target in plan.refuels:
        vehicle_id = created[target] if isinstance(target, str) else target
        station_id = _station_id(session, record, batch.id, stations)
        session.add(_new_refuel(record, figures, vehicle_id, station_id, batch))
    for expense, target in plan.expenses:
        vehicle_id = created[target] if isinstance(target, str) else target
        session.add(_new_expense(expense, vehicle_id, batch))
    session.flush()
    return batch


def _create_vehicles(session: Session, plan: _Plan) -> dict[str, int]:
    """Create the vehicles the mapping left unresolved; return name -> id."""
    created = {}
    for ref in plan.vehicles:
        if plan.vehicle_ids.get(ref.name) is not None:
            continue
        vehicle = Vehicle(name=ref.name)
        for attribute in _VEHICLE_EXTRAS:
            value = getattr(ref, attribute, None)
            if value is not None:
                setattr(vehicle, attribute, value)
        session.add(vehicle)
        session.flush()
        created[ref.name] = vehicle.id
    for name, vehicle_id in plan.vehicle_ids.items():
        if vehicle_id is None and name not in created:
            vehicle = Vehicle(name=name)
            session.add(vehicle)
            session.flush()
            created[name] = vehicle.id
    return created


def _station_id(
    session: Session,
    record: CanonicalRefuel,
    batch_id: int,
    cache: dict[tuple[str, str | None], int],
) -> int | None:
    name = (record.station_name or "").strip()
    if not name:
        return None
    return _get_or_create_station(
        session,
        name,
        record.station_brand,
        getattr(record, "station_location", None),
        batch_id,
        cache,
    )


def _get_or_create_station(
    session: Session,
    name: str,
    brand: str | None,
    location: str | None,
    batch_id: int,
    cache: dict[tuple[str, str | None], int],
) -> int:
    """Reuse the station with this (name, location) or create it for the batch."""
    key = (name, location)
    if key in cache:
        return cache[key]
    same_location = (
        Station.location.is_(None) if location is None else Station.location == location
    )
    station_id = session.scalar(
        select(Station.id).where(Station.name == name, same_location)
    )
    if station_id is None:
        station = Station(
            name=name, brand=brand, location=location, import_batch_id=batch_id
        )
        session.add(station)
        session.flush()
        station_id = station.id
    cache[key] = station_id
    return station_id


def _short(text: str | None) -> str | None:
    return text[:100] if text else None


def _new_refuel(
    record: CanonicalRefuel,
    figures: DerivedFigures,
    vehicle_id: int,
    station_id: int | None,
    batch: ImportBatch,
) -> Refuel:
    return Refuel(
        vehicle_id=vehicle_id,
        date=record.date,
        time=record.time,
        odometer_km=record.odometer_km,
        litres_milli=figures.litres_milli,
        price_per_litre_milli=figures.price_per_litre_milli,
        total_cents=figures.total_cents,
        derived_field=figures.derived_field,
        station_id=station_id,
        is_full=record.is_full,
        missed_previous=record.missed_previous,
        notes=record.notes,
        source=batch.format,
        source_ref=_short(record.source_ref),
        import_batch_id=batch.id,
    )


def _new_expense(
    record: CanonicalExpense, vehicle_id: int, batch: ImportBatch
) -> Expense:
    return Expense(
        vehicle_id=vehicle_id,
        date=record.date,
        odometer_km=record.odometer_km,
        category=ExpenseCategory(record.category),
        title=record.title[:200],
        amount_cents=record.amount_cents,
        coverage_start=record.coverage_start,
        coverage_end=record.coverage_end,
        notes=record.notes,
        source=batch.format,
        source_ref=_short(record.source_ref),
        import_batch_id=batch.id,
    )


__all__ = [
    "ImportPreview",
    "VehicleMapping",
    "available_formats",
    "commit_import",
    "detect_format",
    "list_batches",
    "preview_import",
    "undo_batch",
]
