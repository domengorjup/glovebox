"""Import pipeline: detection, preview, commit, duplicates, undo and backup restore."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import func, select

from glovebox.importers import engine
from glovebox.importers.base import Answers, QuestionKind
from glovebox.importers.pipeline import (
    VehicleMapping,
    commit_import,
    detect_preset,
    list_batches,
    preview_import,
    undo_batch,
)
from glovebox.importers.presets import list_presets, load_preset, save_user_preset
from glovebox.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    ImportBatch,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.services.records import NotFoundError, ValidationError

STANDARD = engine.standard_preset()

REFUELS = load_preset(
    """
name = "Sample refuels"
note = "Sample note."
[format]
distance_unit = "km"
volume_unit = "l"
[fields]
type = { value = "refuel" }
date = { column = "fuelup_date" }
odometer_km = { column = "odometer" }
fuel_l = { column = "litres" }
price_per_l = { column = "price" }
total = { column = "total" }
full = { column = "partial", true_values = ["0"], false_values = ["1"], default = "true" }
station = { column = "tags" }
""",
    id="sample-refuels",
)

FUELLY = (
    b"fuelup_date,odometer,litres,price,total,partial,tags\n"
    b"2024-01-10,1000,40.000,1.500,,0,Alpha Fuel\n"
    b"2024-01-20,1600,20.000,,31.00,1,Beta Oil\n"
    b"2024-02-01,2200,30.000,1.400,,0,Alpha Fuel\n"
)


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _vehicle(session, name: str = "Target") -> int:
    vehicle = Vehicle(name=name)
    session.add(vehicle)
    session.commit()
    return vehicle.id


def _mapping(session) -> VehicleMapping:
    return VehicleMapping(default_vehicle_id=_vehicle(session))


@pytest.fixture
def standard_file(fixtures_dir) -> bytes:
    return (fixtures_dir / "standard_records.csv").read_bytes()


class TestDetection:
    def test_standard_file_selects_the_standard_preset(self, session, standard_file) -> None:
        assert detect_preset(session, standard_file).id == "glovebox"

    def test_unknown_headers_select_nothing(self, session) -> None:
        assert detect_preset(session, b"Datum,Km\n1.1.2024,5\n") is None
        assert detect_preset(session, b"") is None

    def test_user_preset_is_detected(self, session) -> None:
        saved = save_user_preset(session, replace(REFUELS, id="", name="My app"))
        assert detect_preset(session, FUELLY).id == saved.id

    def test_user_preset_wins_a_tie(self, session) -> None:
        saved = save_user_preset(session, replace(REFUELS, id="", name="My app"))
        twin = save_user_preset(session, replace(REFUELS, id="", name="Another"))
        assert detect_preset(session, FUELLY).id in {saved.id, twin.id}

    def test_backup_selects_the_standard_preset(self, session) -> None:
        assert detect_preset(session, _backup()).id == "glovebox"


class TestFuelioTie:
    """A Fuelio file with both sections scores 1.0 for both Fuelio presets."""

    def test_fillups_wins_deterministically(self, session, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
        shipped = {p.id: p for p in list_presets(session)}
        scores = {i: engine.score(shipped[i], engine.read_file(data, shipped[i]))
                  for i in ("fuelio-fillups", "fuelio-costs")}
        assert scores["fuelio-fillups"] == scores["fuelio-costs"] == 1.0
        assert detect_preset(session, data).id == "fuelio-fillups"

    def test_user_preset_still_wins_the_tie(self, session, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
        fillups = next(p for p in list_presets(session) if p.id == "fuelio-fillups")
        save_user_preset(session, replace(fillups, name="My Fuelio", id="", shipped=False))
        assert detect_preset(session, data).name == "My Fuelio"


class TestPreview:
    def test_preview_does_not_write(self, session, standard_file) -> None:
        preview = preview_import(session, standard_file, STANDARD)
        assert preview.format == "glovebox"
        assert preview.vehicle_names == ["Golf", "Polo"]
        assert (preview.new_refuels, preview.new_expenses) == (3, 2)
        assert (preview.duplicate_refuels, preview.duplicate_expenses) == (0, 0)
        assert preview.errors == [] and preview.row_errors == []
        for model in (Refuel, Expense, Vehicle, Station, ImportBatch):
            assert count(session, model) == 0

    def test_preview_carries_the_preset_note(self, session) -> None:
        preview = preview_import(session, FUELLY, REFUELS, mapping=_mapping(session))
        assert preview.preset_note == "Sample note."

    def test_unmapped_required_fields_block(self, session) -> None:
        preview = preview_import(session, b"Datum,Km\n2024-01-01,5\n", STANDARD)
        assert any("'date'" in e for e in preview.errors)
        assert any("'type'" in e for e in preview.errors)
        with pytest.raises(ValidationError):
            commit_import(session, b"Datum,Km\n2024-01-01,5\n", "x.csv", VehicleMapping(), STANDARD)
        assert count(session, Refuel) == 0

    def test_questions_are_surfaced_then_answered(self, session) -> None:
        data = b"fuelup_date,odometer,litres,price,total,partial,tags\n01/02/2024,1000,40,1.5,,0,\n03/04/2024,1500,40,1.5,,0,\n"
        mapping = _mapping(session)
        asked = preview_import(session, data, REFUELS, mapping=mapping)
        assert [q.kind for q in asked.questions] == [QuestionKind.DATE_ORDER]
        assert asked.new_refuels == 0
        with pytest.raises(ValidationError):
            commit_import(session, data, "f.csv", mapping, REFUELS)
        answered = preview_import(
            session, data, REFUELS, mapping=mapping, answers=Answers(date_order="dmy")
        )
        assert answered.questions == [] and answered.new_refuels == 2

    def test_file_without_vehicle_names_requires_target(self, session) -> None:
        preview = preview_import(session, FUELLY, REFUELS)
        assert preview.errors and preview.vehicle_names == []
        assert preview.needs_vehicle_choice
        with pytest.raises(ValidationError):
            commit_import(session, FUELLY, "f.csv", VehicleMapping(), REFUELS)
        assert count(session, Refuel) == 0

    def test_zip_member_names_are_the_vehicles(self, session) -> None:
        data = _zip({"Golf.csv": FUELLY.decode(), "Polo.csv": FUELLY.decode()})
        preview = preview_import(session, data, REFUELS)
        assert preview.vehicle_names == ["Golf", "Polo"]
        assert preview.new_refuels == 6

    def test_mapping_to_none_creates_vehicle(self, session, standard_file) -> None:
        mapping = VehicleMapping(by_name={"Golf": None, "Polo": None})
        commit_import(session, standard_file, "f.csv", mapping, STANDARD)
        assert {v.name for v in session.scalars(select(Vehicle))} == {"Golf", "Polo"}

    def test_mapping_to_none_with_active_same_name_is_an_error(
        self, session, standard_file
    ) -> None:
        _vehicle(session, "Golf")
        mapping = VehicleMapping(by_name={"Golf": None})
        preview = preview_import(session, standard_file, STANDARD, mapping=mapping)
        assert "already exists" in preview.errors[0]
        with pytest.raises(ValidationError):
            commit_import(session, standard_file, "f.csv", mapping, STANDARD)

    def test_undo_unknown_batch_raises_not_found(self, session) -> None:
        with pytest.raises(NotFoundError):
            undo_batch(session, 999)

    def test_row_errors_and_skips_are_reported_and_not_blocking(
        self, session, fixtures_dir
    ) -> None:
        data = (fixtures_dir / "standard_bad_rows.csv").read_bytes()
        preview = preview_import(session, data, STANDARD, mapping=_mapping(session))
        assert preview.errors == []
        assert (preview.new_refuels, preview.new_expenses) == (2, 1)
        assert [e.line for e in preview.row_errors] == [3, 4, 5, 6, 8, 12]
        # One price figure only: the pipeline skips the refuel and says why.
        assert any("2026-05-06" in w for w in preview.warnings)

    def test_a_preset_is_required_unless_the_file_is_a_backup(self, session) -> None:
        assert preview_import(session, FUELLY).errors == ["Choose a preset for this file."]
        assert preview_import(session, _backup()).errors == []

    def test_skip_rule_count(self, session) -> None:
        text = """
