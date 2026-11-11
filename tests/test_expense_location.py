"""Optional location on expenses (change add-expense-location)."""

from __future__ import annotations

import csv
import io
import re
from datetime import date

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from glovebox.config import Settings
from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.exporters.backup import export_backup
from glovebox.exporters.csv_export import NothingToExport, export_csv
from glovebox.importers import engine as import_engine
from glovebox.importers.pipeline import VehicleMapping, commit_import
from glovebox.importers.presets import load_preset, shipped_presets
from glovebox.models import Expense, ExpenseCategory, Vehicle
from glovebox.services import records
from glovebox.services.records import ExpenseInput, ValidationError
from glovebox.standard import RECORD_FIELDS

from test_migration_0003 import _config

STANDARD = import_engine.standard_preset()
M = ExpenseCategory.MAINTENANCE


def _vehicle(session: Session, name: str = "Golf") -> int:
    vehicle = Vehicle(name=name, archived=False)
    session.add(vehicle)
    session.flush()
    return vehicle.id


def _expense(session, vid, day, location, category=M, title="Job") -> Expense:
    item = Expense(
        vehicle_id=vid, date=day, category=category, title=title, amount_cents=1000,
        location=location,
    )
    session.add(item)
    session.flush()
    return item


# --- migration and records service ------------------------------------------------


def test_migration_0008_adds_a_nullable_column_old_rows_are_null() -> None:
    engine = make_engine()
    run_migrations(engine)
    with make_session_factory(engine)() as s:
        vid = _vehicle(s)
        _expense(s, vid, date(2026, 1, 1), "Garage")
        s.commit()
    with engine.begin() as connection:
        command.downgrade(_config(connection), "0007")
    assert "location" not in {c["name"] for c in inspect(engine).get_columns("expense")}
    with engine.begin() as connection:
        command.upgrade(_config(connection), "0008")
    columns = {c["name"]: c for c in inspect(engine).get_columns("expense")}
    assert columns["location"]["nullable"] and columns["location"]["type"].length == 200
    with make_session_factory(engine)() as s:
        assert s.scalars(select(Expense.location)).all() == [None]
    engine.dispose()


def _input(vid: int, **kw) -> ExpenseInput:
    return ExpenseInput(
        vehicle_id=vid, date=date(2026, 3, 1), category=M, amount_cents=500, title="x", **kw
    )


def test_location_is_stripped_blank_is_null_and_long_is_rejected(session: Session) -> None:
    vid = _vehicle(session)
    assert records.create_expense(session, _input(vid, location="  Avto Celje ")).location == "Avto Celje"
    assert records.create_expense(session, _input(vid, location="   ")).location is None
    assert records.create_expense(session, _input(vid, location="x" * 200)).location == "x" * 200
    with pytest.raises(ValidationError, match="Location"):
        records.create_expense(session, _input(vid, location="x" * 201))


def test_recent_locations(session: Session) -> None:
    golf, polo = _vehicle(session), _vehicle(session, "Polo")
    _expense(session, golf, date(2026, 1, 1), "Old Garage")
    _expense(session, polo, date(2026, 2, 1), "avto celje")
    _expense(session, golf, date(2026, 3, 1), "Avto Celje")  # newest spelling wins
    _expense(session, golf, date(2026, 3, 1), None)
    _expense(session, golf, date(2026, 4, 1), "Insurer Ltd", category=ExpenseCategory.INSURANCE)
    assert records.recent_locations(session, M) == ["Avto Celje", "Old Garage"]
    assert records.recent_locations(session, ExpenseCategory.INSURANCE) == ["Insurer Ltd"]
    assert records.recent_locations(session, ExpenseCategory.OTHER) == []
    assert records.recent_locations(session, M, limit=1) == ["Avto Celje"]


def test_duplicate_key_ignores_the_location(session: Session) -> None:
    vid = _vehicle(session)
    csv_text = (
        "type,vehicle,date,total,title,location\n"
        "expense,Golf,2026-01-01,5,a,Garage A\n"
    ).encode()
    first = commit_import(session, csv_text, "a.csv", VehicleMapping(by_name={"Golf": vid}), STANDARD)
    assert first.expenses_imported == 1
    with pytest.raises(ValidationError, match="Nothing new"):  # the same payment, new place
        commit_import(
            session, csv_text.replace(b"Garage A", b"Garage B"), "b.csv",
            VehicleMapping(by_name={"Golf": vid}), STANDARD,
        )
    assert session.scalars(select(Expense.location)).all() == ["Garage A"]


