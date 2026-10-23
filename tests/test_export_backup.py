"""Tests for the full backup (data-export spec)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, time

from sqlalchemy.orm import Session

from glovebox import __version__
from glovebox.config import Settings
from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.exporters.backup import export_backup
from glovebox.importers.pipeline import VehicleMapping, commit_import
from glovebox.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.standard import RECORD_FIELDS, STATION_FIELDS, VEHICLE_FIELDS


def _read(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n).decode("utf-8") for n in archive.namelist()}


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _populate(session: Session) -> tuple[Vehicle, Vehicle]:
    car = Vehicle(name="Car", make="VW", initial_odometer=85000, notes="a, b")
    van = Vehicle(name="Van", make="Ford")
    station = Station(name="OMV Celje", brand="OMV", location="Celje")
    unused = Station(name="Shell", location="Maribor")
    session.add_all([car, van, station, unused])
    session.flush()
    session.add_all(
        [
            Refuel(
                vehicle_id=car.id, date=date(2026, 5, 2), time=time(14, 30),
                odometer_km=98000, litres_milli=20500, price_per_litre_milli=1459,
                total_cents=2991, derived_field=DerivedField.TOTAL,
                station_id=station.id, is_full=False, notes='a, "quoted" note',
                source="fuelly", source_ref="17",
            ),
            Refuel(
                vehicle_id=van.id, date=date(2026, 5, 3), odometer_km=500.5,
                litres_milli=40000, price_per_litre_milli=1500, total_cents=6000,
                missed_previous=True, derived_field=DerivedField.PRICE_PER_LITRE,
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


def test_backup_contents(session: Session) -> None:
    _populate(session)
    files = _read(export_backup(session, Settings()))

    assert set(files) == {
        "records.csv", "vehicles.csv", "stations.csv", "reminders.csv", "datapackage.json",
    }
    records = _rows(files["records.csv"])
    assert list(records[0]) == [f.name for f in RECORD_FIELDS]
    assert len(records) == 4
    assert sorted((r["type"], r["title"], r["odometer_km"]) for r in records) == [
        ("expense", "Parking", ""),
        ("expense", "Policy", ""),
        ("refuel", "", "500.5"),
        ("refuel", "", "98000"),
    ]  # every record exactly once
    refuel = next(r for r in records if r["odometer_km"] == "98000")
    assert (refuel["station"], refuel["station_location"], refuel["station_brand"]) == (
        "OMV Celje", "Celje", "OMV",
    )  # fmt: skip
    assert (refuel["derived"], refuel["source"], refuel["source_ref"]) == ("total", "fuelly", "17")
    assert refuel["full"] == "false" and refuel["notes"] == 'a, "quoted" note'
    assert refuel["time"] == "14:30"

    vehicles = _rows(files["vehicles.csv"])
    assert list(vehicles[0]) == [f.name for f in VEHICLE_FIELDS]
    assert [(v["name"], v["initial_odometer_km"], v["archived"]) for v in vehicles] == [
        ("Car", "85000", "false"), ("Van", "", "false"),
    ]  # fmt: skip
    assert vehicles[0]["notes"] == "a, b"

    stations = _rows(files["stations.csv"])
    assert list(stations[0]) == [f.name for f in STATION_FIELDS]
    assert [s["name"] for s in stations] == ["OMV Celje", "Shell"]  # unused one included


def test_backup_metadata(session: Session) -> None:
    files = _read(export_backup(session, Settings(currency="CHF")))
    descriptor = json.loads(files["datapackage.json"])
    meta = descriptor["glovebox"]
    assert meta["app_version"] == __version__
    assert meta["schema_version"] == "0007"
    assert meta["currency"] == "CHF"
    assert meta["exported_at"]
    assert [r["name"] for r in descriptor["resources"]] == [
        "records", "vehicles", "stations", "reminders",
    ]


def test_selected_vehicle(session: Session) -> None:
    car, van = _populate(session)
    files = _read(export_backup(session, Settings(), [van.id]))

    assert [r["name"] for r in _rows(files["vehicles.csv"])] == ["Van"]
    assert {r["vehicle"] for r in _rows(files["records.csv"])} == {"Van"}
    assert len(_rows(files["records.csv"])) == 2
    assert _rows(files["stations.csv"]) == []  # the van used no station

    files = _read(export_backup(session, Settings(), [car.id]))
    assert [s["name"] for s in _rows(files["stations.csv"])] == ["OMV Celje"]


def test_archived_name_suffix(session: Session) -> None:
    active, old = Vehicle(name="Golf"), Vehicle(name="Golf", archived=True)
    session.add_all([active, old])
    session.flush()
    files = _read(export_backup(session, Settings()))
    vehicles = _rows(files["vehicles.csv"])
    assert [(v["name"], v["archived"]) for v in vehicles] == [
        ("Golf", "false"), ("Golf (archived)", "true"),
    ]  # fmt: skip


def test_round_trip_through_restore(session: Session) -> None:
    """Needs the group 2 import engine (the glovebox preset and backup restore)."""
    _populate(session)
    session.commit()
    original = export_backup(session, Settings())

    engine = make_engine()
    run_migrations(engine)
    with make_session_factory(engine)() as fresh:
        commit_import(fresh, original, "backup.zip", VehicleMapping())
        fresh.commit()
        restored = export_backup(fresh, Settings())
    engine.dispose()

    before, after = _read(original), _read(restored)
    for name in ("records.csv", "vehicles.csv", "stations.csv"):
        assert after[name] == before[name], name
    meta_before = json.loads(before["datapackage.json"])["glovebox"]
    meta_after = json.loads(after["datapackage.json"])["glovebox"]
    meta_before.pop("exported_at"), meta_after.pop("exported_at")
    assert meta_after == meta_before


def test_derived_column_uses_the_standard_names(session: Session) -> None:
    car, _ = _populate(session)
    session.add(
        Refuel(
            vehicle_id=car.id, date=date(2026, 6, 1), odometer_km=99000,
            litres_milli=30000, price_per_litre_milli=1500, total_cents=4500,
            derived_field=DerivedField.LITRES,
        )
    )  # fmt: skip
    session.commit()
    rows = _rows(_read(export_backup(session, Settings()))["records.csv"])
    assert {r["derived"] for r in rows if r["type"] == "refuel"} == {
        "total", "price_per_l", "fuel_l",
    }
