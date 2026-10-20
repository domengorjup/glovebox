"""Tests for the Fuelly-compatible export (data-export spec)."""

from __future__ import annotations

import io
import zipfile
from datetime import date

from sqlalchemy.orm import Session

from glovebox.exporters.fuelly import export_fuelly
from glovebox.models import Expense, ExpenseCategory, Refuel, Station, Vehicle

HEADER = "fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags"


def _refuel(vehicle_id: int, station_id: int | None, **kw) -> Refuel:
    values = dict(
        vehicle_id=vehicle_id, date=date(2026, 5, 2), odometer_km=98000,
        litres_milli=20500, price_per_litre_milli=1459, total_cents=2991,
        station_id=station_id,
    )  # fmt: skip
    return Refuel(**{**values, **kw})


def test_fuelly_export_row(session: Session) -> None:
    car = Vehicle(name="Car")
    station = Station(name="OMV Celje")
    session.add_all([car, station])
    session.flush()
    session.add(_refuel(car.id, station.id, is_full=False))
    session.add(
        Expense(
            vehicle_id=car.id, date=date(2026, 5, 3),
            category=ExpenseCategory.OTHER, title="Wash", amount_cents=500,
        )
    )  # fmt: skip
    session.flush()

    result = export_fuelly(session)

    assert result.media_type == "text/csv"
    lines = result.content.decode("utf-8").splitlines()
    assert lines == [HEADER, "2026-05-02,98000,20.500,1.459,1,0,,OMV Celje"]


def test_flags_and_missing_station(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(_refuel(car.id, None, missed_previous=True, odometer_km=98000.5))
    session.flush()

    lines = export_fuelly(session).content.decode().splitlines()
    assert lines[1] == "2026-05-02,98000.5,20.500,1.459,0,1,,"


def test_multiple_vehicles_are_zipped(session: Session) -> None:
    one, two = Vehicle(name="One"), Vehicle(name="Two/Car")
    session.add_all([one, two])
    session.flush()
    session.add_all([_refuel(one.id, None), _refuel(two.id, None)])
    session.flush()

    result = export_fuelly(session)
    assert result.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2 and all(n.endswith(".csv") for n in names)
        assert all("/" not in n for n in names)
        for name in names:
            assert archive.read(name).decode().startswith(HEADER)

    single = export_fuelly(session, [one.id])
    assert single.media_type == "text/csv"


def test_header_uses_spec_fuelly_columns(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(_refuel(car.id, None))
    session.flush()

    header = export_fuelly(session).content.decode().splitlines()[0]
    assert header.split(",") == [
        "fuelup_date", "odometer", "litres", "price",
        "partial_fuelup", "missed_fuelup", "notes", "tags",
    ]  # fmt: skip
