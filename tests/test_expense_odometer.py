"""Odometer default for expenses and services (change expense-odometer-default)."""

from __future__ import annotations

import re
from datetime import date

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from glovebox.config import Settings
from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.exporters.backup import export_backup
from glovebox.importers import engine as import_engine
from glovebox.importers.pipeline import VehicleMapping, commit_import, preview_import
from glovebox.models import Expense, ExpenseCategory, Refuel, Vehicle
from glovebox.services import records
from glovebox.services.stats import StatsFilter, cost_per_km, vehicle_summary

from test_migration_0003 import _config

STANDARD = import_engine.standard_preset()


def _vehicle(session: Session, initial: float | None = None) -> int:
    vehicle = Vehicle(name="Golf", archived=False, initial_odometer=initial)
    session.add(vehicle)
    session.flush()
    return vehicle.id


def _refuel(session: Session, vid: int, odo: float, day: date) -> None:
    session.add(Refuel(
        vehicle_id=vid, date=day, odometer_km=odo, litres_milli=40000,
        price_per_litre_milli=1500, total_cents=6000,
    ))
    session.flush()


def _expense(session, vid, day, odo=None, estimated=False, title="x"):
    item = Expense(
        vehicle_id=vid, date=day, category=ExpenseCategory.MAINTENANCE, title=title,
        amount_cents=1000, odometer_km=odo, odometer_estimated=estimated,
    )
    session.add(item)
    session.flush()
    return item


# --- last known odometer ------------------------------------------------------


def test_last_known_uses_real_readings_up_to_the_date(session: Session) -> None:
    vid = _vehicle(session, initial=1000)
    _refuel(session, vid, 5000, date(2026, 1, 10))
    _expense(session, vid, date(2026, 2, 1), odo=5200)
    _refuel(session, vid, 9000, date(2026, 6, 1))
    last = records.last_known_odometer(session, vid, date(2026, 3, 1))
    assert (last.km, last.date) == (5200, date(2026, 2, 1))


def test_last_known_ignores_estimates_and_falls_back_to_initial(session: Session) -> None:
    vid = _vehicle(session, initial=1000)
    _expense(session, vid, date(2026, 2, 1), odo=7777, estimated=True)
    last = records.last_known_odometer(session, vid, date(2026, 3, 1))
    assert (last.km, last.date) == (1000, None)
    assert records.last_known_odometer(session, _vehicle_without(session), date(2026, 3, 1)) is None


def _vehicle_without(session: Session) -> int:
    vehicle = Vehicle(name="Other", archived=False)
    session.add(vehicle)
    session.flush()
    return vehicle.id


# --- web form -------------------------------------------------------------------


@pytest.fixture
def car(client: TestClient) -> int:
    client.post("/vehicles/new", data={"name": "Golf"}, follow_redirects=False)
    return 1


