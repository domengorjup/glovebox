"""
Preset-driven CSV export (design D8). Signature FROZEN by task group 1.

Columns follow the order of the preset's ``[fields]``. A field mapped by
``column`` is written under its first listed header; a constant ``type``
filters the records; other constants are not written. Values are converted to
the preset's units and written with the standard export precision.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from glovebox.config import Settings
from glovebox.importers.base import (
    KM_PER_MILE,
    LITRES_PER_UK_GALLON,
    LITRES_PER_US_GALLON,
)
from glovebox.importers.presets import (
    TARGET_FIELDS,
    FieldMapping,
    Preset,
    PresetError,
)
from glovebox.models import DerivedField, Expense, Refuel, Station, Vehicle
from glovebox.standard import BOOLEAN, EXPENSE, FALSE_VALUE, REFUEL, TRUE_VALUE

ARCHIVED_SUFFIX = " (archived)"
_LITRES_PER_UNIT = {
    "gal_us": LITRES_PER_US_GALLON,
    "gal_uk": LITRES_PER_UK_GALLON,
}
_MILE_ODOMETER_DECIMALS = 3


# The standard format names the derived figure like the column it came from.
_DERIVED_NAMES = {
    DerivedField.LITRES: "fuel_l",
    DerivedField.PRICE_PER_LITRE: "price_per_l",
    DerivedField.TOTAL: "total",
}


@dataclass(frozen=True)
class _Units:
    """Output conventions taken from the preset's ``[format]``."""

    miles: bool
    litres_per_unit: Decimal  # litres in one output volume unit
    decimal_char: str
    date_format: str | None  # None: ISO 8601


class NothingToExport(Exception):
    """No selected vehicle has any record the preset exports."""


def unique_vehicle_names(vehicles: Sequence[Vehicle]) -> dict[int, str]:
    """
    Name to write for each vehicle (design D7).

    Active vehicles keep their names. An archived vehicle whose name (ignoring
    case) is already taken by another exported vehicle gets `` (archived)``
    appended, then `` (2)``, `` (3)``, ... until it is unique.
    """
    names: dict[int, str] = {}
    taken: set[str] = set()
    for vehicle in vehicles:
        if not vehicle.archived:
            names[vehicle.id] = vehicle.name
            taken.add(vehicle.name.casefold())
    for vehicle in vehicles:
        if not vehicle.archived:
            continue
        name = vehicle.name
        if name.casefold() in taken:
            name = vehicle.name + ARCHIVED_SUFFIX
            counter = 2
            while name.casefold() in taken:
                name = f"{vehicle.name}{ARCHIVED_SUFFIX} ({counter})"
                counter += 1
        names[vehicle.id] = name
        taken.add(name.casefold())
    return names


def renamed_vehicles(
    session: Session, vehicle_ids: Sequence[int] | None = None
) -> dict[str, str]:
    """Stored name to exported name, for vehicles the export renames (for the UI note)."""
    vehicles = _vehicles(session, vehicle_ids)
    names = unique_vehicle_names(vehicles)
    return {v.name: names[v.id] for v in vehicles if names[v.id] != v.name}


def export_csv(
    session: Session,
    settings: Settings,
    preset: Preset,
    vehicle_ids: Sequence[int] | None = None,
) -> tuple[bytes, str]:
    """
    Export records through an exportable preset (``export`` set, no skip rules).

    Parameters
    ----------
    vehicle_ids : Sequence[int] | None
        Vehicles to export; ``None`` means all.

    Returns
    -------
    tuple[bytes, str]
        The content and its media type: ``text/csv``, or ``application/zip``
        when the preset splits by vehicle and more than one file results.

    Raises
    ------
    PresetError
        The preset is not exportable.
    NothingToExport
        The preset splits by vehicle and no selected vehicle has a row to write.
    """
    if not preset.export or preset.skip_rows:
        raise PresetError(
            f"{preset.name}: not exportable (needs export = true and no skip_rows)"
        )
    units = _units(preset)
    type_filter = preset.fields["type"].value if "type" in preset.fields else None
    columns = [
        (name, mapping)
        for name, mapping in preset.fields.items()
        if mapping.value is None
    ]
    header = [mapping.columns[0] for _, mapping in columns]
    delimiter = preset.file.delimiter or ","

    vehicles = _vehicles(session, vehicle_ids)
    names = unique_vehicle_names(vehicles)
    per_vehicle = {
        v.id: [
            [_cell(name, mapping, row) for name, mapping in columns]
            for row in _vehicle_rows(session, settings, v, names[v.id], units, type_filter)
        ]
        for v in vehicles
    }

    # A vehicle without exported rows gets no file of its own.
    filled = [v for v in vehicles if per_vehicle[v.id]]
    if preset.split_by_vehicle and not filled:
        raise NothingToExport("Nothing to export: the selected vehicles have no records of this kind.")

    if not preset.split_by_vehicle or len(filled) <= 1:
        rows = [row for v in vehicles for row in per_vehicle[v.id]]
        return _csv_bytes(header, rows, delimiter), "text/csv"

    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for v in filled:
            archive.writestr(
                _file_name(names[v.id], v.id, used),
                _csv_bytes(header, per_vehicle[v.id], delimiter),
            )
    return buffer.getvalue(), "application/zip"


