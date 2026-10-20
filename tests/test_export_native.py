"""Tests for the native full export (data-export spec)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date

from sqlalchemy.orm import Session

from autotracker import __version__
from autotracker.exporters.native import export_native
from autotracker.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    Refuel,
    Station,
    Vehicle,
)


def _read(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n).decode("utf-8") for n in archive.namelist()}


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _populate(session: Session) -> tuple[Vehicle, Vehicle]:
    car, van = Vehicle(name="Car"), Vehicle(name="Van", make="Ford")
    station = Station(name="OMV Celje", brand="OMV")
    session.add_all([car, van, station])
    session.flush()
    session.add_all(
        [
            Refuel(
                vehicle_id=car.id, date=date(2026, 5, 2), odometer_km=98000,
                litres_milli=20500, price_per_litre_milli=1459, total_cents=2991,
                derived_field=DerivedField.TOTAL, station_id=station.id,
                is_full=False, notes="a, \"quoted\" note",
            ),
            Refuel(
                vehicle_id=van.id, date=date(2026, 5, 3), odometer_km=500.5,
                litres_milli=40000, price_per_litre_milli=1500, total_cents=6000,
            ),
            Expense(
                vehicle_id=car.id, date=date(2026, 1, 1),
                category=ExpenseCategory.INSURANCE, title="Policy",
                amount_cents=48000, coverage_start=date(2026, 1, 1),
                coverage_end=date(2026, 12, 31),
            ),
            Expense(
                vehicle_id=van.id, date=date(2026, 2, 1),
                category=ExpenseCategory.OTHER, title="Parking", amount_cents=250,
            ),
        ]
    )  # fmt: skip
    session.flush()
    return car, van


def test_export_contents(session: Session) -> None:
    _populate(session)
    files = _read(export_native(session))

    assert set(files) == {
        "vehicles.csv", "stations.csv", "refuels.csv", "expenses.csv",
        "manifest.json",
    }  # fmt: skip
    assert [r["name"] for r in _rows(files["vehicles.csv"])] == ["Car", "Van"]
    assert len(_rows(files["stations.csv"])) == 1
    refuels = _rows(files["refuels.csv"])
    assert len(refuels) == 2
    assert len(_rows(files["expenses.csv"])) == 2
    first = refuels[0]
    assert (first["date"], first["litres"], first["price_per_litre"]) == (
        "2026-05-02", "20.500", "1.459",
    )  # fmt: skip
    assert first["total"] == "29.91"
    assert first["is_full"] == "0"
    assert first["derived_field"] == "total"
    assert first["notes"] == 'a, "quoted" note'


def test_manifest(session: Session) -> None:
    manifest = json.loads(_read(export_native(session))["manifest.json"])
    assert manifest["app_version"] == __version__
    assert manifest["schema_version"] == "0001"
    assert manifest["currency"]
    assert manifest["exported_at"]


def test_selected_vehicle(session: Session) -> None:
    car, _ = _populate(session)
    files = _read(export_native(session, [car.id]))

    assert [r["name"] for r in _rows(files["vehicles.csv"])] == ["Car"]
    assert len(_rows(files["refuels.csv"])) == 1
    assert [r["category"] for r in _rows(files["expenses.csv"])] == ["insurance"]
    assert len(_rows(files["stations.csv"])) == 1


def test_selected_vehicle_without_station_use_omits_stations(
    session: Session,
) -> None:
    _, van = _populate(session)
    files = _read(export_native(session, [van.id]))
    assert _rows(files["stations.csv"]) == []


# TODO: round trip (export, import into empty DB, export again) belongs to the
# native importer task 3.7 and is left to integration.