# --- standard format, export, backup ---------------------------------------------------


def test_location_follows_title_in_the_standard_format() -> None:
    names = [f.name for f in RECORD_FIELDS]
    assert names[names.index("title") + 1] == "location"


def _preset(text: str):
    return load_preset(text, id="test", shipped=True)


STANDARD_TOML = "name = \"Standard\"\nexport = true\n[fields]\n" + "".join(
    f'{f.name} = {{ column = "{f.name}" }}\n' for f in RECORD_FIELDS
)
NO_LOCATION_TOML = "name = \"No place\"\nexport = true\n[fields]\n" + "".join(
    f'{f.name} = {{ column = "{f.name}" }}\n' for f in RECORD_FIELDS if f.name != "location"
)


def test_standard_and_custom_export(session: Session) -> None:
    vid = _vehicle(session)
    _expense(session, vid, date(2026, 1, 1), "Example Garage")
    _expense(session, vid, date(2026, 1, 2), None)
    data, _ = export_csv(session, Settings(), _preset(STANDARD_TOML))
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert [r["location"] for r in rows] == ["Example Garage", ""]
    data, _ = export_csv(session, Settings(), _preset(NO_LOCATION_TOML))
    assert "location" not in data.decode().splitlines()[0].split(",")


def test_fuelly_export_is_unchanged(session: Session) -> None:
    fuelly = next(p for p in shipped_presets() if p.id == "fuelly-metric")
    vid = _vehicle(session)
    _expense(session, vid, date(2026, 1, 1), "Example Garage")
    with pytest.raises(NothingToExport):  # refuel-only format: expenses are not written
        export_csv(session, Settings(), fuelly)


def test_backup_round_trip_keeps_locations(session: Session) -> None:
    import json
    import zipfile

    vid = _vehicle(session)
    _expense(session, vid, date(2026, 1, 1), "Example Garage")
    _expense(session, vid, date(2026, 2, 1), "Example Insurer", category=ExpenseCategory.INSURANCE,
             title="Policy")
    session.commit()
    backup = export_backup(session, Settings())
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        records_csv = archive.read("records.csv").decode()
        descriptor = json.loads(archive.read("datapackage.json"))
    assert "location" in records_csv.splitlines()[0]
    fields = next(r for r in descriptor["resources"] if r["name"] == "records")["schema"]["fields"]
    assert "location" in [f["name"] for f in fields]

    fresh_engine = make_engine()
    run_migrations(fresh_engine)
    with make_session_factory(fresh_engine)() as fresh:
        commit_import(fresh, backup, "b.zip", VehicleMapping())
        got = {e.title: e.location for e in fresh.scalars(select(Expense))}
        again = export_backup(fresh, Settings())
    fresh_engine.dispose()
    assert sorted(got.values()) == ["Example Garage", "Example Insurer"]
    with zipfile.ZipFile(io.BytesIO(again)) as archive:
        assert archive.read("records.csv").decode() == records_csv


# --- import ------------------------------------------------------------------------------


def test_import_stores_and_truncates_the_location(session: Session) -> None:
    _vehicle(session)
    data = (
        "type,vehicle,date,total,title,location\n"
        f"expense,Golf,2026-01-01,5,a,{'y' * 250}\n"
        "expense,Golf,2026-01-02,6,b,\n"
    ).encode()
    commit_import(session, data, "a.csv", VehicleMapping(by_name={"Golf": 1}), STANDARD)
    found = {e.title: e.location for e in session.scalars(select(Expense))}
    assert found == {"a": "y" * 200, "b": None}


def test_drivvo_presets_import_the_location(fixtures_dir) -> None:
    from glovebox.importers.base import Answers

    def run(name, preset_id):
        chosen = next(p for p in shipped_presets() if p.id == preset_id)
        source = import_engine.read_file((fixtures_dir / name).read_bytes(), chosen)
        return import_engine.apply(chosen, source, Answers())

    expenses = run("drivvo_en_sections.csv", "drivvo-expenses").expenses
    assert [e.location for e in expenses if e.title == "Insurance"] == ["Example Insurer"]
    services = run("drivvo_en_sections.csv", "drivvo-services").expenses
    assert {e.location for e in services} == {"Example Garage"}
    assert services[0].notes == "Also: Oil Filter"  # folded item keeps the first item's place
    web = run("drivvo_web_sections.csv", "drivvo-services").expenses
    assert "Example Garage" in {e.location for e in web}