def csv_bytes(header: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    """RFC 4180 CSV (comma, CRLF, UTF-8 without BOM); used by the backup tables."""
    return _csv_bytes(header, rows, ",")


def _csv_bytes(header: Sequence[str], rows, delimiter: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _vehicles(session: Session, vehicle_ids: Sequence[int] | None) -> list[Vehicle]:
    query = select(Vehicle).order_by(Vehicle.id)
    if vehicle_ids is not None:
        query = query.where(Vehicle.id.in_(vehicle_ids))
    return list(session.scalars(query))


def _file_name(vehicle_name: str, vehicle_id: int, used: set[str]) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", vehicle_name).strip("_") or "vehicle"
    name = f"{slug}.csv"
    if name in used:
        name = f"{slug}_{vehicle_id}.csv"
    used.add(name)
    return name


def _units(preset: Preset) -> _Units:
    fmt = preset.format
    date_format = None if fmt.date_format == "auto" else fmt.date_format
    return _Units(
        miles=fmt.distance_unit == "mi",
        litres_per_unit=_LITRES_PER_UNIT.get(fmt.volume_unit, Decimal(1)),
        decimal_char=fmt.decimal_char if fmt.decimal_char == "," else ".",
        date_format=date_format,
    )


# --- Records -----------------------------------------------------------------


def _vehicle_rows(
    session: Session,
    settings: Settings,
    vehicle: Vehicle,
    vehicle_name: str,
    units: _Units,
    type_filter: str | None,
) -> list[dict[str, object]]:
    """Standard-field values of one vehicle's records, oldest first."""
    rows: list[tuple[tuple, dict[str, object]]] = []
    if type_filter in (None, REFUEL):
        refuels = session.execute(
            select(Refuel, Station)
            .outerjoin(Station, Refuel.station_id == Station.id)
            .where(Refuel.vehicle_id == vehicle.id)
        ).all()
        for refuel, station in refuels:
            key = (refuel.date, 0, refuel.odometer_km, refuel.id)
            rows.append((key, _refuel_values(refuel, station, vehicle_name, settings, units)))
    if type_filter in (None, EXPENSE):
        expenses = session.scalars(select(Expense).where(Expense.vehicle_id == vehicle.id))
        for expense in expenses:
            key = (expense.date, 1, expense.odometer_km or 0, expense.id)
            rows.append((key, _expense_values(expense, vehicle_name, settings, units)))
    rows.sort(key=lambda item: item[0])
    return [values for _, values in rows]


def _refuel_values(
    r: Refuel, station: Station | None, vehicle_name: str, settings: Settings, u: _Units
) -> dict[str, object]:
    return {
        "type": REFUEL,
        "vehicle": vehicle_name,
        "date": _date(r.date, u),
        "time": _time(r.time),
        "odometer_km": _odometer(r.odometer_km, u),
        "fuel_l": _number(Decimal(r.litres_milli) / 1000 / u.litres_per_unit, "fuel_l", u),
        "price_per_l": _number(
            Decimal(r.price_per_litre_milli) / 1000 * u.litres_per_unit, "price_per_l", u
        ),
        "total": _number(Decimal(r.total_cents) / 100, "total", u),
        "currency": settings.currency,
        "full": r.is_full,
        "missed_previous": r.missed_previous,
        "station": station.name if station else None,
        "station_location": station.location if station else None,
        "station_brand": station.brand if station else None,
        "derived": _DERIVED_NAMES[r.derived_field] if r.derived_field else None,
        "notes": r.notes,
        "source": r.source,
        "source_ref": r.source_ref,
    }


def _expense_values(
    e: Expense, vehicle_name: str, settings: Settings, u: _Units
) -> dict[str, object]:
    return {
        "type": EXPENSE,
        "vehicle": vehicle_name,
        "date": _date(e.date, u),
        "odometer_km": _odometer(e.odometer_km, u) if e.odometer_km is not None else None,
        "total": _number(Decimal(e.amount_cents) / 100, "total", u),
        "currency": settings.currency,
        "category": e.category.value,
        "title": e.title,
        "coverage_start": _date(e.coverage_start, u) if e.coverage_start else None,
        "coverage_end": _date(e.coverage_end, u) if e.coverage_end else None,
        "notes": e.notes,
        "source": e.source,
        "source_ref": e.source_ref,
    }


# --- Formatting ----------------------------------------------------------------


def _date(value: date, units: _Units) -> str:
    if units.date_format is None:
        return value.isoformat()
    return datetime.combine(value, time()).strftime(units.date_format)


def _time(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M:%S" if value.second else "%H:%M")


def _decimal_text(value: Decimal, units: _Units) -> str:
    return f"{value:f}".replace(".", units.decimal_char)


def _number(value: Decimal, field_name: str, units: _Units) -> str:
    """Fixed decimals from the standard field's ``export_decimals``."""
    decimals = TARGET_FIELDS[field_name].export_decimals
    quantum = Decimal(1).scaleb(-decimals)
    return _decimal_text(value.quantize(quantum), units)


def _odometer(km: float, units: _Units) -> str:
    """Without trailing zeros; converted to miles when asked."""
    value = Decimal(repr(float(km)))
    if units.miles:
        value = (value / KM_PER_MILE).quantize(Decimal(1).scaleb(-_MILE_ODOMETER_DECIMALS))
    return _decimal_text(value.normalize(), units)


def _cell(name: str, mapping: FieldMapping, row: dict[str, object]) -> str:
    """One output cell: the field's value, translated by the mapping's lists."""
    value = row.get(name)
    if value is None:
        return ""
    if TARGET_FIELDS[name].type == BOOLEAN:
        word = TRUE_VALUE if value else FALSE_VALUE
        listed = mapping.true_values if value else mapping.false_values
        return listed[0] if listed else word
    sources = mapping.map.get(str(value))
    return sources[0] if sources else str(value)
