"""Native full export (D8)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Sequence
from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from glovebox import __version__
from glovebox.config import Settings
from glovebox.models import Expense, Refuel, Station, Vehicle

VEHICLE_COLUMNS = [
    "id", "name", "make", "model", "plate", "fuel_type",
    "initial_odometer", "archived", "notes",
]  # fmt: skip
STATION_COLUMNS = ["id", "name", "brand", "location"]
REFUEL_COLUMNS = [
    "id", "vehicle_id", "date", "time", "odometer_km", "litres",
    "price_per_litre", "total", "derived_field", "station_id", "is_full",
    "missed_previous", "notes", "source", "source_ref",
]  # fmt: skip
EXPENSE_COLUMNS = [
    "id", "vehicle_id", "date", "odometer_km", "category", "title", "amount",
    "coverage_start", "coverage_end", "notes", "source", "source_ref",
]  # fmt: skip


def export_native(
    session: Session, settings: Settings, vehicle_ids: Sequence[int] | None = None
) -> bytes:
    """
    Build the native export ZIP.

    Contains ``vehicles.csv``, ``stations.csv``, ``refuels.csv``,
    ``expenses.csv`` and ``manifest.json``, UTF-8, ISO dates, ``.`` decimals.
    Litres and price per litre have 3 decimals, money 2 decimals, so values
    round-trip exactly from the integer storage units.

    Parameters
    ----------
    session : Session
        Open database session.
    settings : Settings
        Settings of the running app (the manifest records its currency).
    vehicle_ids : Sequence[int] | None, optional
        Vehicles to export; ``None`` exports all. With a selection, only
        stations used by the exported refuels are included.

    Returns
    -------
    bytes
        The ZIP file content.
    """
    vehicle_query = select(Vehicle).order_by(Vehicle.id)
    refuel_query = select(Refuel).order_by(Refuel.id)
    expense_query = select(Expense).order_by(Expense.id)
    if vehicle_ids is not None:
        vehicle_query = vehicle_query.where(Vehicle.id.in_(vehicle_ids))
        refuel_query = refuel_query.where(Refuel.vehicle_id.in_(vehicle_ids))
        expense_query = expense_query.where(Expense.vehicle_id.in_(vehicle_ids))
    vehicles = session.scalars(vehicle_query).all()
    refuels = session.scalars(refuel_query).all()
    expenses = session.scalars(expense_query).all()

    station_query = select(Station).order_by(Station.id)
    if vehicle_ids is not None:
        used = {r.station_id for r in refuels if r.station_id is not None}
        station_query = station_query.where(Station.id.in_(used))
    stations = session.scalars(station_query).all()

    files = {
        "vehicles.csv": _csv(VEHICLE_COLUMNS, map(_vehicle_row, vehicles)),
        "stations.csv": _csv(STATION_COLUMNS, map(_station_row, stations)),
        "refuels.csv": _csv(REFUEL_COLUMNS, map(_refuel_row, refuels)),
        "expenses.csv": _csv(EXPENSE_COLUMNS, map(_expense_row, expenses)),
        "manifest.json": json.dumps(_manifest(session, settings), indent=2) + "\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()


def _manifest(session: Session, settings: Settings) -> dict[str, Any]:
    """Return export metadata: app and schema version, timestamp, currency."""
    schema_version = session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()
    return {
        "app_version": __version__,
        "schema_version": schema_version,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": settings.currency,
    }


def _csv(columns: list[str], rows: Any) -> str:
    """Serialise rows to CSV text with a header line."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([_cell(value) for value in row] for row in rows)
    return buffer.getvalue()


def _cell(value: Any) -> str:
    """Format one value; ``None`` becomes an empty cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def _vehicle_row(v: Vehicle) -> list[Any]:
    return [
        v.id, v.name, v.make, v.model, v.plate, v.fuel_type,
        v.initial_odometer, v.archived, v.notes,
    ]  # fmt: skip


def _station_row(s: Station) -> list[Any]:
    return [s.id, s.name, s.brand, s.location]


def _refuel_row(r: Refuel) -> list[Any]:
    return [
        r.id, r.vehicle_id, r.date, r.time, r.odometer_km,
        f"{r.litres_milli / 1000:.3f}",
        f"{r.price_per_litre_milli / 1000:.3f}",
        f"{r.total_cents / 100:.2f}",
        r.derived_field, r.station_id, r.is_full, r.missed_previous,
        r.notes, r.source, r.source_ref,
    ]  # fmt: skip


def _expense_row(e: Expense) -> list[Any]:
    return [
        e.id, e.vehicle_id, e.date, e.odometer_km, e.category, e.title,
        f"{e.amount_cents / 100:.2f}", e.coverage_start, e.coverage_end,
        e.notes, e.source, e.source_ref,
    ]  # fmt: skip
