"""Shipped presets: they load, are detected, and import the fixtures (tasks 3.1-3.5)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, time

import pytest

from glovebox.importers import engine
from glovebox.importers.base import Answers
from glovebox.importers.pipeline import PREFERRED_ON_TIE
from glovebox.importers.presets import Preset, shipped_presets
from glovebox.models import ExpenseCategory
from glovebox.standard import RECORD_FIELDS

IDS = {
    "glovebox", "fuelly-metric", "fuelly-us", "fuelly-website",
    "fuelio-fillups", "fuelio-costs",
    "drivvo-refuelling", "drivvo-services", "drivvo-expenses",
}  # fmt: skip
VERIFIED = {"glovebox", "drivvo-refuelling", "drivvo-services", "drivvo-expenses"}


def preset(preset_id: str) -> Preset:
    return next(p for p in shipped_presets() if p.id == preset_id)


def detect(data: bytes) -> tuple[str | None, dict[str, float]]:
    """Best shipped preset with score above 0.5 (ties as the import page breaks them)."""
    scores = {
        p.id: engine.score(p, engine.read_file(data, p)) for p in shipped_presets()
    }
    best = max(scores, key=lambda key: (scores[key], key in PREFERRED_ON_TIE))
    return (best if scores[best] > 0.5 else None), scores


def run(fixtures_dir, name: str, preset_id: str, **answers):
    data = (fixtures_dir / name).read_bytes()
    chosen = preset(preset_id)
    source = engine.read_file(data, chosen)
    return engine.apply(chosen, source, Answers(**answers))


def zip_of(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# --- Loading (no engine needed) -------------------------------------------


def test_every_shipped_preset_loads() -> None:
    presets = shipped_presets()
    assert {p.id for p in presets} == IDS
    assert all(p.shipped for p in presets)
    assert len({p.name.casefold() for p in presets}) == len(presets)


def test_standard_preset_maps_every_standard_field_in_order() -> None:
    glovebox = preset("glovebox")
    assert list(glovebox.fields) == [f.name for f in RECORD_FIELDS]
    assert all(m.columns == (name,) for name, m in glovebox.fields.items())
    assert glovebox.verified and glovebox.export
    assert (glovebox.format.decimal_char, glovebox.format.date_format) == (".", "%Y-%m-%d")
    assert (glovebox.format.distance_unit, glovebox.format.volume_unit) == ("km", "l")


def test_export_flags() -> None:
    exportable = {p.id for p in shipped_presets() if p.export}
    assert exportable == {"glovebox", "fuelly-metric"}
    assert preset("fuelly-metric").split_by_vehicle
    assert not preset("fuelly-metric").skip_rows


def test_unverified_presets_say_so() -> None:
    for p in shipped_presets():
        assert p.verified == (p.id in VERIFIED)
        assert p.note
        if not p.verified:
            assert p.note.startswith("Never tested against a real export")
    for preset_id in ("drivvo-refuelling", "drivvo-services", "drivvo-expenses"):
        assert preset(preset_id).note.startswith("Tested with Drivvo Android exports")


def test_shipped_preset_files_explain_the_export() -> None:
    from glovebox.importers.presets import SHIPPED_DIR

    for path in SHIPPED_DIR.glob("*.toml"):
        assert path.read_text(encoding="utf-8").startswith("# Export: "), path.name


def test_fuelio_presets_read_their_sections() -> None:
    assert preset("fuelio-fillups").file.section == "Log"
    costs = preset("fuelio-costs")
    assert costs.file.section == "Costs"
    assert {r.column for r in costs.skip_rows} == {"isTemplate", "isIncome", "Cost"}


def test_fuelly_metric_matches_v1_export_layout() -> None:
    fields = preset("fuelly-metric").fields
    assert list(fields) == [
        "type", "date", "odometer_km", "fuel_l", "price_per_l",
        "full", "missed_previous", "notes", "station",
    ]  # fmt: skip
    assert fields["full"].true_values == ("0",)
    assert fields["missed_previous"].true_values == ("1",)


# --- Detection and import (need the engine, group 2) ---------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("fuelly_import_metric.csv", "fuelly-metric"),
        ("fuelly_import_gallons.csv", "fuelly-us"),
        ("fuelly_import_ambiguous_dates.csv", "fuelly-metric"),
        ("fuelly_export.csv", "fuelly-website"),
        ("fuelio_semicolon_miles.csv", "fuelio-fillups"),
        ("drivvo_en_sections.csv", "drivvo-refuelling"),
    ],
)
def test_fixture_is_detected(fixtures_dir, name: str, expected: str) -> None:
    best, scores = detect((fixtures_dir / name).read_bytes())
    assert best == expected, scores


def test_fuelio_file_with_both_sections_scores_both_presets(fixtures_dir) -> None:
    # The file holds ## Log and ## Costs, so both presets score 1.0 (a tie);
    # which one is pre-selected is up to the caller. The user imports the
    # file once per preset.
    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    _, scores = detect(data)
    assert scores["fuelio-fillups"] > 0.5
    assert scores["fuelio-costs"] > 0.5


def test_unknown_headers_select_no_preset(fixtures_dir) -> None:
    data = (fixtures_dir / "drivvo_unknown_headers.csv").read_bytes()
    best, _ = detect(data)
    assert best is None
    standard = preset("glovebox")
    result = engine.apply(standard, engine.read_file(data, standard), Answers())
    assert result.errors and not result.refuels and not result.expenses


class TestFuelly:
    def test_flags_and_values(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelly_import_metric.csv", "fuelly-metric")
        assert not result.errors and not result.row_errors and not result.questions
        first, second, third = result.refuels
        assert (first.is_full, first.missed_previous) == (False, False)
        assert (second.is_full, second.missed_previous) == (True, False)
        assert (third.is_full, third.missed_previous) == (True, True)
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
        result = run(fixtures_dir, "fuelly_import_metric.csv", "fuelly-metric")
        first, second, _ = result.refuels
        assert first.station_name == "OMV Celje"
        assert first.station_brand is None
        assert second.station_name is None

    def test_gallons_converted_without_question(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelly_import_gallons.csv", "fuelly-us")
        assert not result.questions and not result.errors
        first = result.refuels[0]
        assert first.litres_milli == 37854
        assert first.price_per_litre_milli == 925
        assert first.odometer_km == pytest.approx(1609.344)

    def test_ambiguous_dates_ask_then_resolve(self, fixtures_dir) -> None:
        name = "fuelly_import_ambiguous_dates.csv"
        asked = run(fixtures_dir, name, "fuelly-metric")
        assert [q.kind.value for q in asked.questions] == ["date_order"]
        dmy = run(fixtures_dir, name, "fuelly-metric", date_order="dmy").refuels[0]
        mdy = run(fixtures_dir, name, "fuelly-metric", date_order="mdy").refuels[0]
        assert dmy.date == date(2024, 4, 3)
        assert mdy.date == date(2024, 3, 4)

    def test_missing_required_columns_block(self) -> None:
        data = b"fuelup_date,price\n2024-01-01,1.4\n"
        chosen = preset("fuelly-metric")
        result = engine.apply(chosen, engine.read_file(data, chosen), Answers())
        assert result.errors and not result.refuels

    def test_website_export_asks_units(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelly_export.csv", "fuelly-website")
        kinds = {q.kind.value for q in result.questions}
        assert kinds == {"distance_unit", "volume_unit"}
        assert result.refuels == []

    def test_website_export_us_answers_convert(self, fixtures_dir) -> None:
        result = run(
            fixtures_dir, "fuelly_export.csv", "fuelly-website",
            distance_unit="mi", volume_unit="gal_us",
        )  # fmt: skip
        assert not result.questions and not result.errors
        first = result.refuels[0]
        assert first.litres_milli == 37854
        assert first.price_per_litre_milli == 925
        assert first.odometer_km == pytest.approx(12000 * 1.609344)
        assert first.vehicle_name == "Test Car"
        assert [v.name for v in result.vehicles] == ["Test Car"]
        assert first.notes == "first"
        assert all(r.is_full and not r.missed_previous for r in result.refuels)

    def test_website_export_metric_answers_keep_values(self, fixtures_dir) -> None:
        result = run(
            fixtures_dir, "fuelly_export.csv", "fuelly-website",
            distance_unit="km", volume_unit="l",
        )  # fmt: skip
        first = result.refuels[0]
        assert first.litres_milli == 10000
        assert first.odometer_km == 12000


class TestFuelio:
    def test_comma_km_refuels(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelio_comma_km.csv", "fuelio-fillups")
        assert not result.errors and not result.row_errors and not result.questions
        first, second, third, _fourth = result.refuels
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

    def test_total_versus_per_litre_price(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelio_comma_km.csv", "fuelio-fillups")
        fourth = result.refuels[3]
        assert fourth.litres_milli == 72604
        assert fourth.total_cents == 300000
        assert fourth.price_per_litre_milli == 41320

    def test_station_comes_from_city_column_only(self, fixtures_dir) -> None:
        # Design D9: no lookup in ## FavStations any more.
        result = run(fixtures_dir, "fuelio_comma_km.csv", "fuelio-fillups")
        assert result.refuels[1].station_name == "Beta Oil"
        assert result.refuels[2].station_name is None

    def test_semicolon_miles_and_gallons_converted(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "fuelio_semicolon_miles.csv", "fuelio-fillups")
        first = result.refuels[0]
        assert first.odometer_km == pytest.approx(1609.344)
        assert first.litres_milli == 37854
        assert first.total_cents == 3500
        assert first.price_per_litre_milli == 925  # 3.50 per gallon

    def test_cp1252_semicolon_file(self) -> None:
        text = (
            "## Log\n"
            "Data;Odo (km);Fuel (litres);Full;Price (optional);VolumePrice;City (optional)\n"
            "2024-01-01 10:00;1000;45,20;1;65,95;1,459;Šentilj\n"
        )
        chosen = preset("fuelio-fillups")
        source = engine.read_file(text.encode("cp1252"), chosen)
        refuel = engine.apply(chosen, source, Answers()).refuels[0]
        assert (refuel.litres_milli, refuel.total_cents) == (45200, 6595)
        assert refuel.station_name == "Šentilj"

    def test_zero_prices_are_missing_and_full_defaults_true(self) -> None:
        data = (
            b"## Log\nData;Odo (km);Fuel (litres);Full;Price (optional);VolumePrice\n"
            b"2024-01-01 10:00;1000;40.0;;0;0\n"
        )
        chosen = preset("fuelio-fillups")
        refuel = engine.apply(chosen, engine.read_file(data, chosen), Answers()).refuels[0]
        assert refuel.total_cents is None and refuel.price_per_litre_milli is None
        assert refuel.is_full

    def test_bad_row_is_a_row_error(self) -> None:
        data = (
            b"## Log\nData;Odo (km);Fuel (litres);Full\n"
            b"2024-01-01 10:00;1000;40.0;1\n2024-01-02 10:00;abc;40.0;1\n"
        )
        chosen = preset("fuelio-fillups")
        result = engine.apply(chosen, engine.read_file(data, chosen), Answers())
        assert len(result.refuels) == 1
        assert [e.field for e in result.row_errors] == ["odometer_km"]

    def test_ambiguous_dates_ask(self) -> None:
        data = b"## Log\nData;Odo (km);Fuel (litres)\n03/04/2024;1000;40.0\n"
        chosen = preset("fuelio-fillups")
        source = engine.read_file(data, chosen)
        assert [q.kind.value for q in engine.apply(chosen, source).questions] == [
            "date_order"
        ]
        dmy = engine.apply(chosen, source, Answers(date_order="dmy"))
        assert dmy.refuels[0].date == date(2024, 4, 3)

    def test_costs(self, fixtures_dir) -> None:
        result = run(
            fixtures_dir, "fuelio_comma_km.csv", "fuelio-costs", distance_unit="km"
        )
        assert not result.errors and not result.row_errors
        oil, policy, garage = result.expenses
        assert [e.title for e in result.expenses] == ["Oil change", "Policy 2024", "Garage"]
        assert [e.category for e in result.expenses] == [
            ExpenseCategory.MAINTENANCE,
            ExpenseCategory.OTHER,  # D9: mapped from the title only
            ExpenseCategory.OTHER,
        ]
        assert [e.amount_cents for e in result.expenses] == [12050, 40000, 500]
        assert oil.odometer_km == 10800
        assert policy.odometer_km is None
        assert oil.notes == "with filter"
        assert oil.source_ref == "c1"
        assert garage.date == date(2024, 2, 2)

    def test_template_income_and_zero_rows_are_skipped(self, fixtures_dir) -> None:
        result = run(
            fixtures_dir, "fuelio_comma_km.csv", "fuelio-costs", distance_unit="km"
        )
        assert len(result.expenses) == 3  # fixture has 6 cost rows
        assert result.skipped == 3
        assert not result.row_errors

    def test_thousands_separator_is_a_row_error_by_default(self, fixtures_dir) -> None:
        # "1.234,50" has a thousands separator; the preset sets none (strict numbers).
        result = run(
            fixtures_dir, "fuelio_semicolon_miles.csv", "fuelio-costs", distance_unit="mi"
        )
        assert result.expenses == []
        assert [e.field for e in result.row_errors] == ["total"]

    def test_decimal_comma_cost(self) -> None:
        data = (
            b"## Costs\nCostTitle;Date;Odo;CostTypeID;Notes;Cost;isTemplate;isIncome\n"
            b"Brake pads;2024-06-20 10:00;1200;1;;1234,50;0;0\n"
        )
        chosen = preset("fuelio-costs")
        source = engine.read_file(data, chosen)
        result = engine.apply(chosen, source, Answers(distance_unit="mi"))
        assert result.expenses[0].amount_cents == 123450
        assert result.expenses[0].category == ExpenseCategory.OTHER
        assert result.expenses[0].odometer_km == pytest.approx(1200 * 1.609344)

    def test_zip_member_name_is_the_vehicle(self, fixtures_dir) -> None:
        archive = zip_of(
            {
                "Test Golf.csv": (fixtures_dir / "fuelio_comma_km.csv").read_bytes(),
                "Miles Car.csv": (fixtures_dir / "fuelio_semicolon_miles.csv").read_bytes(),
                "readme.txt": b"ignored",
            }
        )
        chosen = preset("fuelio-fillups")
        result = engine.apply(chosen, engine.read_file(archive, chosen), Answers())
        assert sorted(v.name for v in result.vehicles) == ["Miles Car", "Test Golf"]
        assert len(result.refuels) == 6
        assert {r.vehicle_name for r in result.refuels} == {"Test Golf", "Miles Car"}


class TestDrivvo:
    """The Android History export: three sections in one file (synthetic sample)."""

    def test_detection_and_section_scores(self, fixtures_dir) -> None:
        data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
        _, scores = detect(data)
        assert scores["drivvo-refuelling"] == 1.0
        assert scores["drivvo-expenses"] == 1.0 and scores["drivvo-services"] == 1.0
        assert engine.read_file(data).sections == ["Refuelling", "Expense", "Service"]

    def test_refuel_rows_use_the_first_fuel(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "drivvo_en_sections.csv", "drivvo-refuelling")
        assert not result.errors and not result.row_errors and not result.questions
        assert not result.expenses and len(result.refuels) == 4
        first, second, partial, last = result.refuels
        assert (first.date, first.time) == (date(2025, 3, 2), time(8, 15))
        assert first.odometer_km == 10250
        assert (first.litres_milli, first.price_per_litre_milli) == (40000, 1453)
        assert first.total_cents == 5812
        assert first.station_name == "Alpha Fuel"
        assert first.is_full and not first.missed_previous
        assert second.notes == "Weekly shop" and second.time == time(17, 40, 12)
        assert not partial.is_full and partial.total_cents == 1520
        assert last.station_name == "Čista Črpalka"
        assert first.vehicle_name is None  # no vehicle column: chosen at import

    def test_malformed_header_cells_are_read(self, fixtures_dir) -> None:
        data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
        source = engine.read_file(data, preset("drivvo-refuelling"))
        headers = source.tables[0].headers
        assert len(headers) == 29
        assert headers[6] == "Filled tank completely"
        assert headers[11] == "Filled tank completely 2"
        assert headers.count("Price / L") == 3

    def test_expense_rows(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "drivvo_en_sections.csv", "drivvo-expenses")
        assert not result.errors and not result.row_errors and not result.refuels
        parking, insurance, registration = result.expenses
        assert (parking.title, parking.category) == ("Parking", ExpenseCategory.OTHER)
        assert parking.odometer_km is None  # "0.0" means no reading
        assert parking.notes == "Old ticket"
        assert insurance.category == ExpenseCategory.INSURANCE
        assert insurance.amount_cents == 35000 and insurance.odometer_km == 11000
        assert registration.category == ExpenseCategory.REGISTRATION
        assert registration.amount_cents == 12050

    def test_service_items_become_maintenance_expenses(self, fixtures_dir) -> None:
        result = run(fixtures_dir, "drivvo_en_sections.csv", "drivvo-services")
        assert not result.errors and not result.row_errors
        assert result.skipped == 1  # the item without a price
        titles = [e.title for e in result.expenses]
        assert titles == ["Oil Change", "Cabin Air Filter", "Wiper Blades", "Labor Cost"]
        assert {e.category for e in result.expenses} == {ExpenseCategory.MAINTENANCE}
        assert sum(e.amount_cents for e in result.expenses) == 15800
        assert result.expenses[1].notes == "First line\nsecond line"

    def test_web_export_sections_and_escapes_are_read(self, fixtures_dir) -> None:
        # The web export uses "#Section" markers, "%uXXXX" escapes and spaces
        # before some quoted header cells. Its expenses read with the shipped
        # preset; its "#Refueling" section is not covered by one.
        data = (fixtures_dir / "drivvo_web_sections.csv").read_bytes()
        source = engine.read_file(data)
        assert source.sections == ["Vehicle", "Refueling", "Expense", "Service"]
        assert detect(data)[1]["drivvo-refuelling"] == 0.0
        result = run(fixtures_dir, "drivvo_web_sections.csv", "drivvo-expenses")
        (insurance,) = result.expenses
        assert insurance.category == ExpenseCategory.INSURANCE
        assert (insurance.date, insurance.amount_cents) == (date(2025, 3, 25), 35000)
        services = run(fixtures_dir, "drivvo_web_sections.csv", "drivvo-services")
        assert [e.notes for e in services.expenses] == ["Menjava olja in filtra, žaga"]

    def test_headers_are_case_and_whitespace_insensitive(self) -> None:
        data = b"##Refuelling\n  DATE ,odometer (KM),VOLUME ,total  COST\n2024-01-01,100,10.0,15.0\n"
        chosen = preset("drivvo-refuelling")
        result = engine.apply(chosen, engine.read_file(data, chosen), Answers())
        assert len(result.refuels) == 1
