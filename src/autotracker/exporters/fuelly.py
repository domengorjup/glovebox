"""Fuelly-compatible export (D8)."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotracker.models import Refuel, Station, Vehicle

HEADER = [
    "fuelup_date", "odometer", "litres", "price",
    "partial_fuelup", "missed_fuelup", "notes", "tags",
]  # fmt: skip


@dataclass(frozen=True)
class ExportFile:
    """A downloadable file."""

    filename: str
    media_type: str
    content: bytes


def export_fuelly(
    session: Session, vehicle_ids: Sequence[int] | None = None
) -> ExportFile:
    """
    Build the Fuelly-compatible export.

    One CSV per vehicle with header
    ``fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags``;
    zipped when there is more than one vehicle. Expenses are omitted. ``price``
    is the price per litre and the station name goes into ``tags``.

    Parameters
    ----------
    session : Session
        Open database session.
    vehicle_ids : Sequence[int] | None, optional
        Vehicles to export; ``None`` exports all.

    Returns
    -------
    ExportFile
        A CSV (one vehicle) or a ZIP (several vehicles).
    """
    query = select(Vehicle).order_by(Vehicle.id)
    if vehicle_ids is not None:
        query = query.where(Vehicle.id.in_(vehicle_ids))
    vehicles = session.scalars(query).all()
    files = {_csv_name(v): _vehicle_csv(session, v) for v in vehicles}
    if len(files) == 1:
        (filename, content), = files.items()
        return ExportFile(filename, "text/csv", content)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return ExportFile("fuelly_export.zip", "application/zip", buffer.getvalue())


def _csv_name(vehicle: Vehicle) -> str:
    """Return a file-system safe, unique CSV name for the vehicle."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", vehicle.name).strip("_") or "vehicle"
    return f"fuelly_{vehicle.id}_{slug}.csv"


def _vehicle_csv(session: Session, vehicle: Vehicle) -> bytes:
    """Return the UTF-8 CSV of one vehicle's refuels, oldest first."""
    rows = session.execute(
        select(Refuel, Station.name)
        .outerjoin(Station, Refuel.station_id == Station.id)
        .where(Refuel.vehicle_id == vehicle.id)
        .order_by(Refuel.date, Refuel.odometer_km, Refuel.id)
    ).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(_row(refuel, station) for refuel, station in rows)
    return buffer.getvalue().encode("utf-8")


def _row(refuel: Refuel, station_name: str | None) -> list[str]:
    """Format one refuel as a Fuelly row."""
    odometer = refuel.odometer_km
    return [
        refuel.date.isoformat(),
        str(int(odometer)) if float(odometer).is_integer() else str(odometer),
        f"{refuel.litres_milli / 1000:.3f}",
        f"{refuel.price_per_litre_milli / 1000:.3f}",
        "0" if refuel.is_full else "1",
        "1" if refuel.missed_previous else "0",
        refuel.notes or "",
        station_name or "",
    ]
