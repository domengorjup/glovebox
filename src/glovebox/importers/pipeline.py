"""
Import pipeline (D6): read, apply a preset, map vehicles, dedupe, preview,
commit, undo. The web UI calls only this module.

Every import goes through ``engine.apply`` with a ``Preset``. A ZIP may also
hold ``vehicles.csv`` and ``stations.csv``: missing vehicles and stations are
created with their details and existing ones only get empty fields filled. A
full backup is that case plus ``datapackage.json``, restored with the standard
preset.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from glovebox.importers import engine
from glovebox.importers.base import (
    Answers,
    CanonicalExpense,
    CanonicalRefuel,
    ImportResult,
    Question,
    RowError,
    parse_flag,
)
from glovebox.importers.engine import SourceTable, find_column
from glovebox.importers.presets import STANDARD_ID, Preset, list_presets
from glovebox.models import (
    Expense,
    ExpenseCategory,
    ImportBatch,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.services.records import (
    DerivedFigures,
    NotFoundError,
    ValidationError,
    derive_price_figures,
)

CHOOSE_VEHICLE_MESSAGE = "Choose a target vehicle for this file."
NEW_VEHICLE_NAME_MESSAGE = "Enter a name for the new vehicle."
NOTHING_NEW_MESSAGE = "Nothing new to import: every row is already present."
CUSTOM_FORMAT = "custom"  # batch format of a preset that was never saved
DETECT_THRESHOLD = 0.5
# A Fuelio backup or a Drivvo export holds several sections and scores 1.0 for
# each of its section presets; among tied shipped presets these (the fill-ups)
# win. Tied user presets always win.
PREFERRED_ON_TIE = ("fuelio-fillups", "drivvo-refuelling")
_BACKUP_TABLES = ("records", "vehicles", "stations")


@dataclass(frozen=True)
class CompanionChange:
    """
    A vehicle or station from ``vehicles.csv`` / ``stations.csv`` that the
    import creates or fills.

    ``fields`` lists the details set: all given ones for ``create``, only the
    empty ones of the existing item for ``fill``.
    """

    kind: str  # "vehicle" or "station"
    action: str  # "create" or "fill"
    name: str
    location: str | None
    fields: tuple[str, ...]


@dataclass
class ImportPreview:
    """
    What would happen on commit; ``preview_import`` writes nothing.

    ``duplicate_*`` are counted against existing rows (D6 keys). A preview
    with ``errors`` or ``questions`` cannot be committed. ``row_errors`` are
    the rows that are skipped for a fault; the rest stays committable.
    """

    format: str  # id of the preset used
    vehicle_names: list[str]
    new_refuels: int
    new_expenses: int
    duplicate_refuels: int
    duplicate_expenses: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    row_errors: list[RowError] = field(default_factory=list)
    skipped: int = 0  # rows dropped by the preset's skip rules
    preset_note: str = ""
    is_backup: bool = False
    companion_changes: list[CompanionChange] = field(default_factory=list)
    needs_vehicle_choice: bool = False  # question for the user, not a file fault

    @property
    def nothing_new(self) -> bool:
        """True if a commit would create no record, vehicle or station."""
        return not (self.new_refuels or self.new_expenses or self.companion_changes)


@dataclass(frozen=True)
class VehicleMapping:
    """
    File vehicle name -> existing vehicle id, or ``None`` to create it.

    A name that is absent from ``by_name`` is matched to the active vehicle of
    the same name, else created. A name mapped to ``None`` is always created
    (the preview reports an error if an active vehicle already has that name).
    ``default_vehicle_id`` serves files without vehicle names; instead,
    ``default_new_name`` (``None`` = not chosen) creates a vehicle of that name
    for them in the commit transaction. The name is required (stripped) and must
    not belong to an active vehicle.
    """

    by_name: dict[str, int | None] = field(default_factory=dict)
    default_vehicle_id: int | None = None
    default_new_name: str | None = None


@dataclass(frozen=True)
class _StationRow:
    name: str
    location: str | None
    brand: str | None


@dataclass
class _Plan:
    """Parsed, mapped and de-duplicated import, ready to preview or commit."""

    format: str
    preview: ImportPreview
    refuels: list[tuple[CanonicalRefuel, DerivedFigures, int | str]] = field(
        default_factory=list
    )
    expenses: list[tuple[CanonicalExpense, int | str]] = field(default_factory=list)
    vehicle_ids: dict[str, int | None] = field(default_factory=dict)
    new_default: str | None = None  # name of the vehicle created for unnamed records
    vehicle_details: dict[str, dict] = field(default_factory=dict)  # vehicles.csv
    stations: list[_StationRow] = field(default_factory=list)  # stations.csv
    vehicle_fills: dict[int, dict] = field(default_factory=dict)  # id -> empty fields to set
    station_fills: dict[tuple[str, str | None], str] = field(default_factory=dict)  # -> brand

    @property
    def blocked(self) -> bool:
        """True if the preview has errors or unanswered questions."""
        return bool(self.preview.errors or self.preview.questions)


def detect_preset(
    session: Session, data: bytes, section: str | None = None
) -> Preset | None:
    """
    The best-matching preset for an upload (user presets first, then shipped),
    or ``None`` if none finds at least half of its columns. On a tie the first
    user preset wins, and among shipped presets one of ``PREFERRED_ON_TIE``. A full
    backup gets the standard preset. When this returns ``None``, start the mapping from
    ``engine.fallback_preset(engine.read_file(data))``.

    With ``section`` only presets that read that section of the file are
    considered (the "next section" step of a multi-section file).
    """
    presets = list_presets(session)
    if all(p.id != STANDARD_ID for p in presets):
        presets.append(engine.standard_preset())
    if engine.read_file(data).is_backup:
        return next(p for p in presets if p.id == STANDARD_ID)
    if section is not None:
        wanted = section.casefold()
        presets = [p for p in presets if (p.file.section or "").casefold() == wanted]
    best: Preset | None = None
    best_score = 0.0
    for preset in presets:
        value = engine.score(preset, engine.read_file(data, preset))
        if value < DETECT_THRESHOLD:
            continue
        tie_win = (
            best is not None
            and value == best_score
            and best.shipped
            and preset.id in PREFERRED_ON_TIE
        )
        if best is None or value > best_score or tie_win:
            best, best_score = preset, value
    return best


def preview_import(
    session: Session,
    data: bytes,
    preset: Preset | None = None,
    *,
    mapping: VehicleMapping | None = None,
    answers: Answers | None = None,
) -> ImportPreview:
    """
    Read the file with ``preset`` and count what would be imported, writing
    nothing. ``answers`` carries the user's choices (date order, units,
    encoding, delimiter, header row).

    A file vehicle name that is absent from the mapping is matched to the
    active vehicle of the same name, or else counted as a vehicle to create.
    Records of a file without vehicle names need ``mapping.default_vehicle_id``;
    without it the preview carries an error and ``needs_vehicle_choice`` is
    set, so a UI can ask for the vehicle instead of reporting a failed file.
    A full backup ZIP is restored with the standard preset whatever ``preset``
    says; only a backup may be previewed without a preset.
    """
    return _plan(session, data, preset, answers, mapping).preview


def commit_import(
    session: Session,
    data: bytes,
    filename: str,
    mapping: VehicleMapping,
    preset: Preset | None = None,
    *,
    answers: Answers | None = None,
) -> ImportBatch:
    """
    Write all new records in one transaction under a new ``ImportBatch``;
    duplicates are skipped and counted. The batch records the preset id as its
    ``format`` (``custom`` for a preset that was never saved).

    Raises
    ------
    ValidationError
        If the preview has errors or unanswered questions, or if nothing
        would be created (no batch is written then).
    """
    plan = _plan(session, data, preset, answers, mapping)
    if plan.blocked:
        raise ValidationError(plan.preview.errors or ["Unanswered import questions"])
    if plan.preview.nothing_new:
        raise ValidationError([NOTHING_NEW_MESSAGE])
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
    preset: Preset | None,
    answers: Answers | None,
    mapping: VehicleMapping | None,
) -> _Plan:
    mapping = mapping or VehicleMapping()
    source = engine.read_file(data, preset, answers)
    if source.is_backup:  # a full backup is always read with the standard preset
        preset = engine.standard_preset()
        source = engine.read_file(data, preset, answers)
    if preset is None:
        preview = ImportPreview(CUSTOM_FORMAT, [], 0, 0, 0, 0)
        preview.errors.append("Choose a preset for this file.")
        return _Plan(CUSTOM_FORMAT, preview)
    preview = ImportPreview(
        preset.id or CUSTOM_FORMAT, [], 0, 0, 0, 0, is_backup=source.is_backup
    )
    preview.preset_note = preset.note
    plan = _Plan(preview.format, preview)
    has_companions = source.vehicles is not None or source.stations is not None
    if source.is_backup and not source.tables:
        preview.errors.append("The backup has no records.csv.")
        return plan
    if source.tables or not has_companions:
        result = engine.apply(preset, source, answers)
    else:  # only vehicles.csv and/or stations.csv
        result = ImportResult()
    _collect(plan, result)
    names = _read_vehicles(source.vehicles, plan)
    _read_stations(source.stations, plan)
    preview.vehicle_names = [*names, *(n for n in _vehicle_names(result) if n not in names)]
    if not plan.blocked:
        _map_and_dedupe(session, result, mapping, plan)
        _plan_companions(session, plan)
    return plan


def _collect(plan: _Plan, result: ImportResult) -> None:
    preview = plan.preview
    preview.warnings.extend(result.warnings)
    preview.errors.extend(result.errors)
    preview.questions.extend(result.questions)
    preview.row_errors.extend(result.row_errors)
    preview.skipped += result.skipped


def _read_vehicles(table: SourceTable | None, plan: _Plan) -> list[str]:
    """Read ``vehicles.csv`` into ``plan.vehicle_details``; return the names."""
    if table is None:
        return []
    column = {
        name: find_column([name], table.headers)
        for name in (
            "name", "make", "model", "plate", "fuel_type",
            "initial_odometer_km", "archived", "notes", "vin", "model_year",
            "engine", "tyre_size", "insurance_policy", "insurance_valid_until",
            "registration_valid_until",
        )
    }  # fmt: skip
    if column["name"] is None:
        plan.preview.errors.append("vehicles.csv has no 'name' column.")
        return []
    names = []
    for line, row in table.rows:
        name = _cell(row, column["name"])
        if not name:
            continue
        details: dict = {
            attribute: value
            for attribute in (
                "make", "model", "plate", "fuel_type", "notes", "vin", "engine",
                "tyre_size", "insurance_policy",
            )
            if (value := _cell(row, column[attribute]))
        }
        _read_vehicle_numbers_and_dates(row, column, line, details, plan)
        odometer = _cell(row, column["initial_odometer_km"])
        if odometer:
            try:
                details["initial_odometer"] = float(odometer)
            except ValueError:
                plan.preview.row_errors.append(
                    RowError(
                        line, "initial_odometer_km", odometer,
                        "vehicles.csv: not a number; the vehicle is imported without it.",
                    )
                )  # fmt: skip
        details["archived"] = parse_flag(_cell(row, column["archived"]))
        plan.vehicle_details.setdefault(name, details)
        if name not in names:
            names.append(name)
    return names


def _read_vehicle_numbers_and_dates(
    row: list[str], column: dict, line: int, details: dict, plan: _Plan
) -> None:
    """Add the model year and the two dates of a ``vehicles.csv`` row, if valid."""
    parsers = {
        "model_year": int,
        "insurance_valid_until": date.fromisoformat,
        "registration_valid_until": date.fromisoformat,
    }
    for attribute, parse in parsers.items():
        text = _cell(row, column[attribute])
        if not text:
            continue
        try:
            details[attribute] = parse(text)
        except ValueError:
            plan.preview.row_errors.append(
                RowError(
                    line, attribute, text,
                    "vehicles.csv: not a valid value; the vehicle is imported without it.",
                )
            )  # fmt: skip


def _read_stations(table: SourceTable | None, plan: _Plan) -> None:
    """Read ``stations.csv`` into ``plan.stations``."""
    if table is None:
        return
    column = {n: find_column([n], table.headers) for n in ("name", "location", "brand")}
    if column["name"] is None:
        plan.preview.errors.append("stations.csv has no 'name' column.")
        return
    for _, row in table.rows:
        name = _cell(row, column["name"])
        if name:
            plan.stations.append(
                _StationRow(
                    name,
                    _cell(row, column["location"]) or None,
                    _cell(row, column["brand"]) or None,
                )
            )


_VEHICLE_DETAILS = (
    "make", "model", "plate", "fuel_type", "initial_odometer", "notes", "vin",
    "model_year", "engine", "tyre_size", "insurance_policy",
    "insurance_valid_until", "registration_valid_until",
)  # fmt: skip


def _plan_companions(session: Session, plan: _Plan) -> None:
    """
    List what ``vehicles.csv`` and ``stations.csv`` create or fill, and keep
    the empty fields to set on existing rows. Nothing existing is overwritten.
    """
    changes = plan.preview.companion_changes
    for name, details in plan.vehicle_details.items():
        vehicle_id = plan.vehicle_ids.get(name)
        if vehicle_id is None:
            given = tuple(_label(k) for k in _VEHICLE_DETAILS if details.get(k) is not None)
            changes.append(CompanionChange("vehicle", "create", name, None, given))
            continue
        vehicle = session.get(Vehicle, vehicle_id)
        empty = {
            k: details[k]
            for k in _VEHICLE_DETAILS
            if details.get(k) not in (None, "") and getattr(vehicle, k) in (None, "")
        }
        if empty:
            plan.vehicle_fills[vehicle_id] = empty
            changes.append(
                CompanionChange("vehicle", "fill", name, None, tuple(_label(k) for k in empty))
            )
    seen: set[tuple[str, str | None]] = set()
    for station in plan.stations:
        key = (station.name, station.location)
        if key in seen:
            continue
        seen.add(key)
        existing = session.scalar(
            select(Station).where(
                Station.name == station.name,
                Station.location.is_(None)
                if station.location is None
                else Station.location == station.location,
            )
        )
        if existing is None:
            given = ("brand",) if station.brand else ()
            changes.append(CompanionChange("station", "create", *key, given))
        elif station.brand and not existing.brand:
            plan.station_fills[key] = station.brand
            changes.append(CompanionChange("station", "fill", *key, ("brand",)))


def _label(attribute: str) -> str:
    return "initial_odometer_km" if attribute == "initial_odometer" else attribute


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


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
        archived = bool(plan.vehicle_details.get(name, {}).get("archived"))
        plan.vehicle_ids[name] = _resolve_vehicle(session, name, mapping, archived)
        if name in mapping.by_name and mapping.by_name[name] is None:
            if _active_vehicle_id(session, name) is not None:
                preview.errors.append(
                    f'A vehicle named "{name}" already exists; '
                    "choose it instead of creating a new one."
                )
    needs_default = any(
        r.vehicle_name is None for r in [*result.refuels, *result.expenses]
    )
    if needs_default and mapping.default_vehicle_id is None:
        if not _plan_new_default(session, mapping, plan):
            return
    refuel_keys: set[tuple] = set()
    expense_matched: Counter[tuple] = Counter()
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
    # Expenses are matched one to one: a file may hold several equal rows (e.g.
    # two service items of the same price on one day), and each of them is a
    # duplicate only if the database already holds as many rows with that key.
    for expense in result.expenses:
        target = _target(expense.vehicle_name, plan, mapping)
        key = (target, expense.date, expense.category, expense.amount_cents)
        if expense_matched[key] < known.expenses(target)[key]:
            expense_matched[key] += 1
            preview.duplicate_expenses += 1
            continue
        plan.expenses.append((expense, target))
    # Odometers are never invented on import; only point out the gaps.
    without = sum(1 for expense, _ in plan.expenses if expense.odometer_km is None)
    if without:
        noun = "expense has" if without == 1 else "expenses have"
        preview.warnings.append(f"{without} {noun} no odometer.")
    preview.new_refuels = len(plan.refuels)
    preview.new_expenses = len(plan.expenses)


def _plan_new_default(session: Session, mapping: VehicleMapping, plan: _Plan) -> bool:
    """
    Plan the vehicle for unnamed records from ``mapping.default_new_name``.
    Returns False (with an error in the preview) if there is none or it is
    invalid.
    """
    preview = plan.preview
    preview.needs_vehicle_choice = True
    if mapping.default_new_name is None:
        preview.errors.append(CHOOSE_VEHICLE_MESSAGE)
        return False
    name = mapping.default_new_name.strip()
    if not name:
        preview.errors.append(NEW_VEHICLE_NAME_MESSAGE)
        return False
    if _active_vehicle_id(session, name) is not None:
        preview.errors.append(
            f'A vehicle named "{name}" already exists; '
            "choose it instead of creating a new one."
        )
        return False
    plan.new_default = name
    plan.vehicle_ids.setdefault(name, None)
    return True


def _hundredths(figures: DerivedFigures) -> int:
    """Litres rounded to 0.01 L (half up), as an integer."""
    return (figures.litres_milli + 5) // 10


def _resolve_vehicle(
    session: Session, name: str, mapping: VehicleMapping, archived_ok: bool = False
) -> int | None:
    """
    Mapped id (``None`` = create), else the active vehicle with that name.
    ``archived_ok`` (a backup restoring an archived vehicle) also accepts an
    archived vehicle of that name, so a second restore creates nothing.
    """
    if name in mapping.by_name:
        return mapping.by_name[name]
    found = _active_vehicle_id(session, name)
    if found is None and archived_ok:
        found = session.scalar(select(Vehicle.id).where(Vehicle.name == name))
    return found


def _active_vehicle_id(session: Session, name: str) -> int | None:
    return session.scalar(
        select(Vehicle.id).where(Vehicle.name == name, Vehicle.archived.is_(False))
    )


def _target(name: str | None, plan: _Plan, mapping: VehicleMapping) -> int | str:
    """Existing vehicle id, or the file's vehicle name if it will be created."""
    if name is None:
        if plan.new_default is not None:
            return plan.new_default
        return mapping.default_vehicle_id  # type: ignore[return-value]
    vehicle_id = plan.vehicle_ids[name]
    return name if vehicle_id is None else vehicle_id


