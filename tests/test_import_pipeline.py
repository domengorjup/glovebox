"""End-to-end pipeline tests (3.2, 3.8) and the native round trip (3.7)."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from sqlalchemy import func, select

from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.config import Settings
from glovebox.exporters.fuelly import export_fuelly
from glovebox.exporters.native import export_native
from glovebox.importers.base import Ambiguity, ImportOptions
from glovebox.importers.pipeline import (
    VehicleMapping,
    available_formats,
    commit_import,
    detect_format,
    list_batches,
    preview_import,
    undo_batch,
)
from glovebox.models import (
    Expense,
    ExpenseCategory,
    ImportBatch,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.services.records import NotFoundError, ValidationError


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def fuelio(fixtures_dir) -> bytes:
    return (fixtures_dir / "fuelio_comma_km.csv").read_bytes()


class TestFormats:
    def test_registered_adapters(self) -> None:
        assert {a.name for a in available_formats()} == {
            "drivvo", "fuelio", "fuelly", "native",
        }  # fmt: skip

    def test_detect_fuelio_backup(self, fuelio) -> None:
        assert detect_format(fuelio) == "fuelio"

    def test_unknown_content(self) -> None:
        assert detect_format(b"hello world") is None

    def test_user_can_override_detection(self, session, fuelio) -> None:
        preview = preview_import(session, fuelio, format="drivvo")
        assert preview.format == "drivvo"
        assert preview.header_mismatch is not None

    def test_unrecognised_file_has_error(self, session) -> None:
        preview = preview_import(session, b"hello world")
        assert preview.errors and preview.new_refuels == 0


class TestPreview:
    def test_preview_does_not_write(self, session, fuelio) -> None:
        preview = preview_import(session, fuelio)
        assert preview.format == "fuelio"
        assert preview.vehicle_names == ["Test Golf"]
        assert (preview.new_refuels, preview.new_expenses) == (4, 3)
        assert (preview.duplicate_refuels, preview.duplicate_expenses) == (0, 0)
        for model in (Refuel, Expense, Vehicle, Station, ImportBatch):
            assert count(session, model) == 0

    def test_unknown_headers_report_found_and_expected(
        self, session, fixtures_dir
    ) -> None:
        data = (fixtures_dir / "drivvo_unknown_headers.csv").read_bytes()
        preview = preview_import(session, data, format="drivvo")
        assert preview.errors
        assert preview.header_mismatch.found[0] == "Datum"
        assert preview.header_mismatch.expected
        with pytest.raises(ValidationError):
            commit_import(session, data, "x.csv", VehicleMapping(), format="drivvo")
        assert count(session, Refuel) == 0

    def test_ambiguous_dates_are_surfaced_then_answered(
        self, session, fixtures_dir
    ) -> None:
        data = (fixtures_dir / "fuelly_import_ambiguous_dates.csv").read_bytes()
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        asked = preview_import(session, data, mapping=mapping)
        assert asked.ambiguities == [Ambiguity.DATE_ORDER]
        answered = preview_import(
            session, data, mapping=mapping, options=ImportOptions(date_order="dmy")
        )
        assert not answered.ambiguities and answered.new_refuels == 2

    def test_units_question_for_fuelly_export(self, session, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelly_export.csv").read_bytes()
        assert preview_import(session, data).ambiguities == [Ambiguity.UNITS]

    def test_file_without_vehicle_names_requires_target(
        self, session, fixtures_dir
    ) -> None:
        data = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
        preview = preview_import(session, data)
        assert preview.errors and preview.vehicle_names == []
        assert preview.needs_vehicle_choice
        with pytest.raises(ValidationError):
            commit_import(session, data, "f.csv", VehicleMapping())

    def test_mapping_to_none_creates_vehicle(self, session, fuelio) -> None:
        mapping = VehicleMapping(by_name={"Test Golf": None})
        commit_import(session, fuelio, "f.csv", mapping)
        assert [v.name for v in session.scalars(select(Vehicle))] == ["Test Golf"]

    def test_mapping_to_none_with_active_same_name_is_an_error(
        self, session, fuelio
    ) -> None:
        _vehicle(session, "Test Golf")
        mapping = VehicleMapping(by_name={"Test Golf": None})
        assert "already exists" in preview_import(session, fuelio, mapping=mapping).errors[0]
        with pytest.raises(ValidationError):
            commit_import(session, fuelio, "f.csv", mapping)

    def test_undo_unknown_batch_raises_not_found(self, session) -> None:
        with pytest.raises(NotFoundError):
            undo_batch(session, 999)

    def test_rows_with_too_few_price_figures_are_skipped(self, session) -> None:
        data = b"fuelup_date,odometer,litres\n2024-01-01,1000,40.0\n"
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        preview = preview_import(session, data, mapping=mapping)
        assert preview.new_refuels == 0 and preview.warnings


class TestCommit:
    def test_commit_writes_everything_in_one_batch(self, session, fuelio) -> None:
        batch = commit_import(session, fuelio, "fuelio.csv", VehicleMapping())
        assert (batch.format, batch.filename) == ("fuelio", "fuelio.csv")
        assert (batch.refuels_imported, batch.expenses_imported) == (4, 3)
        vehicle = session.scalar(select(Vehicle))
        assert vehicle.name == "Test Golf"
        refuels = session.scalars(select(Refuel).order_by(Refuel.date)).all()
        assert {r.import_batch_id for r in refuels} == {batch.id}
        assert refuels[0].source == "fuelio"
        assert refuels[0].vehicle_id == vehicle.id
        assert (refuels[0].litres_milli, refuels[0].total_cents) == (40000, 6000)
        assert refuels[0].price_per_litre_milli == 1500
        assert refuels[0].derived_field is None
        assert count(session, Expense) == 3
        stations = {s.name for s in session.scalars(select(Station))}
        assert stations == {"Alpha Fuel", "Beta Oil Main"}
        assert all(s.brand is None for s in session.scalars(select(Station)))

    def test_missing_figure_is_derived(self, session, fixtures_dir) -> None:
        data = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        commit_import(session, data, "f.csv", mapping)
        first = session.scalars(select(Refuel).order_by(Refuel.date)).first()
        assert first.total_cents == 2991  # 20.5 L x 1.459
        assert first.derived_field.value == "total"
        assert first.station_id is not None  # the tags cell is the station

    def test_map_file_vehicle_to_existing_one(self, session, fuelio) -> None:
        golf = _vehicle(session, "Golf")
        mapping = VehicleMapping(by_name={"Test Golf": golf})
        commit_import(session, fuelio, "f.csv", mapping)
        assert [v.name for v in session.scalars(select(Vehicle))] == ["Golf"]
        assert {r.vehicle_id for r in session.scalars(select(Refuel))} == {golf}

    def test_same_name_vehicle_is_reused(self, session, fuelio) -> None:
        existing = _vehicle(session, "Test Golf")
        commit_import(session, fuelio, "f.csv", VehicleMapping())
        assert count(session, Vehicle) == 1
        assert {r.vehicle_id for r in session.scalars(select(Refuel))} == {existing}

    def test_station_is_reused_across_imports(self, session, fixtures_dir) -> None:
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        commit_import(
            session,
            (fixtures_dir / "drivvo_refuel_en.csv").read_bytes(),
            "a.csv",
            mapping,
        )
        data = b"Date,Odometer,Volume,Total cost,Gas station\n2024-09-01,9000,30,45,Alpha Fuel\n"
        commit_import(session, data, "b.csv", mapping)
        assert count(session, Station) == 2

    def test_failed_commit_leaves_no_trace(
        self, session, fuelio, monkeypatch
    ) -> None:
        from glovebox.importers import pipeline

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(pipeline, "_new_expense", boom)
        with pytest.raises(RuntimeError):
            commit_import(session, fuelio, "f.csv", VehicleMapping())
        for model in (Refuel, Expense, Vehicle, Station, ImportBatch):
            assert count(session, model) == 0


class TestDuplicates:
    def test_reimport_is_a_noop(self, session, fuelio) -> None:
        commit_import(session, fuelio, "f.csv", VehicleMapping())
        second = preview_import(session, fuelio)
        assert (second.new_refuels, second.new_expenses) == (0, 0)
        assert (second.duplicate_refuels, second.duplicate_expenses) == (4, 3)
        batch = commit_import(session, fuelio, "f.csv", VehicleMapping())
        assert (batch.refuels_imported, batch.expenses_imported) == (0, 0)
        assert batch.duplicates_skipped == 7
        assert count(session, Refuel) == 4 and count(session, Expense) == 3
        assert count(session, Vehicle) == 1

    def test_litres_compared_at_two_decimals(self, session) -> None:
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        first = b"fuelup_date,odometer,litres,price\n2024-01-01,1000,40.001,1.5\n"
        second = b"fuelup_date,odometer,litres,price\n2024-01-01,1000,40.004,1.5\n"
        commit_import(session, first, "a.csv", mapping)
        assert preview_import(session, second, mapping=mapping).duplicate_refuels == 1

    def test_duplicates_inside_one_file(self, session) -> None:
        data = (
            b"fuelup_date,odometer,litres,price\n"
            b"2024-01-01,1000,40.0,1.5\n2024-01-01,1000,40.0,1.5\n"
        )
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        preview = preview_import(session, data, mapping=mapping)
        assert (preview.new_refuels, preview.duplicate_refuels) == (1, 1)

    def test_expense_key_includes_category_and_amount(self, session, fixtures_dir) -> None:
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        data = (fixtures_dir / "drivvo_expense_en.csv").read_bytes()
        commit_import(session, data, "e.csv", mapping)
        changed = data.replace(b",5.00,", b",6.00,")
        preview = preview_import(session, changed, mapping=mapping)
        assert (preview.new_expenses, preview.duplicate_expenses) == (1, 1)


class TestUndo:
    def test_undo_removes_batch_and_its_stations(self, session, fuelio) -> None:
        batch = commit_import(session, fuelio, "f.csv", VehicleMapping())
        undo_batch(session, batch.id)
        for model in (Refuel, Expense, Station, ImportBatch):
            assert count(session, model) == 0
        assert count(session, Vehicle) == 1  # vehicles are kept

    def test_undo_keeps_other_batches_and_shared_stations(
        self, session, fixtures_dir
    ) -> None:
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        first = commit_import(
            session, (fixtures_dir / "drivvo_refuel_en.csv").read_bytes(), "a", mapping
        )
        extra = b"Date,Odometer,Volume,Total cost,Gas station\n2024-09-01,9000,30,45,Alpha Fuel\n"
        second = commit_import(session, extra, "b", mapping)
        undo_batch(session, second.id)
        assert count(session, Refuel) == 2
        assert {s.name for s in session.scalars(select(Station))} == {
            "Alpha Fuel", "Beta Oil",
        }
        assert [b.id for b in list_batches(session)] == [first.id]
        undo_batch(session, first.id)
        assert count(session, Station) == 0

    def test_station_used_by_other_records_survives(self, session, fixtures_dir) -> None:
        mapping = VehicleMapping(default_vehicle_id=_vehicle(session))
        batch = commit_import(
            session, (fixtures_dir / "drivvo_refuel_en.csv").read_bytes(), "a", mapping
        )
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
        assert [s.name for s in session.scalars(select(Station))] == ["Alpha Fuel"]
        assert count(session, Refuel) == 1

    def test_undo_unknown_batch(self, session) -> None:
        with pytest.raises(NotFoundError):
            undo_batch(session, 999)

    def test_list_batches_newest_first(self, session, fuelio, fixtures_dir) -> None:
        a = commit_import(session, fuelio, "a", VehicleMapping())
        b = commit_import(
            session,
            (fixtures_dir / "fuelio_semicolon_miles.csv").read_bytes(),
            "b",
            VehicleMapping(),
        )
        assert [x.id for x in list_batches(session)] == [b.id, a.id]


class TestFuellyRoundTrip:
    def test_station_survives_own_fuelly_export(self, session) -> None:
        _populate(session)
        exported = export_fuelly(session)
        files = _fuelly_files(exported)
        other_engine = make_engine()
        run_migrations(other_engine)
        with make_session_factory(other_engine)() as other:
            vehicle = _vehicle(other, "Target")
            for content in files:
                commit_import(
                    other, content, "f.csv", VehicleMapping(default_vehicle_id=vehicle)
                )
            names = {s.name for s in other.scalars(select(Station))}
            used = {
                other.get(Station, r.station_id).name
                for r in other.scalars(select(Refuel))
                if r.station_id
            }
        other_engine.dispose()
        assert {"Alpha", "Beta"} <= names and used == {"Alpha", "Beta"}


def _fuelly_files(export) -> list[bytes]:
    if export.media_type == "text/csv":
        return [export.content]
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        return [archive.read(n) for n in archive.namelist()]


class TestNativeRoundTrip:
    def test_round_trip_into_empty_database(self, session) -> None:
        _populate(session)
        first = export_native(session, Settings())

        other_engine = make_engine()
        run_migrations(other_engine)
        with make_session_factory(other_engine)() as other:
            preview = preview_import(other, first)
            assert preview.format == "native"
            assert (preview.new_refuels, preview.new_expenses) == (3, 2)
            commit_import(other, first, "export.zip", VehicleMapping())
            second = export_native(other, Settings())
        other_engine.dispose()

        assert _tables(first) == _tables(second)

    def test_native_values_restored(self, session) -> None:
        _populate(session)
        data = export_native(session, Settings())
        other_engine = make_engine()
        run_migrations(other_engine)
        with make_session_factory(other_engine)() as other:
            commit_import(other, data, "export.zip", VehicleMapping())
            vehicle = other.scalar(select(Vehicle).where(Vehicle.name == "Golf"))
            assert (vehicle.make, vehicle.plate, vehicle.initial_odometer) == (
                "VW", "LJ-123", 500.0,
            )  # fmt: skip
            station = other.scalar(select(Station).where(Station.name == "Alpha"))
            assert (station.brand, station.location) == ("Brandco", "Ljubljana")
            unused = other.scalar(select(Station).where(Station.name == "Unused"))
            assert unused is not None
            insurance = other.scalar(
                select(Expense).where(Expense.category == ExpenseCategory.INSURANCE)
            )
            assert insurance.coverage_end == date(2024, 12, 31)
            archived = other.scalar(select(Vehicle).where(Vehicle.name == "Old"))
            assert archived.archived
            refuel = other.scalar(select(Refuel).where(Refuel.odometer_km == 1200))
            assert refuel.missed_previous and not refuel.is_full
            assert refuel.time is not None
        other_engine.dispose()

    def test_reimport_native_is_noop(self, session) -> None:
        _populate(session)
        data = export_native(session, Settings())
        preview = preview_import(session, data)
        assert (preview.new_refuels, preview.new_expenses) == (0, 0)
        assert (preview.duplicate_refuels, preview.duplicate_expenses) == (3, 2)

    def test_missing_member_is_an_error(self, session) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("vehicles.csv", "id,name\n1,x\n")
        preview = preview_import(session, buffer.getvalue(), format="native")
        assert preview.errors


# --- helpers ---------------------------------------------------------------


def _vehicle(session, name: str = "Target") -> int:
    vehicle = Vehicle(name=name)
    session.add(vehicle)
    session.commit()
    return vehicle.id


def _populate(session) -> None:
    from datetime import time

    golf = Vehicle(
        name="Golf", make="VW", model="Polo", plate="LJ-123",
        fuel_type="Petrol", initial_odometer=500.0, notes="n, with comma",
    )  # fmt: skip
    old = Vehicle(name="Old", archived=True)
    session.add_all([golf, old])
    alpha = Station(name="Alpha", brand="Brandco", location="Ljubljana")
    beta = Station(name="Beta")
    session.add_all([alpha, beta, Station(name="Unused")])
    session.flush()
    for odo, d, litres, ppl, total, station, full, missed in [
        (1000.0, date(2024, 1, 5), 40000, 1500, 6000, alpha, True, False),
        (1200.0, date(2024, 1, 20), 20500, 1459, 2991, beta, False, True),
        (1500.0, date(2024, 2, 3), 45200, 1459, 6595, None, True, False),
    ]:
        session.add(
            Refuel(
                vehicle_id=golf.id, date=d, odometer_km=odo, litres_milli=litres,
                price_per_litre_milli=ppl, total_cents=total,
                station_id=station.id if station else None, is_full=full,
                missed_previous=missed, notes="note" if station else None,
                time=time(8, 30) if odo == 1200.0 else None,
            )
        )  # fmt: skip
    session.add_all(
        [
            Expense(
                vehicle_id=golf.id, date=date(2024, 1, 1),
                category=ExpenseCategory.INSURANCE, title="Policy",
                amount_cents=40000, coverage_start=date(2024, 1, 1),
                coverage_end=date(2024, 12, 31),
            ),
            Expense(
                vehicle_id=golf.id, date=date(2024, 2, 1), odometer_km=1400.0,
                category=ExpenseCategory.MAINTENANCE, title="Oil change",
                amount_cents=8990, notes="x",
            ),
        ]
    )  # fmt: skip
    session.commit()


def _tables(archive: bytes) -> dict[str, list[dict[str, str]]]:
    """CSV contents of an export, ignoring the manifest and the ``source``
    column (the importer stamps rows with its own source)."""
    import csv

    tables = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in ("vehicles.csv", "stations.csv", "refuels.csv", "expenses.csv"):
            rows = list(csv.DictReader(io.StringIO(zf.read(name).decode())))
            for row in rows:
                row.pop("source", None)
            tables[name] = rows
    return tables
