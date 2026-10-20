"""Drivvo adapter tests with the PROVISIONAL English mapping (tasks 4.1, 4.2)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from glovebox.importers.base import ALIASES_DIR, ImportOptions, load_aliases
from glovebox.importers.drivvo import DrivvoAdapter
from glovebox.importers.pipeline import (
    VehicleMapping,
    commit_import,
    detect_format,
    preview_import,
)
from glovebox.models import Expense, ExpenseCategory, Refuel, Vehicle

ADAPTER = DrivvoAdapter()


def parse(fixtures_dir, name: str):
    return ADAPTER.parse((fixtures_dir / name).read_bytes(), ImportOptions())


def test_alias_file_is_marked_provisional() -> None:
    text = (ALIASES_DIR / "drivvo.toml").read_text()
    assert "PROVISIONAL" in text
    assert load_aliases("drivvo").provisional


def test_refuel_rows(fixtures_dir) -> None:
    result = parse(fixtures_dir, "drivvo_refuel_en.csv")
    first, second = result.refuels
    assert not result.errors
    assert any("provisional" in w for w in result.warnings)
    assert first.date == date(2024, 2, 1)
    assert first.odometer_km == 5000
    assert (first.litres_milli, first.price_per_litre_milli) == (40000, 1500)
    assert first.total_cents == 6000
    assert first.station_name == "Alpha Fuel"
    assert first.is_full and not first.missed_previous
    assert not second.is_full
    assert second.notes == "short stop"


def test_service_rows_become_expenses(fixtures_dir) -> None:
    oil, insurance, wipers = parse(fixtures_dir, "drivvo_service_en.csv").expenses
    assert (oil.title, oil.category) == ("Oil change", ExpenseCategory.MAINTENANCE)
    assert oil.amount_cents == 8990 and oil.odometer_km == 5200
    assert insurance.category == ExpenseCategory.INSURANCE
    # Unknown service types default to maintenance but keep their title.
    assert (wipers.title, wipers.category) == ("Wiper blades", "maintenance")


def test_expense_rows(fixtures_dir) -> None:
    parking, tax = parse(fixtures_dir, "drivvo_expense_en.csv").expenses
    assert (parking.title, parking.category) == ("Parking", ExpenseCategory.OTHER)
    assert parking.odometer_km is None
    assert tax.category == ExpenseCategory.REGISTRATION


def test_headers_are_case_and_whitespace_insensitive() -> None:
    data = b"  DATE ,odometer,VOLUME ,total  COST\n2024-01-01,100,10.0,15.0\n"
    assert len(ADAPTER.parse(data, ImportOptions()).refuels) == 1


def test_unknown_headers_are_reported(fixtures_dir) -> None:
    result = parse(fixtures_dir, "drivvo_unknown_headers.csv")
    assert result.errors and not result.refuels
    assert result.header_mismatch.found == [
        "Datum", "Kilometer", "Menge", "Gesamtpreis",
    ]  # fmt: skip
    assert any("Odometer" in line for line in result.header_mismatch.expected)


def test_detect_does_not_claim_fuelly(fixtures_dir) -> None:
    head = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
    assert ADAPTER.detect(head) == 0


@pytest.mark.parametrize(
    "name", ["drivvo_refuel_en.csv", "drivvo_service_en.csv", "drivvo_expense_en.csv"]
)
def test_detected_by_pipeline(fixtures_dir, name: str) -> None:
    assert detect_format((fixtures_dir / name).read_bytes()) == "drivvo"


def test_provisional_file_goes_through_pipeline(fixtures_dir, session) -> None:
    session.add(Vehicle(name="Golf"))
    session.commit()
    vehicle_id = session.scalar(select(Vehicle.id))
    mapping = VehicleMapping(default_vehicle_id=vehicle_id)
    data = (fixtures_dir / "drivvo_refuel_en.csv").read_bytes()

    preview = preview_import(session, data, mapping=mapping)
    assert (preview.format, preview.new_refuels) == ("drivvo", 2)

    commit_import(session, data, "drivvo_refuel_en.csv", mapping)
    again = preview_import(session, data, mapping=mapping)
    assert (again.new_refuels, again.duplicate_refuels) == (0, 2)
    refuels = session.scalars(select(Refuel).order_by(Refuel.date)).all()
    assert refuels[0].total_cents == 6000 and refuels[0].source == "drivvo"
    assert refuels[0].station_id is not None
    assert session.scalars(select(Expense)).all() == []
