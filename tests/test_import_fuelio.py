"""Fuelio adapter tests (tasks 3.3, 3.4)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, time

import pytest

from autotracker.importers.base import Ambiguity, ImportOptions
from autotracker.importers.fuelio import FuelioAdapter
from autotracker.models import ExpenseCategory

ADAPTER = FuelioAdapter()


def parse(data: bytes, **options):
    return ADAPTER.parse(data, ImportOptions(**options))


@pytest.fixture
def comma(fixtures_dir):
    return fixtures_dir / "fuelio_comma_km.csv"


class TestDetection:
    @pytest.mark.parametrize("marker", ["## Log", '"## Log"', '"## Log",'])
    def test_log_line_quoted_or_not(self, marker: str) -> None:
        assert ADAPTER.detect(f"{marker}\nData;Odo\n".encode()) > 0.5

    def test_other_text_is_not_fuelio(self) -> None:
        assert ADAPTER.detect(b"fuelup_date,odometer\n") == 0

    def test_detects_zip_by_first_member(self, fixtures_dir) -> None:
        archive = _zip({"a.csv": (fixtures_dir / "fuelio_comma_km.csv").read_bytes()})
        assert ADAPTER.detect(archive[:4096]) > 0.5


class TestLog:
    def test_comma_km_refuels(self, comma) -> None:
        result = parse(comma.read_bytes())
        assert not result.errors
        assert [v.name for v in result.vehicles] == ["Test Golf"]
        first, second, third, fourth = result.refuels
        assert first.vehicle_name == "Test Golf"
        assert (first.date, first.time) == (date(2024, 3, 1), time(8, 30))
        assert first.odometer_km == 10000
        assert first.litres_milli == 40000
        assert first.total_cents == 6000
        assert first.price_per_litre_milli == 1500
        assert first.is_full and not first.missed_previous
        assert first.station_name == "Alpha Fuel"
        assert first.notes == "first fill"
        assert first.source_ref == "u1"
        assert not second.is_full
        assert third.missed_previous

    def test_total_versus_per_litre_price(self, comma) -> None:
        fourth = parse(comma.read_bytes()).refuels[3]
        assert fourth.litres_milli == 72604
        assert fourth.total_cents == 300000
        assert fourth.price_per_litre_milli == 41320

    def test_fav_station_name_takes_precedence(self, comma) -> None:
        second = parse(comma.read_bytes()).refuels[1]
        assert second.station_name == "Beta Oil Main"

    def test_no_station_when_nothing_given(self, comma) -> None:
        assert parse(comma.read_bytes()).refuels[2].station_name is None

    def test_semicolon_miles_and_gallons_converted(self, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelio_semicolon_miles.csv").read_bytes()
        first = parse(data).refuels[0]
        assert first.odometer_km == pytest.approx(1609.344)
        assert first.litres_milli == 37854
        assert first.total_cents == 3500
        assert first.price_per_litre_milli == 925  # 3.50 per gallon

    def test_cp1252_semicolon_file(self) -> None:
        text = (
            "## Vehicle\nName;x\nŠkoda;\n## Log\n"
            "Data;Odo (km);Fuel (litres);Full;Price (optional);VolumePrice\n"
            "2024-01-01 10:00;1000;45,20;1;65,95;1,459\n"
        )
        result = parse(text.encode("cp1252"))
        refuel = result.refuels[0]
        assert result.vehicles[0].name == "Škoda"
        assert (refuel.litres_milli, refuel.total_cents) == (45200, 6595)

    def test_missing_required_header(self) -> None:
        data = b"## Log\nData;Odo (km)\n2024-01-01 10:00;1000\n"
        result = parse(data)
        assert result.errors
        assert result.header_mismatch.found == ["Data", "Odo (km)"]
        assert "Fuel (litres)" in result.header_mismatch.expected

    def test_bad_row_is_skipped_with_warning(self) -> None:
        data = (
            b"## Log\nData;Odo (km);Fuel (litres);Full\n"
            b"2024-01-01 10:00;1000;40.0;1\n2024-01-02 10:00;abc;40.0;1\n"
        )
        result = parse(data)
        assert len(result.refuels) == 1
        assert len(result.warnings) == 1

    def test_ambiguous_dates_ask(self) -> None:
        data = b"## Log\nData;Odo (km);Fuel (litres)\n03/04/2024;1000;40.0\n"
        result = parse(data)
        assert result.ambiguities == [Ambiguity.DATE_ORDER]
        assert parse(data, date_order="dmy").refuels[0].date == date(2024, 4, 3)


class TestCosts:
    def test_expenses_with_categories(self, comma) -> None:
        expenses = parse(comma.read_bytes()).expenses
        assert [e.title for e in expenses] == ["Service", "Insurance", "Parking"]
        assert [e.category for e in expenses] == [
            ExpenseCategory.MAINTENANCE,
            ExpenseCategory.INSURANCE,
            ExpenseCategory.OTHER,
        ]
        assert [e.amount_cents for e in expenses] == [12050, 40000, 500]
        assert expenses[0].odometer_km == 10800
        assert expenses[1].odometer_km is None
        assert expenses[0].notes == "Oil change; with filter"

    def test_template_income_and_zero_rows_skipped(self, comma) -> None:
        expenses = parse(comma.read_bytes()).expenses
        assert len(expenses) == 3  # fixture has 6 cost rows

    def test_template_row_is_not_imported(self) -> None:
        data = (
            b"## CostCategories\nCostTypeID;Name\n1;Service\n"
            b"## Costs\nCostTitle;Date;Odo;CostTypeID;Notes;Cost;isTemplate;isIncome\n"
            b"Tpl;2024-01-01 00:00;0;1;;10.00;1;0\n"
        )
        assert parse(data).expenses == []

    def test_decimal_comma_with_thousands(self, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelio_semicolon_miles.csv").read_bytes()
        expense = parse(data).expenses[0]
        assert expense.amount_cents == 123450
        assert expense.category == ExpenseCategory.MAINTENANCE


class TestZip:
    def test_two_vehicles(self, fixtures_dir) -> None:
        archive = _zip(
            {
                "Test Golf.csv": (fixtures_dir / "fuelio_comma_km.csv").read_bytes(),
                "Miles Car.csv": (
                    fixtures_dir / "fuelio_semicolon_miles.csv"
                ).read_bytes(),
                "readme.txt": b"ignored",
            }
        )
        result = parse(archive)
        assert sorted(v.name for v in result.vehicles) == ["Miles Car", "Test Golf"]
        assert len(result.refuels) == 6
        assert {r.vehicle_name for r in result.refuels} == {"Test Golf", "Miles Car"}

    def test_vehicle_name_falls_back_to_member_name(self) -> None:
        body = b"## Log\nData;Odo (km);Fuel (litres)\n2024-01-01 10:00;1000;40.0\n"
        result = parse(_zip({"My Car.csv": body}))
        assert result.refuels[0].vehicle_name == "My Car"

    def test_damaged_zip(self) -> None:
        assert parse(b"PK\x03\x04garbage").errors


def test_not_fuelio_reports_error() -> None:
    assert parse(b"a,b\n1,2\n").errors


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()