name = "Skip"
[format]
distance_unit = "km"
volume_unit = "l"
[fields]
type = { value = "refuel" }
date = { column = "d" }
odometer_km = { column = "o" }
fuel_l = { column = "l" }
total = { column = "t" }
[[skip_rows]]
column = "flag"
values = ["1"]
"""
        data = b"d,o,l,t,flag\n2024-01-01,1,40,60,0\n2024-01-02,2,40,60,1\n"
        preview = preview_import(session, data, load_preset(text), mapping=_mapping(session))
        assert (preview.new_refuels, preview.skipped) == (1, 1)


class TestCommit:
    def test_commit_writes_everything_in_one_batch(self, session, standard_file) -> None:
        batch = commit_import(session, standard_file, "std.csv", VehicleMapping(), STANDARD)
        assert (batch.format, batch.filename) == ("glovebox", "std.csv")
        assert (batch.refuels_imported, batch.expenses_imported) == (3, 2)
        assert {v.name for v in session.scalars(select(Vehicle))} == {"Golf", "Polo"}
        refuels = session.scalars(select(Refuel).order_by(Refuel.date)).all()
        assert {r.import_batch_id for r in refuels} == {batch.id}
        assert count(session, Expense) == 2

    def test_batch_format_is_the_preset_id(self, session) -> None:
        batch = commit_import(session, FUELLY, "f.csv", _mapping(session), REFUELS)
        assert batch.format == "sample-refuels"
        assert {r.source for r in session.scalars(select(Refuel))} == {"sample-refuels"}

    def test_unsaved_preset_uses_custom_as_format(self, session) -> None:
        batch = commit_import(
            session, FUELLY, "f.csv", _mapping(session), replace(REFUELS, id="")
        )
        assert batch.format == "custom"

    def test_two_of_three_derivation(self, session) -> None:
        commit_import(session, FUELLY, "f.csv", _mapping(session), REFUELS)
        refuels = session.scalars(select(Refuel).order_by(Refuel.date)).all()
        first, second, third = refuels
        assert (first.litres_milli, first.price_per_litre_milli, first.total_cents) == (
            40000, 1500, 6000,
        )  # fmt: skip
        assert first.derived_field == DerivedField.TOTAL
        assert (second.price_per_litre_milli, second.derived_field) == (
            1550, DerivedField.PRICE_PER_LITRE,
        )  # fmt: skip
        assert second.is_full is False
        assert third.total_cents == 4200

    def test_rows_with_errors_are_skipped_and_the_rest_commits(
        self, session, fixtures_dir
    ) -> None:
        data = (fixtures_dir / "standard_bad_rows.csv").read_bytes()
        batch = commit_import(session, data, "f.csv", _mapping(session), STANDARD)
        assert (batch.refuels_imported, batch.expenses_imported) == (2, 1)
        assert count(session, Refuel) == 2 and count(session, Expense) == 1

    def test_station_created_once_with_location_and_brand(self, session, standard_file) -> None:
        commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        omv = session.scalar(select(Station).where(Station.name == "OMV Celje"))
        assert (omv.location, omv.brand) == ("Celje", "OMV")
        assert count(session, Station) == 2
        assert all(s.import_batch_id for s in session.scalars(select(Station)))

    def test_station_shared_by_several_refuels_is_created_once(self, session) -> None:
        commit_import(session, FUELLY, "f.csv", _mapping(session), REFUELS)
        assert {s.name for s in session.scalars(select(Station))} == {"Alpha Fuel", "Beta Oil"}
        alpha = session.scalar(select(Station).where(Station.name == "Alpha Fuel"))
        assert session.scalar(
            select(func.count()).select_from(Refuel).where(Refuel.station_id == alpha.id)
        ) == 2
        assert alpha.brand is None  # a brand is never inferred

    def test_station_is_reused_across_imports(self, session) -> None:
        mapping = _mapping(session)
        commit_import(session, FUELLY, "a.csv", mapping, REFUELS)
        more = b"fuelup_date,odometer,litres,price,total,partial,tags\n2024-09-01,9000,30,1.5,,0,Alpha Fuel\n"
        commit_import(session, more, "b.csv", mapping, REFUELS)
        assert count(session, Station) == 2

    def test_file_provided_source_and_derived_are_kept(self, session, standard_file) -> None:
        commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        second = session.scalar(select(Refuel).where(Refuel.date == date(2026, 5, 20)))
        assert second.source == "sample-preset"
        assert second.derived_field == DerivedField.PRICE_PER_LITRE
        assert second.price_per_litre_milli == 1450
        assert second.missed_previous is True and second.is_full is False
        first = session.scalar(select(Refuel).where(Refuel.date == date(2026, 5, 2)))
        assert first.source == "manual" and first.source_ref == "r1"

    def test_expense_fields(self, session, standard_file) -> None:
        commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        insurance = session.scalar(
            select(Expense).where(Expense.category == ExpenseCategory.INSURANCE)
        )
        assert insurance.title == "Insurance 2026" and insurance.amount_cents == 42000
        assert (insurance.coverage_start, insurance.coverage_end) == (
            date(2026, 1, 1), date(2026, 12, 31),
        )  # fmt: skip

    def test_map_file_vehicle_to_existing_one(self, session, standard_file) -> None:
        golf = _vehicle(session, "My car")
        mapping = VehicleMapping(by_name={"Golf": golf, "Polo": golf})
        commit_import(session, standard_file, "f.csv", mapping, STANDARD)
        assert [v.name for v in session.scalars(select(Vehicle))] == ["My car"]
        assert {r.vehicle_id for r in session.scalars(select(Refuel))} == {golf}

    def test_same_name_vehicle_is_reused(self, session, standard_file) -> None:
        existing = _vehicle(session, "Golf")
        commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        assert count(session, Vehicle) == 2
        golf_refuels = session.scalars(select(Refuel).where(Refuel.vehicle_id == existing))
        assert len(golf_refuels.all()) == 2

    def test_failed_commit_leaves_no_trace(self, session, standard_file, monkeypatch) -> None:
        from glovebox.importers import pipeline

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(pipeline, "_new_expense", boom)
        with pytest.raises(RuntimeError):
            commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        for model in (Refuel, Expense, Vehicle, Station, ImportBatch):
            assert count(session, model) == 0


class TestDuplicates:
    def test_reimport_is_a_noop(self, session, standard_file) -> None:
        commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        second = preview_import(session, standard_file, STANDARD)
        assert (second.new_refuels, second.new_expenses) == (0, 0)
        assert (second.duplicate_refuels, second.duplicate_expenses) == (3, 2)
        assert second.nothing_new
        with pytest.raises(ValidationError, match="Nothing new"):
            commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        assert len(list_batches(session)) == 1  # no empty batch
        assert count(session, Refuel) == 3 and count(session, Expense) == 2
        assert count(session, Vehicle) == 2

    def test_litres_compared_at_two_decimals(self, session) -> None:
        mapping = _mapping(session)
        head = b"fuelup_date,odometer,litres,price,total,partial,tags\n"
        first = head + b"2024-01-01,1000,40.001,1.5,,0,\n"
        second = head + b"2024-01-01,1000,40.004,1.5,,0,\n"
        commit_import(session, first, "a.csv", mapping, REFUELS)
        assert preview_import(session, second, REFUELS, mapping=mapping).duplicate_refuels == 1

    def test_duplicates_inside_one_file(self, session) -> None:
        data = (
            b"fuelup_date,odometer,litres,price,total,partial,tags\n"
            b"2024-01-01,1000,40.0,1.5,,0,\n2024-01-01,1000,40.0,1.5,,0,\n"
        )
        preview = preview_import(session, data, REFUELS, mapping=_mapping(session))
        assert (preview.new_refuels, preview.duplicate_refuels) == (1, 1)

    def test_expense_key_includes_category_and_amount(self, session, standard_file) -> None:
        commit_import(session, standard_file, "e.csv", VehicleMapping(), STANDARD)
        changed = standard_file.replace(b",180.00,", b",181.00,")
        preview = preview_import(session, changed, STANDARD)
        assert (preview.new_expenses, preview.duplicate_expenses) == (1, 1)


    def test_equal_expenses_in_one_file_are_all_kept(self, session, fixtures_dir) -> None:
        # Two service items of the same price on the same day are two records;
        # a re-import matches them one to one against the database.
        services = next(p for p in list_presets(session) if p.id == "drivvo-services")
        data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
        mapping = _mapping(session)
        first = preview_import(session, data, services, mapping=mapping)
        assert (first.new_expenses, first.duplicate_expenses) == (4, 0)
        commit_import(session, data, "d.csv", mapping, preset=services)
        again = preview_import(session, data, services, mapping=mapping)
        assert (again.new_expenses, again.duplicate_expenses) == (0, 4)

class TestUndo:
    def test_undo_removes_batch_and_its_stations(self, session, standard_file) -> None:
        batch = commit_import(session, standard_file, "f.csv", VehicleMapping(), STANDARD)
        undo_batch(session, batch.id)
        for model in (Refuel, Expense, Station, ImportBatch):
            assert count(session, model) == 0
        assert count(session, Vehicle) == 2  # vehicles are kept

    def test_undo_keeps_other_batches_and_shared_stations(self, session) -> None:
        mapping = _mapping(session)
        first = commit_import(session, FUELLY, "a", mapping, REFUELS)
        extra = b"fuelup_date,odometer,litres,price,total,partial,tags\n2024-09-01,9000,30,1.5,,0,Alpha Fuel\n"
        second = commit_import(session, extra, "b", mapping, REFUELS)
        undo_batch(session, second.id)
        assert count(session, Refuel) == 3
        assert {s.name for s in session.scalars(select(Station))} == {"Alpha Fuel", "Beta Oil"}
        assert [b.id for b in list_batches(session)] == [first.id]
        undo_batch(session, first.id)
        assert count(session, Station) == 0

    def test_station_used_by_other_records_survives(self, session) -> None:
        mapping = _mapping(session)
        batch = commit_import(session, FUELLY, "a", mapping, REFUELS)
        alpha = session.scalar(select(Station).where(Station.name == "Alpha Fuel"))
        session.add(
            Refuel(
                vehicle_id=mapping.default_vehicle_id,
                date=date(2025, 1, 1),
                odometer_km=1,
                litres_milli=1000,
                price_per_litre_milli=1000,
                total_cents=100,
                station_id=alpha.id,
            )
        )
        session.commit()
        undo_batch(session, batch.id)
        assert {s.name for s in session.scalars(select(Station))} == {"Alpha Fuel"}
        assert session.scalar(select(Station)).import_batch_id is None

    def test_batches_newest_first(self, session) -> None:
        mapping = _mapping(session)
        a = commit_import(session, FUELLY, "a", mapping, REFUELS)
        more = FUELLY + b"2024-03-01,2800,30.000,1.400,,0,Alpha Fuel\n"
        b = commit_import(session, more, "b", mapping, REFUELS)
        assert [x.id for x in list_batches(session)] == [b.id, a.id]


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


RECORD_HEAD = (
    "type,vehicle,date,time,odometer_km,fuel_l,price_per_l,total,currency,full,"
    "missed_previous,station,station_location,station_brand,category,title,"
    "coverage_start,coverage_end,notes,derived,source,source_ref\n"
)


def _backup(records: str | None = None, **extra: str) -> bytes:
    members = {
        "datapackage.json": "{}",
        "records.csv": RECORD_HEAD
        + (
            records
            if records is not None
            else "refuel,Golf,2026-05-20,08:05,98600,40.000,1.450,58.00,EUR,false,true,"
            "Petrol Ljubljana,Ljubljana,Petrol,,,,,,price_per_l,drivvo-refuelling,r2\n"
            "expense,Golf,2026-05-10,,98400,,,180.00,EUR,,,,,,maintenance,Oil change,,,,,manual,e1\n"
        ),
        "vehicles.csv": "name,make,model,plate,fuel_type,initial_odometer_km,archived,notes\n"
        "Golf,Volkswagen,Golf VII,LJ AB-123,Diesel,85000,false,Company car\n"
        "Old Polo,VW,Polo,,Petrol,1000.5,true,\n",
        "stations.csv": "name,location,brand\n"
        "Petrol Ljubljana,Ljubljana,Petrol\nUnused Station,Maribor,\n",
    }
    members.update(extra)
    return _zip(members)


class TestBackupRestore:
    def test_preview_counts_and_vehicles(self, session) -> None:
        preview = preview_import(session, _backup(), STANDARD)
        assert preview.is_backup and preview.format == "glovebox"
        assert preview.vehicle_names == ["Golf", "Old Polo"]
        assert (preview.new_refuels, preview.new_expenses) == (1, 1)
        assert preview.errors == []
        assert count(session, Vehicle) == 0

    def test_backup_is_restored_whatever_preset_is_given(self, session) -> None:
        batch = commit_import(session, _backup(), "b.zip", VehicleMapping(), REFUELS)
        assert batch.format == "glovebox"
        assert count(session, Refuel) == 1

    def test_vehicles_with_details_and_stations_without_refuels(self, session) -> None:
        commit_import(session, _backup(), "b.zip", VehicleMapping(), STANDARD)
        golf = session.scalar(select(Vehicle).where(Vehicle.name == "Golf"))
        assert (golf.make, golf.model, golf.plate, golf.fuel_type) == (
            "Volkswagen", "Golf VII", "LJ AB-123", "Diesel",
        )  # fmt: skip
        assert (golf.initial_odometer, golf.archived, golf.notes) == (85000.0, False, "Company car")
        polo = session.scalar(select(Vehicle).where(Vehicle.name == "Old Polo"))
        assert polo.archived is True and polo.initial_odometer == 1000.5
        names = {s.name for s in session.scalars(select(Station))}
        assert names == {"Petrol Ljubljana", "Unused Station"}
        unused = session.scalar(select(Station).where(Station.name == "Unused Station"))
        assert unused.location == "Maribor" and unused.brand is None

    def test_derived_field_and_source_are_restored(self, session) -> None:
        commit_import(session, _backup(), "b.zip", VehicleMapping(), STANDARD)
        refuel = session.scalar(select(Refuel))
        assert refuel.derived_field == DerivedField.PRICE_PER_LITRE
        assert refuel.source == "drivvo-refuelling"
        assert refuel.price_per_litre_milli == 1450

    def test_restore_twice_is_a_noop(self, session) -> None:
        commit_import(session, _backup(), "b.zip", VehicleMapping(), STANDARD)
        with pytest.raises(ValidationError, match="Nothing new"):
            commit_import(session, _backup(), "b.zip", VehicleMapping(), STANDARD)
        assert len(list_batches(session)) == 1
        assert count(session, Vehicle) == 2 and count(session, Station) == 2

    def test_vehicle_mapping_applies(self, session) -> None:
        mine = _vehicle(session, "Mine")
        mapping = VehicleMapping(by_name={"Golf": mine})
        commit_import(session, _backup(), "b.zip", mapping, STANDARD)
        assert {r.vehicle_id for r in session.scalars(select(Refuel))} == {mine}
        assert {v.name for v in session.scalars(select(Vehicle))} == {"Mine", "Old Polo"}

    def test_undo_removes_restored_records_and_stations(self, session) -> None:
        batch = commit_import(session, _backup(), "b.zip", VehicleMapping(), STANDARD)
        undo_batch(session, batch.id)
        assert count(session, Refuel) == 0 and count(session, Station) == 0

    def test_missing_records_file_is_an_error(self, session) -> None:
        data = _zip({"datapackage.json": "{}", "vehicles.csv": "name\nGolf\n"})
        preview = preview_import(session, data, STANDARD)
        assert "records.csv" in preview.errors[0]

    def test_bad_record_rows_are_reported(self, session) -> None:
        bad = "refuel,Golf,2026-13-45,,98600,40.000,,58.00,,,,,,,,,,,,,,\n"
        preview = preview_import(session, _backup(bad), STANDARD)
        assert preview.row_errors and preview.new_refuels == 0

    def test_bad_vehicle_odometer_is_reported_but_not_fatal(self, session) -> None:
        vehicles = "name,initial_odometer_km\nGolf,abc\n"
        preview = preview_import(session, _backup(**{"vehicles.csv": vehicles}), STANDARD)
        assert preview.row_errors and "vehicles.csv" in preview.row_errors[0].message
        assert preview.errors == []


def _with_companions(**members: str) -> bytes:
    """A ZIP of records.csv (standard format) plus the given tables, no datapackage.json."""
    records = (
        RECORD_HEAD
        + "refuel,Golf,2026-05-20,,98600,40.000,1.450,58.00,,,,Petrol Ljubljana,Ljubljana,,,,,,,,,\n"
    )
    return _zip({"records.csv": records, **members})


class TestCompanionTables:
    """vehicles.csv and stations.csv in a normal import (no datapackage.json)."""

    def test_detected_as_standard_and_not_a_backup(self, session) -> None:
        data = _with_companions(**{"vehicles.csv": "name,make\nGolf,VW\n"})
        assert detect_preset(session, data).id == "glovebox"
        preview = preview_import(session, data, STANDARD)
        assert not preview.is_backup and preview.vehicle_names == ["Golf"]

    def test_records_table_is_not_a_vehicle_name(self, session) -> None:
        data = _zip({"records.csv": "date,odo,l,price\n2024-01-01,5,40,1.5\n",
                     "stations.csv": "name\nA\n"})
        preset = replace(REFUELS, fields={**REFUELS.fields})
        preview = preview_import(session, data, preset)
        assert "records" not in preview.vehicle_names

    def test_missing_vehicle_and_station_are_created_with_details(self, session) -> None:
        data = _with_companions(**{
            "vehicles.csv": "name,make,model,plate,fuel_type,initial_odometer_km,notes\n"
                            "Golf,VW,Golf VII,LJ AB-123,Diesel,85000,Company car\n",
            "stations.csv": "name,location,brand\nPetrol Ljubljana,Ljubljana,Petrol\n"
                            "Unused,Maribor,OMV\n",
        })
        preview = preview_import(session, data, STANDARD)
        listed = {(c.kind, c.action, c.name) for c in preview.companion_changes}
        assert listed == {
            ("vehicle", "create", "Golf"),
            ("station", "create", "Petrol Ljubljana"),
            ("station", "create", "Unused"),
        }
        assert count(session, Vehicle) == 0 and count(session, Station) == 0
        commit_import(session, data, "x.zip", VehicleMapping(), STANDARD)
        golf = session.scalar(select(Vehicle))
        assert (golf.make, golf.plate, golf.initial_odometer) == ("VW", "LJ AB-123", 85000.0)
        stations = {s.name: s for s in session.scalars(select(Station))}
        assert set(stations) == {"Petrol Ljubljana", "Unused"}
        assert stations["Unused"].brand == "OMV"
        assert session.scalar(select(Refuel)).station_id == stations["Petrol Ljubljana"].id

    def test_existing_vehicle_only_gets_empty_fields_filled(self, session) -> None:
        session.add(Vehicle(name="Golf", make="Seat", plate=None, notes=""))
        session.commit()
        data = _with_companions(**{
            "vehicles.csv": "name,make,plate,notes,fuel_type\nGolf,VW,LJ AB-123,Note,Diesel\n"
        })
        preview = preview_import(session, data, STANDARD)
        (change,) = preview.companion_changes
        assert (change.action, change.name) == ("fill", "Golf")
        assert set(change.fields) == {"plate", "notes", "fuel_type"}
        commit_import(session, data, "x.zip", VehicleMapping(), STANDARD)
        golf = session.scalar(select(Vehicle))
        assert (golf.make, golf.plate, golf.notes, golf.fuel_type) == (
            "Seat", "LJ AB-123", "Note", "Diesel",
        )  # fmt: skip
        assert count(session, Vehicle) == 1

    def test_existing_station_keeps_its_brand_and_gets_a_missing_one(self, session) -> None:
        session.add_all([
            Station(name="A", location="X", brand="Old"),
            Station(name="B", location="Y", brand=None),
            Station(name="B", location="Z", brand=None),
        ])
        session.commit()
        data = _with_companions(**{
            "stations.csv": "name,location,brand\nA,X,New\nB,Y,Petrol\n"
        })
        preview = preview_import(session, data, STANDARD)
        assert [(c.action, c.name, c.location) for c in preview.companion_changes] == [
            ("fill", "B", "Y")
        ]
        commit_import(session, data, "x.zip", VehicleMapping(), STANDARD)
        brands = {(s.name, s.location): s.brand for s in session.scalars(select(Station))}
        assert brands[("A", "X")] == "Old"
        assert brands[("B", "Y")] == "Petrol"
        assert brands[("B", "Z")] is None

    def test_nothing_to_fill_lists_nothing(self, session) -> None:
        session.add(Vehicle(name="Golf", make="VW"))
        session.commit()
        data = _with_companions(**{"vehicles.csv": "name,make\nGolf,Other\n"})
        assert preview_import(session, data, STANDARD).companion_changes == []

    def test_works_with_a_non_standard_preset(self, session) -> None:
        data = _zip({
            "Golf.csv": "fuelup_date,odometer,litres,price,total,partial,tags\n"
                        "2024-01-10,1000,40.000,1.500,,0,Alpha\n",
            "vehicles.csv": "name,make\nGolf,VW\n",
        })
        commit_import(session, data, "x.zip", VehicleMapping(), REFUELS)
        vehicle = session.scalar(select(Vehicle))
        assert (vehicle.name, vehicle.make) == ("Golf", "VW")

    def test_vehicles_only_zip(self, session) -> None:
        data = _zip({"vehicles.csv": "name,make\nGolf,VW\n"})
        commit_import(session, data, "x.zip", VehicleMapping(), STANDARD)
        assert session.scalar(select(Vehicle.make)) == "VW" and count(session, Refuel) == 0

    def test_a_table_named_stations_with_dates_is_a_normal_table(self, session) -> None:
        data = _zip({"stations.csv": "date,odometer_km,fuel_l,price_per_l,type\n"
                                     "2024-01-01,5,40,1.5,refuel\n"})
        preview = preview_import(session, data, STANDARD, mapping=_mapping(session))
        assert preview.companion_changes == []
        assert preview.new_refuels == 1

    def test_backup_is_the_same_path_plus_datapackage(self, session) -> None:
        plain = _backup()
        members = zipfile.ZipFile(io.BytesIO(plain))
        without = _zip({n: members.read(n).decode() for n in members.namelist()
                        if n != "datapackage.json"})
        a = preview_import(session, without, STANDARD)
        b = preview_import(session, plain, STANDARD)
        assert not a.is_backup and b.is_backup
        assert a.companion_changes == b.companion_changes
        assert (a.new_refuels, a.new_expenses, a.vehicle_names) == (
            b.new_refuels, b.new_expenses, b.vehicle_names,
        )