class _ExistingKeys:
    """Duplicate keys of rows already in the database, loaded per vehicle."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._refuels: dict[int, set[tuple]] = {}
        self._expenses: dict[int, Counter[tuple]] = {}

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

    def expenses(self, target: int | str) -> Counter[tuple]:
        """Number of existing expenses per duplicate key."""
        if isinstance(target, str):
            return Counter()
        if target not in self._expenses:
            rows = self._session.execute(
                select(
                    Expense.date, Expense.category, Expense.amount_cents
                ).where(Expense.vehicle_id == target)
            )
            self._expenses[target] = Counter((target, d, c, a) for d, c, a in rows)
        return self._expenses[target]


# --- Writing ---------------------------------------------------------------


def _write(session: Session, plan: _Plan, filename: str) -> ImportBatch:
    batch = ImportBatch(
        format=plan.format[:50],
        filename=filename[:255],
        refuels_imported=len(plan.refuels),
        expenses_imported=len(plan.expenses),
        duplicates_skipped=plan.preview.duplicate_refuels
        + plan.preview.duplicate_expenses,
    )
    session.add(batch)
    session.flush()
    created = _create_vehicles(session, plan)
    for vehicle_id, values in plan.vehicle_fills.items():
        vehicle = session.get(Vehicle, vehicle_id)
        for attribute, value in values.items():
            setattr(vehicle, attribute, value)
    stations: dict[tuple[str, str | None], int] = {}
    for station in plan.stations:
        station_id = _get_or_create_station(
            session, station.name, station.brand, station.location, batch.id, stations
        )
        if brand := plan.station_fills.get((station.name, station.location)):
            session.get(Station, station_id).brand = brand
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
    for name, vehicle_id in plan.vehicle_ids.items():
        if vehicle_id is not None:
            continue
        vehicle = Vehicle(name=name, **plan.vehicle_details.get(name, {}))
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
        record.station_location,
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
        derived_field=figures.derived_field or record.derived,
        station_id=station_id,
        is_full=record.is_full,
        missed_previous=record.missed_previous,
        notes=record.notes,
        source=(record.source or batch.format)[:50],
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
        odometer_estimated=record.odometer_estimated,
        category=ExpenseCategory(record.category),
        title=record.title[:200],
        amount_cents=record.amount_cents,
        coverage_start=record.coverage_start,
        coverage_end=record.coverage_end,
        notes=record.notes,
        source=(record.source or batch.format)[:50],
        source_ref=_short(record.source_ref),
        import_batch_id=batch.id,
    )


__all__ = [
    "CompanionChange",
    "ImportPreview",
    "VehicleMapping",
    "commit_import",
    "detect_preset",
    "list_batches",
    "preview_import",
    "undo_batch",
]