def _post_refuel(client: TestClient, odo: str, day: str = "2026-10-18") -> None:
    response = client.post(
        "/refuels/new",
        data={"vehicle_id": "1", "date": day, "odometer_km": odo,
              "litres": "40", "total": "60"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]


def _post_service(client: TestClient, odo: str, day: str = "2026-10-20"):
    return client.post(
        "/expenses/new",
        data={"vehicle_id": "1", "date": day, "category": "maintenance",
              "title": "Oil change", "amount": "80", "odometer_km": odo},
        follow_redirects=False,
    )


def test_refuel_form_requires_the_odometer(client: TestClient, car: int) -> None:
    html = client.get("/refuels/new").text
    assert re.search(r'<input[^>]*name="odometer_km"[^>]*required', html)


def test_refuel_without_odometer_is_rejected(client: TestClient, car: int, engine: Engine) -> None:
    response = client.post(
        "/refuels/new",
        data={"vehicle_id": "1", "date": "2026-10-18", "odometer_km": "",
              "litres": "40", "total": "60"},
    )
    assert response.status_code == 422 and "Odometer is required" in response.text
    with make_session_factory(engine)() as s:
        assert s.scalar(select(Refuel.id)) is None


def test_expense_form_shows_the_last_recorded_odometer(client: TestClient, car: int) -> None:
    _post_refuel(client, "104163")
    html = client.get("/expenses/new?kind=service").text
    assert "Last recorded: 104,163&nbsp;km" in html


def test_empty_odometer_is_estimated_and_warned(
    client: TestClient, car: int, engine: Engine
) -> None:
    _post_refuel(client, "104163")
    response = _post_service(client, "")
    assert response.status_code == 303
    page = client.get("/").text
    assert "Odometer not entered" in page and "104,163" in page
    assert "≈" in page and "104,163" in page.split("≈", 1)[1][:30]
    with make_session_factory(engine)() as s:
        item = s.scalars(select(Expense)).one()
        assert (item.odometer_km, item.odometer_estimated) == (104163, True)
    assert "Odometer not entered" not in client.get("/").text  # shown once


def test_typed_odometer_is_real_and_not_warned(
    client: TestClient, car: int, engine: Engine
) -> None:
    _post_refuel(client, "104163")
    _post_service(client, "104500")
    page = client.get("/").text
    assert "Odometer not entered" not in page and "≈" not in page
    with make_session_factory(engine)() as s:
        item = s.scalars(select(Expense)).one()
        assert (item.odometer_km, item.odometer_estimated) == (104500, False)


def test_no_earlier_reading_saves_empty_with_gentle_warning(
    client: TestClient, car: int, engine: Engine
) -> None:
    assert "No earlier reading" in client.get("/expenses/new").text
    _post_service(client, "")
    assert "recommended" in client.get("/").text
    with make_session_factory(engine)() as s:
        item = s.scalars(select(Expense)).one()
        assert (item.odometer_km, item.odometer_estimated) == (None, False)


def test_estimates_do_not_feed_the_next_estimate(
    client: TestClient, car: int, engine: Engine
) -> None:
    _post_refuel(client, "100000", "2026-10-01")
    _post_service(client, "", "2026-10-05")
    _post_service(client, "", "2026-10-06")
    with make_session_factory(engine)() as s:
        assert [e.odometer_km for e in s.scalars(select(Expense))] == [100000, 100000]


def test_editing_an_estimate_shows_the_field_empty(client: TestClient, car: int) -> None:
    _post_refuel(client, "104163")
    _post_service(client, "")
    html = client.get("/expenses/1/edit").text
    assert re.search(r'name="odometer_km"[^>]*value=""|name="odometer_km"(?![^>]*value=)', html)
    assert "is an estimate" in html
    assert _post_edit(client, "104400").status_code == 303


def _post_edit(client: TestClient, odo: str):
    return client.post(
        "/expenses/1/edit",
        data={"vehicle_id": "1", "date": "2026-10-20", "category": "maintenance",
              "title": "Oil change", "amount": "80", "odometer_km": odo},
        follow_redirects=False,
    )


# --- statistics -----------------------------------------------------------------


def test_estimated_odometers_do_not_stretch_the_distance(session: Session) -> None:
    vid = _vehicle(session)
    _refuel(session, vid, 10000, date(2026, 1, 1))
    _refuel(session, vid, 15000, date(2026, 2, 1))
    _expense(session, vid, date(2026, 3, 1), odo=15000, estimated=True)
    _expense(session, vid, date(2026, 1, 15), odo=9000, estimated=True)  # stale
    _expense(session, vid, date(2026, 3, 2), odo=99999, estimated=True)
    assert cost_per_km(session, StatsFilter(vehicles=(vid,))).distance_km == 5000
    assert vehicle_summary(session, vid, date(2026, 3, 5)).last_odometer_km == 15000


def test_entered_expense_odometer_still_counts(session: Session) -> None:
    vid = _vehicle(session)
    _refuel(session, vid, 10000, date(2026, 1, 1))
    _expense(session, vid, date(2026, 3, 1), odo=16000)
    assert cost_per_km(session, StatsFilter(vehicles=(vid,))).distance_km == 6000


# --- import and round trip --------------------------------------------------------


NO_ODO = (
    b"type,vehicle,date,odometer_km,total,title\n"
    b"expense,Golf,2026-01-01,,5,a\n"
    b"expense,Golf,2026-01-02,,6,b\n"
    b"expense,Golf,2026-01-03,1000,7,c\n"
)


def test_preview_counts_expenses_without_odometer(session: Session) -> None:
    preview = preview_import(session, NO_ODO, STANDARD, mapping=VehicleMapping())
    assert "2 expenses have no odometer." in preview.warnings


def test_import_does_not_invent_odometers(session: Session) -> None:
    _vehicle(session)
    _refuel(session, 1, 5000, date(2025, 12, 1))
    commit_import(session, NO_ODO, "a.csv", VehicleMapping(by_name={"Golf": 1}), STANDARD)
    rows = list(session.scalars(select(Expense).order_by(Expense.date)))
    assert [e.odometer_km for e in rows] == [None, None, 1000]
    assert not any(e.odometer_estimated for e in rows)


def test_refuel_row_without_odometer_is_a_row_error(session: Session) -> None:
    data = b"type,vehicle,date,odometer_km,fuel_l,total\nrefuel,Golf,2026-01-01,,40,60\n"
    preview = preview_import(session, data, STANDARD, mapping=VehicleMapping())
    assert [(e.field, e.message) for e in preview.row_errors] == [
        ("odometer_km", "The odometer reading is missing.")
    ]
    assert preview.new_refuels == 0


def test_estimated_flag_round_trips_and_needs_a_value(session: Session) -> None:
    vid = _vehicle(session)
    _refuel(session, vid, 5000, date(2026, 1, 1))
    _expense(session, vid, date(2026, 1, 5), odo=5000, estimated=True, title="est")
    _expense(session, vid, date(2026, 1, 6), odo=5100, title="real")
    session.commit()
    backup = export_backup(session, Settings())
    fresh_engine = make_engine()
    run_migrations(fresh_engine)
    with make_session_factory(fresh_engine)() as fresh:
        commit_import(fresh, backup, "b.zip", VehicleMapping())
        got = {e.title: e.odometer_estimated for e in fresh.scalars(select(Expense))}
    fresh_engine.dispose()
    assert got == {"est": True, "real": False}

    bogus = b"type,vehicle,date,odometer_km,odometer_estimated,total,title\n" \
            b"expense,Golf,2026-01-01,,true,5,a\n"
    preview = preview_import(session, bogus, STANDARD, mapping=VehicleMapping(by_name={"Golf": vid}))
    assert preview.new_expenses == 1
    parsed = import_engine.apply(STANDARD, import_engine.read_file(bogus, STANDARD), None)
    assert parsed.expenses[0].odometer_estimated is False


# --- migration --------------------------------------------------------------------


def test_migration_0004_adds_the_flag_with_default_false() -> None:
    engine = make_engine()
    run_migrations(engine)
    columns = {c["name"]: c for c in inspect(engine).get_columns("expense")}
    assert "odometer_estimated" in columns and not columns["odometer_estimated"]["nullable"]
    with engine.begin() as connection:
        command.downgrade(_config(connection), "0003")
    assert "odometer_estimated" not in {c["name"] for c in inspect(engine).get_columns("expense")}
    engine.dispose()


# --- hint follows the form's vehicle and date ---------------------------------------


def test_odometer_steps_follow_the_running_maximum(session: Session) -> None:
    vid = _vehicle(session, initial=1000)
    _refuel(session, vid, 5000, date(2026, 1, 10))
    _expense(session, vid, date(2026, 1, 20), odo=4000)  # lower: no step
    _expense(session, vid, date(2026, 2, 1), odo=5200)
    _expense(session, vid, date(2026, 2, 5), odo=9999, estimated=True)  # ignored
    steps = records.odometer_steps(session, [vid])[vid]
    assert steps == [(None, 1000), (date(2026, 1, 10), 5000), (date(2026, 2, 1), 5200)]
    for day in (date(2026, 1, 5), date(2026, 1, 15), date(2026, 3, 1)):
        on = [s for s in steps if s[0] is None or s[0] <= day][-1]
        assert on[1] == records.last_known_odometer(session, vid, day).km


def test_form_embeds_the_readings_of_every_vehicle(client: TestClient, car: int) -> None:
    import html as html_lib
    import json

    client.post("/vehicles/new", data={"name": "Polo", "initial_odometer": "500"},
                follow_redirects=False)
    _post_refuel(client, "104163")
    page = client.get("/expenses/new?kind=service").text
    raw = re.search(r"data-steps='([^']*)'", page).group(1)
    steps = json.loads(html_lib.unescape(raw))
    assert steps["1"] == [["2026-10-18", 104163.0]]
    assert steps["2"] == [["", 500.0]]
    assert 'id="i-vehicle_id"' in page and 'id="i-date"' in page