# --- web forms ---------------------------------------------------------------------------


@pytest.fixture
def car(client: TestClient) -> int:
    client.post("/vehicles/new", data={"name": "Golf"}, follow_redirects=False)
    return 1


def _form(**extra) -> dict:
    data = {"vehicle_id": "1", "date": "2026-10-20", "category": "maintenance",
            "title": "Oil change", "amount": "80", "odometer_km": "", "location": ""}
    data.update(extra)
    return data


def _locations(engine: Engine) -> list[str | None]:
    with make_session_factory(engine)() as s:
        return list(s.scalars(select(Expense.location).order_by(Expense.id)))


def test_full_service_form_stores_shows_edits_and_clears_the_location(
    client: TestClient, car: int, engine: Engine
) -> None:
    html = client.get("/expenses/new?kind=service").text
    assert re.search(r'<input[^>]*name="location"[^>]*list="location-options-maintenance"', html)
    assert client.post("/expenses/new", data=_form(location=" Example Garage "),
                       follow_redirects=False).status_code == 303
    assert _locations(engine) == ["Example Garage"]
    assert "Example Garage" in client.get("/").text
    assert 'name="location" value="Example Garage"' in client.get("/expenses/1/edit").text
    client.post("/expenses/1/edit", data=_form(location="Other Garage"), follow_redirects=False)
    assert _locations(engine) == ["Other Garage"]
    client.post("/expenses/1/edit", data=_form(location=""), follow_redirects=False)
    assert _locations(engine) == [None]


def test_quick_pages_show_location_after_odometer_and_save_it(
    client: TestClient, car: int, engine: Engine
) -> None:
    for path in ("/quick-service", "/quick-expense"):
        html = client.get(path).text
        order = [html.index(f'name="{n}"') for n in ("title", "amount", "odometer_km", "location")]
        assert order == sorted(order), path
        assert html.index('name="location"') < html.index("q-open-more")  # not under More
    client.post("/quick-service", data=_form(location="Example Garage"), follow_redirects=False)
    client.post("/quick-expense", data=_form(category="insurance", location="Example Insurer"),
                follow_redirects=False)
    assert _locations(engine) == ["Example Garage", "Example Insurer"]


def test_datalists_offer_earlier_values_of_the_same_category_only(
    client: TestClient, car: int
) -> None:
    client.post("/vehicles/new", data={"name": "Polo"}, follow_redirects=False)
    for day, vid, cat, loc in (
        ("2026-01-01", "1", "maintenance", "Old Garage"),
        ("2026-02-01", "2", "maintenance", "Garage Two"),
        ("2026-02-01", "2", "maintenance", "garage two"),
        ("2026-03-01", "1", "insurance", "Example Insurer"),
    ):
        client.post("/expenses/new", data=_form(vehicle_id=vid, date=day, category=cat,
                                               location=loc), follow_redirects=False)
    html = client.get("/quick-service?vehicle=1").text

    def options(category: str) -> list[str]:
        block = re.search(rf'<datalist id="location-options-{category}">(.*?)</datalist>', html, re.S)
        return re.findall(r'value="([^"]*)"', block.group(1))

    assert options("maintenance") == ["garage two", "Old Garage"]
    assert options("insurance") == ["Example Insurer"]
    assert options("other") == []


def test_too_long_location_is_rejected_with_a_message(
    client: TestClient, car: int, engine: Engine
) -> None:
    for path in ("/expenses/new", "/quick-service"):
        response = client.post(path, data=_form(location="x" * 201))
        assert response.status_code == 422 and "Location must be at most 200" in response.text
    assert _locations(engine) == []


def test_insurance_and_registration_accept_a_location(
    client: TestClient, car: int, engine: Engine
) -> None:
    for category, place in (("insurance", "Insurer"), ("registration", "Test centre")):
        client.post("/expenses/new", data=_form(category=category, location=place),
                    follow_redirects=False)
    assert _locations(engine) == ["Insurer", "Test centre"]


def test_timeline_meta_line(client: TestClient, car: int) -> None:
    client.post("/expenses/new", data=_form(location="Example Garage", notes="Winter tyres"),
                follow_redirects=False)
    client.post("/expenses/new", data=_form(
        category="insurance", title="Policy", location="Example Insurer",
        coverage_start="2026-01-01", coverage_end="2026-12-31"), follow_redirects=False)
    page = client.get("/").text
    assert "Example Garage · Winter tyres" in page
    assert "Insurance · Example Insurer · covers 2026-01-01" in page
