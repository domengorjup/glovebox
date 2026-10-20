"""
Native importer (design D8): reads the ZIP written by ``exporters.native``.

The ZIP holds ``vehicles.csv``, ``stations.csv``, ``refuels.csv``,
``expenses.csv`` and ``manifest.json``. Rows refer to vehicles and stations
by the ids used inside the ZIP.

The canonical records only carry a vehicle name and a station name, so this
module subclasses them to also carry the vehicle details and station
location. The pipeline reads those extras with ``getattr``.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal, InvalidOperation

from autotracker.importers.base import (
    CanonicalExpense,
    CanonicalRefuel,
    CanonicalVehicleRef,
    HeaderMismatch,
    ImportOptions,
    ImportResult,
    leading_zip_member,
    parse_flag,
    scale_to_int,
)
from autotracker.models import ExpenseCategory

_REQUIRED = {
    "vehicles.csv": ["id", "name"],
    "stations.csv": ["id", "name"],
    "refuels.csv": [
        "vehicle_id", "date", "odometer_km", "litres", "price_per_litre", "total",
    ],  # fmt: skip
    "expenses.csv": ["vehicle_id", "date", "category", "title", "amount"],
}


@dataclass(frozen=True)
class NativeVehicleRef(CanonicalVehicleRef):
    """A vehicle with the details stored in ``vehicles.csv``."""

    make: str | None = None
    model: str | None = None
    plate: str | None = None
    fuel_type: str | None = None
    initial_odometer: float | None = None
    archived: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class NativeRefuel(CanonicalRefuel):
    """A refuel that also knows its station's location."""

    station_location: str | None = None


@dataclass(frozen=True)
class NativeStation:
    """A station row of ``stations.csv``."""

    name: str
    brand: str | None = None
    location: str | None = None


@dataclass
class NativeResult(ImportResult):
    """``ImportResult`` that also lists every station of the export."""

    stations: list[NativeStation] = field(default_factory=list)


class NativeAdapter:
    """Adapter for the native export ZIP."""

    name = "native"

    def detect(self, head: bytes) -> float:
        """Return 0.95 if the ZIP starts with ``vehicles.csv`` or a manifest."""
        member = leading_zip_member(head)
        if member is not None and member[0] in ("vehicles.csv", "manifest.json"):
            return 0.95
        return 0.0

    def parse(self, data: bytes, options: ImportOptions) -> ImportResult:
        """Parse the ZIP; never raises on bad content."""
        result = NativeResult()
        try:
            tables = _read_tables(data, result)
        except zipfile.BadZipFile:
            result.errors.append("The native export must be a ZIP file.")
            return result
        if tables is None:
            return result
        try:
            self._convert(tables, result)
        except (ValueError, InvalidOperation, KeyError) as error:
            result.errors.append(f"Invalid native export: {error}")
        return result

    def _convert(
        self, tables: dict[str, list[dict[str, str]]], result: NativeResult
    ) -> None:
        vehicles = {row["id"]: row for row in tables["vehicles.csv"]}
        stations = {row["id"]: row for row in tables["stations.csv"]}
        for row in tables["vehicles.csv"]:
            result.vehicles.append(_vehicle(row))
        for row in tables["stations.csv"]:
            result.stations.append(
                NativeStation(
                    row["name"], _text(row, "brand"), _text(row, "location")
                )
            )
        for row in tables["refuels.csv"]:
            result.refuels.append(_refuel(row, vehicles, stations))
        for row in tables["expenses.csv"]:
            result.expenses.append(_expense(row, vehicles))


def _read_tables(
    data: bytes, result: ImportResult
) -> dict[str, list[dict[str, str]]] | None:
    tables = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        for name, required in _REQUIRED.items():
            if name not in names:
                result.errors.append(f"The ZIP has no {name}.")
                continue
            text = archive.read(name).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text, newline=""))
            found = list(reader.fieldnames or [])
            if not set(required) <= set(found):
                result.header_mismatch = HeaderMismatch(found, required)
                result.errors.append(f"{name} lacks required columns.")
                continue
            tables[name] = list(reader)
    return None if result.errors else tables


def _text(row: dict[str, str], key: str) -> str | None:
    return (row.get(key) or "").strip() or None


def _vehicle(row: dict[str, str]) -> NativeVehicleRef:
    odometer = _text(row, "initial_odometer")
    return NativeVehicleRef(
        name=row["name"],
        make=_text(row, "make"),
        model=_text(row, "model"),
        plate=_text(row, "plate"),
        fuel_type=_text(row, "fuel_type"),
        initial_odometer=float(odometer) if odometer else None,
        archived=parse_flag(row.get("archived") or ""),
        notes=_text(row, "notes"),
    )


def _refuel(
    row: dict[str, str],
    vehicles: dict[str, dict[str, str]],
    stations: dict[str, dict[str, str]],
) -> NativeRefuel:
    station = stations.get(row.get("station_id") or "")
    clock = _text(row, "time")
    return NativeRefuel(
        vehicle_name=vehicles[row["vehicle_id"]]["name"],
        date=date.fromisoformat(row["date"]),
        time=time.fromisoformat(clock) if clock else None,
        odometer_km=float(row["odometer_km"]),
        litres_milli=scale_to_int(Decimal(row["litres"]), 1000),
        price_per_litre_milli=scale_to_int(Decimal(row["price_per_litre"]), 1000),
        total_cents=scale_to_int(Decimal(row["total"]), 100),
        station_name=station["name"] if station else None,
        station_brand=_text(station, "brand") if station else None,
        station_location=_text(station, "location") if station else None,
        is_full=parse_flag(row.get("is_full") or "1"),
        missed_previous=parse_flag(row.get("missed_previous") or ""),
        notes=_text(row, "notes"),
        source_ref=_text(row, "source_ref"),
    )


def _expense(
    row: dict[str, str], vehicles: dict[str, dict[str, str]]
) -> CanonicalExpense:
    odometer = _text(row, "odometer_km")
    start, end = _text(row, "coverage_start"), _text(row, "coverage_end")
    return CanonicalExpense(
        vehicle_name=vehicles[row["vehicle_id"]]["name"],
        date=date.fromisoformat(row["date"]),
        category=ExpenseCategory(row["category"]),
        amount_cents=scale_to_int(Decimal(row["amount"]), 100),
        title=row["title"],
        odometer_km=float(odometer) if odometer else None,
        coverage_start=date.fromisoformat(start) if start else None,
        coverage_end=date.fromisoformat(end) if end else None,
        notes=_text(row, "notes"),
        source_ref=_text(row, "source_ref"),
    )
