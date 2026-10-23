"""
Full backup ZIP (design D7). Signature FROZEN by task group 1 (the optional
``vehicle_ids`` was added, keyword-compatible).
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from glovebox import __version__
from glovebox.config import Settings
from glovebox.exporters.csv_export import (
    csv_bytes,
    export_csv,
    unique_vehicle_names,
)
from glovebox.importers import engine
from glovebox.models import Refuel, Reminder, Station, Vehicle
from glovebox.standard import (
    REMINDER_FIELDS,
    STATION_FIELDS,
    VEHICLE_FIELDS,
    datapackage,
)


def export_backup(
    session: Session, settings: Settings, vehicle_ids: Sequence[int] | None = None
) -> bytes:
    """
    ZIP with ``records.csv`` (standard format, all fields), ``vehicles.csv``,
    ``stations.csv``, ``reminders.csv`` and ``datapackage.json`` (with the ``glovebox`` metadata).

    Parameters
    ----------
    vehicle_ids : Sequence[int] | None, optional
        Vehicles to back up; ``None`` means all. With a selection, only the
        stations used by the exported refuels are listed.
    """
    query = select(Vehicle).order_by(Vehicle.id)
    if vehicle_ids is not None:
        query = query.where(Vehicle.id.in_(vehicle_ids))
    vehicles = list(session.scalars(query))
    names = unique_vehicle_names(vehicles)

    station_query = select(Station).order_by(Station.id)
    if vehicle_ids is not None:
        used = select(Refuel.station_id).where(
            Refuel.vehicle_id.in_([v.id for v in vehicles]),
            Refuel.station_id.is_not(None),
        )
        station_query = station_query.where(Station.id.in_(used))
    stations = list(session.scalars(station_query))

    records, _ = export_csv(session, settings, engine.standard_preset(), vehicle_ids)
    vehicle_rows = [_vehicle_row(v, names[v.id]) for v in vehicles]
    station_rows = [[s.name, s.location or "", s.brand or ""] for s in stations]
    reminder_rows = _reminder_rows(session, vehicles, names)
    descriptor = datapackage(_metadata(session, settings))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("records.csv", records)
        archive.writestr(
            "vehicles.csv", csv_bytes([f.name for f in VEHICLE_FIELDS], vehicle_rows)
        )
        archive.writestr(
            "stations.csv", csv_bytes([f.name for f in STATION_FIELDS], station_rows)
        )
        archive.writestr(
            "reminders.csv",
            csv_bytes([f.name for f in REMINDER_FIELDS], reminder_rows),
        )
        archive.writestr(
            "datapackage.json", (json.dumps(descriptor, indent=2) + "\n").encode("utf-8")
        )
    return buffer.getvalue()


def _vehicle_row(v: Vehicle, name: str) -> list[str]:
    odometer = ""
    if v.initial_odometer is not None:
        odometer = f"{Decimal(repr(float(v.initial_odometer))).normalize():f}"
    values = {
        "name": name,
        "make": v.make,
        "model": v.model,
        "plate": v.plate,
        "fuel_type": v.fuel_type,
        "initial_odometer_km": odometer,
        "archived": "true" if v.archived else "false",
        "notes": v.notes,
        "vin": v.vin,
        "model_year": v.model_year,
        "engine": v.engine,
        "tyre_size": v.tyre_size,
        "insurance_policy": v.insurance_policy,
        "insurance_valid_until": _iso(v.insurance_valid_until),
        "registration_valid_until": _iso(v.registration_valid_until),
    }
    return [str(values[f.name] or "") for f in VEHICLE_FIELDS]


def _reminder_rows(
    session: Session, vehicles: Sequence[Vehicle], names: dict[int, str]
) -> list[list[str]]:
    """Rows of ``reminders.csv`` for the exported vehicles, oldest first."""
    query = (
        select(Reminder)
        .where(Reminder.vehicle_id.in_([v.id for v in vehicles]))
        .order_by(Reminder.id)
    )
    rows = []
    for r in session.scalars(query):
        values = {
            "uid": r.uid,
            "vehicle": names[r.vehicle_id],
            "title": r.title,
            "category": r.category.value,
            "due_date": _iso(r.due_date),
            "lead_days": r.lead_days,
            "status": r.status.value,
            "done_date": _iso(r.done_at.date()) if r.done_at else "",
            "vehicle_field": r.vehicle_field,
            "notes": r.notes,
        }
        rows.append([str(values[f.name] if values[f.name] is not None else "")
                     for f in REMINDER_FIELDS])
    return rows


def _iso(day: date | None) -> str:
    return day.isoformat() if day else ""


def _metadata(session: Session, settings: Settings) -> dict[str, str | None]:
    """App version, schema version, export time and currency."""
    schema_version = session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()
    return {
        "app_version": __version__,
        "schema_version": schema_version,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": settings.currency,
    }
