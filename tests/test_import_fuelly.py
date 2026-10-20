"""Fuelly adapter tests (tasks 3.5, 3.6)."""

from __future__ import annotations

from datetime import date, time

import pytest

from glovebox.importers.base import Ambiguity, ImportOptions
from glovebox.importers.fuelly import FuellyAdapter

ADAPTER = FuellyAdapter()


def parse(fixtures_dir, name: str, **options):
    data = (fixtures_dir / name).read_bytes()
    return ADAPTER.parse(data, ImportOptions(**options))


class TestDetection:
    def test_import_format(self, fixtures_dir) -> None:
        head = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
        assert ADAPTER.detect(head) > 0.5

    def test_export_format(self, fixtures_dir) -> None:
        head = (fixtures_dir / "fuelly_export.csv").read_bytes()
        assert ADAPTER.detect(head) > 0.5

    def test_other_csv(self) -> None:
        assert ADAPTER.detect(b"Date,Odometer,Volume\n") == 0


class TestImportFormat:
    def test_partial_and_missed_flags(self, fixtures_dir) -> None:
        result = parse(fixtures_dir, "fuelly_import_metric.csv")
        first, second, third = result.refuels
        assert (first.is_full, first.missed_previous) == (False, False)
        assert (second.is_full, second.missed_previous) == (True, False)
        assert (third.is_full, third.missed_previous) == (True, True)

    def test_metric_values(self, fixtures_dir) -> None:
        result = parse(fixtures_dir, "fuelly_import_metric.csv")
        first, second, third = result.refuels
        assert first.date == date(2024, 5, 2)
        assert first.odometer_km == 98000
        assert first.litres_milli == 20500
        assert first.price_per_litre_milli == 1459
        assert first.total_cents is None  # derived by the pipeline
        assert second.notes == "highway trip"
        assert (third.date, third.time) == (date(2024, 6, 10), time(14, 30))
        assert result.vehicles == []
        assert all(r.vehicle_name is None for r in result.refuels)

    def test_tags_column_becomes_station_name(self, fixtures_dir) -> None:
        first, second, _ = parse(fixtures_dir, "fuelly_import_metric.csv").refuels
        assert first.station_name == "OMV Celje"
        assert first.station_brand is None
        assert second.station_name is None  # empty tags

    def test_gallons_converted(self, fixtures_dir) -> None:
        first = parse(fixtures_dir, "fuelly_import_gallons.csv").refuels[0]
        assert first.litres_milli == 37854
        assert first.price_per_litre_milli == 925
        assert first.odometer_km == pytest.approx(1609.344)

    def test_gallons_need_no_question(self, fixtures_dir) -> None:
        assert not parse(fixtures_dir, "fuelly_import_gallons.csv").ambiguities

    def test_explicit_km_column_with_gallons(self) -> None:
        data = b"fuelup_date,km,gallons,price\n2024-01-01,1000,10.000,3.500\n"
        refuel = ADAPTER.parse(data, ImportOptions()).refuels[0]
        assert refuel.odometer_km == 1000
        assert refuel.litres_milli == 37854

    def test_ambiguous_dates_ask_then_resolve(self, fixtures_dir) -> None:
        name = "fuelly_import_ambiguous_dates.csv"
        assert parse(fixtures_dir, name).ambiguities == [Ambiguity.DATE_ORDER]
        dmy = parse(fixtures_dir, name, date_order="dmy").refuels[0]
        mdy = parse(fixtures_dir, name, date_order="mdy").refuels[0]
        assert dmy.date == date(2024, 4, 3)
        assert mdy.date == date(2024, 3, 4)

    def test_missing_required_headers(self) -> None:
        result = ADAPTER.parse(b"fuelup_date,price\n2024-01-01,1.4\n", ImportOptions())
        assert result.errors
        assert result.header_mismatch.found == ["fuelup_date", "price"]
        assert "odometer" in result.header_mismatch.expected


class TestExportFormat:
    def test_units_are_asked(self, fixtures_dir) -> None:
        result = parse(fixtures_dir, "fuelly_export.csv")
        assert result.ambiguities == [Ambiguity.UNITS]
        assert result.refuels == []

    def test_imperial_answer_converts(self, fixtures_dir) -> None:
        result = parse(fixtures_dir, "fuelly_export.csv", units="imperial")
        first = result.refuels[0]
        assert first.litres_milli == 37854
        assert first.price_per_litre_milli == 925
        assert first.odometer_km == pytest.approx(12000 * 1.609344)
        assert first.vehicle_name == "Test Car"
        assert [v.name for v in result.vehicles] == ["Test Car"]
        assert first.notes == "first"

    def test_metric_answer_keeps_values(self, fixtures_dir) -> None:
        first = parse(fixtures_dir, "fuelly_export.csv", units="metric").refuels[0]
        assert first.litres_milli == 10000
        assert first.odometer_km == 12000

    def test_warns_that_flags_are_missing(self, fixtures_dir) -> None:
        result = parse(fixtures_dir, "fuelly_export.csv", units="metric")
        assert any("full" in w for w in result.warnings)
