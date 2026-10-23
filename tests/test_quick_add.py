"""Quick-add refuel page (/quick): form posts, station chips, snackbar, undo."""

from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from glovebox.models import Refuel
from glovebox.services import records
from glovebox.services.records import StationInput


def _post(client: TestClient, path: str, data: dict, status: int = 303):
    response = client.post(path, data=data, follow_redirects=False)
    assert response.status_code == status, response.text[:400]
    return response


def _vehicle(client: TestClient, name: str) -> int:
    _post(client, "/vehicles/new", {"name": name})
    vehicles = client.get("/api/v1/vehicles").json()
    return next(v["id"] for v in vehicles if v["name"] == name)


def _station(engine: Engine, name: str) -> int:
    with Session(engine) as session:
        station = records.create_station(session, StationInput(name=name))
        session.commit()
        return station.id


def _refuel(client, vehicle, station, days_ago, odometer):
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    _post(client, "/refuels/new", {
        "vehicle_id": str(vehicle), "date": day, "odometer_km": str(odometer),
        "litres": "40", "total": "60", "is_full": "1",
        "station_id": str(station) if station else "",
    })  # fmt: skip


def _chips(html: str) -> list[str]:
    block = html.split('aria-label="Station"', 1)[1].split("</div>", 1)[0]
    return re.findall(r'name="station_choice" value="(\w+)"', block)


def _checked(html: str) -> str:
    return re.search(r'name="station_choice" value="(\w+)" checked', html).group(1)


def _quick(vehicle: int, **extra) -> dict:
    data = {"vehicle_id": str(vehicle), "date": date.today().isoformat(),
            "odometer_km": "1500", "litres": "40", "total": "64.9",
            "is_full": "1", "station_choice": "other", "station_id": ""}  # fmt: skip
    data.update(extra)
    return data


def test_quick_creates_refuel_with_time_and_flash(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    _refuel(client, golf, None, 20, 1000)
    html = client.get("/quick").text
    assert "Last: 1,000" in html
    assert "Last: 1,000&nbsp;km" in html or "Last: 1,000 km" in html
    _post(client, "/quick", _quick(golf))
    with Session(engine) as session:
        new = session.scalars(select(Refuel).order_by(Refuel.id.desc())).first()
        assert new.odometer_km == 1500 and new.time is not None
        assert new.total_cents == 6490 and new.price_per_litre_milli > 0
    page = client.get("/").text
    assert "Refuel saved" in page and "40.0 L" in page
    assert "8.00\u00a0L/100\u00a0km" in page  # 40 L over 500 km
    assert "Undo" in page
    assert "Refuel saved" not in client.get("/").text  # one-time


def test_quick_flash_without_consumption_figure(client: TestClient):
    golf = _vehicle(client, "Golf")
    _post(client, "/quick", _quick(golf))
    page = client.get("/").text
    snack = re.search(r'class="snackbar".*?</span>', page, re.S).group(0)
    assert "Refuel saved" in snack and "L/100" not in snack


def test_undo_deletes_the_new_refuel(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    _post(client, "/quick", _quick(golf))
    page = client.get("/").text
    path = re.search(r'action="([^"]*/refuels/\d+/undo)"', page).group(1)
    _post(client, path, {})
    with Session(engine) as session:
        assert session.scalars(select(Refuel)).first() is None
    _post(client, path, {})  # pressed twice: harmless


def test_validation_errors_rerender_quick_page(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    response = _post(client, "/quick", _quick(golf, odometer_km="abc"), 422)
    assert "Odometer" in response.text and 'class="dialog form quick"' in response.text
    assert 'value="40"' in response.text  # entered values kept
    response = _post(client, "/quick", _quick(golf, litres="", total=""), 422)
    assert 'class="dialog form quick"' in response.text
    with Session(engine) as session:
        assert session.scalars(select(Refuel)).first() is None


def test_quick_warning_needs_confirmation(client: TestClient):
    golf = _vehicle(client, "Golf")
    _refuel(client, golf, None, 20, 1000)
    first = _post(client, "/quick", _quick(golf, odometer_km="900"), 200)
    assert "confirm_warnings" in first.text and "Save anyway" in first.text
    _post(client, "/quick", _quick(golf, odometer_km="900", confirm_warnings="1"))


def test_station_chips_recent_then_two_most_frequent(client: TestClient, engine: Engine):
    golf, clio = _vehicle(client, "Golf"), _vehicle(client, "Clio")
    a, b, c, d = (_station(engine, n) for n in ("Alpha", "Bravo", "Charlie", "Delta"))
    # Golf: Bravo x3, Charlie x2, Delta x1, Alpha newest; Clio uses only Delta.
    for days, st in ((60, b), (50, b), (40, b), (30, c), (20, c), (15, d), (1, a)):
        _refuel(client, golf, st, days, 1000 - days)
    _refuel(client, clio, d, 5, 500)
    html = client.get(f"/quick?vehicle={golf}").text
    assert _chips(html) == [str(a), str(b), str(c), "other"]
    assert _checked(html) == str(a)
    clio_html = client.get(f"/quick?vehicle={clio}").text
    assert _chips(clio_html) == [str(d), "other"]


def test_station_chip_choice_and_other(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    a, b = _station(engine, "Alpha"), _station(engine, "Bravo")
    _refuel(client, golf, a, 10, 1000)
    # Chip wins over the (ignored) select value.
    _post(client, "/quick", _quick(golf, station_choice=str(a), station_id=str(b)))
    # "Other" uses the select, here a brand new station.
    _post(client, "/quick", _quick(golf, odometer_km="1600", station_id="__new",
                                   new_station_name="Echo"))
    with Session(engine) as session:
        rows = session.scalars(select(Refuel).order_by(Refuel.id)).all()
        assert rows[1].station_id == a
        assert rows[2].station_id not in (None, a, b)


def test_vehicle_choice_only_with_several_vehicles(client: TestClient):
    golf = _vehicle(client, "Golf")
    assert 'aria-label="Refuel vehicle"' not in client.get("/quick").text
    clio = _vehicle(client, "Clio")
    html = client.get("/quick").text
    assert 'aria-label="Refuel vehicle"' in html
    # app-bar vehicle is preselected
    client.post("/preferences/vehicle", data={"vehicle": str(clio)})
    assert f'name="vehicle_id" value="{clio}"' in client.get("/quick").text
    assert f'name="vehicle_id" value="{golf}"' in client.get(f"/quick?vehicle={golf}").text


def test_quick_defaults_and_chooser(client: TestClient):
    _vehicle(client, "Golf")
    html = client.get("/quick").text
    assert re.search(r'name="is_full"[^>]*checked', html)
    assert "Today, " in html and "autofocus" in html
    assert 'inputmode="numeric"' in html
    assert 'href="/quick"' in client.get("/add").text


def test_quick_without_vehicles_goes_to_timeline(client: TestClient):
    assert client.get("/quick", follow_redirects=False).status_code == 303


# --- quick service and expense ------------------------------------------------


def _entry(vehicle: int, **extra) -> dict:
    data = {"vehicle_id": str(vehicle), "date": date.today().isoformat(),
            "title": "Oil change", "amount": "189.90", "odometer_km": ""}  # fmt: skip
    data.update(extra)
    return data


def _title_chips(html: str, key: str) -> list[str]:
    block = re.search(rf'data-title-chips="{key}".*?</div>', html, re.S).group(0)
    return re.findall(r'data-title="([^"]*)"', block)


def _expense_rows(engine: Engine):
    from glovebox.models import Expense

    with Session(engine) as session:
        return session.scalars(select(Expense).order_by(Expense.id)).all()


def test_quick_service_saves_maintenance_with_snackbar_and_undo(
    client: TestClient, engine: Engine
):
    golf = _vehicle(client, "Golf")
    _refuel(client, golf, None, 10, 1000)
    html = client.get("/quick-service").text
    # The last reading is only a suggestion: placeholder and hint, empty value.
    assert 'name="odometer_km" value=""' in html and 'placeholder="1,000"' in html
    assert "Last: 1,000&nbsp;km on" in html
    # Left empty: saved as estimated, with the existing notice.
    _post(client, "/quick-service", _entry(golf))
    row = _expense_rows(engine)[0]
    assert row.category.value == "maintenance" and row.odometer_estimated
    page = client.get("/").text
    assert "Service saved" in page and "189.90" in page and "Undo" in page
    assert "used the last recorded" in page
    path = re.search(r'action="([^"]*/expenses/\d+/undo)"', page).group(1)
    _post(client, path, {})
    assert _expense_rows(engine) == []
    _post(client, path, {})  # twice: harmless


def test_quick_service_typed_odometer_is_real(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    _refuel(client, golf, None, 10, 1000)
    _post(client, "/quick-service", _entry(golf, odometer_km="1200"))
    row = _expense_rows(engine)[0]
    assert row.odometer_km == 1200 and not row.odometer_estimated


def test_quick_service_title_chips(client: TestClient):
    golf = _vehicle(client, "Golf")
    assert _title_chips(client.get("/quick-service").text, "maintenance") == ["Regular service"]
    titles = ("Regular service", "Brake pads", "Tyres", "Wipers", "Oil", "Brake pads")
    for age, title in zip(range(60, 0, -10), titles):
        day = (date.today() - timedelta(days=age)).isoformat()
        _post(client, "/quick-service", _entry(golf, title=title, date=day))
    chips = _title_chips(client.get("/quick-service").text, "maintenance")
    # Fixed first, then the newest distinct titles; "Regular service" not repeated.
    assert chips == ["Regular service", "Brake pads", "Oil", "Wipers"]


def test_quick_expense_types_chips_and_coverage(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    _post(client, "/quick-expense", _entry(
        golf, category="insurance", title="Insurance 2026", amount="365",
        coverage_start="2026-01-01", coverage_end="2026-12-31"))
    _post(client, "/quick-expense", _entry(golf, category="other", title="Parking"))
    html = client.get("/quick-expense").text
    assert _title_chips(html, "insurance") == ["Insurance 2026"]
    assert _title_chips(html, "other") == ["Parking"]
    assert _title_chips(html, "registration") == []
    assert "maintenance" not in re.findall(r'name="category" value="(\w+)"', html)
    row = _expense_rows(engine)[0]
    assert row.coverage_end == date(2026, 12, 31)
    assert "Expense saved" in client.get("/").text


def test_quick_expense_errors_rerender(client: TestClient, engine: Engine):
    golf = _vehicle(client, "Golf")
    response = _post(client, "/quick-expense", _entry(golf, category="other", title=""), 422)
    assert "Title is required" in response.text and "data-quick-kind" in response.text
    response = _post(client, "/quick-expense", _entry(
        golf, category="other", coverage_start="2026-01-01"), 422)
    assert "Coverage" in response.text
    assert _expense_rows(engine) == []


def test_quick_pages_vehicle_choice_and_chooser(client: TestClient):
    _vehicle(client, "Golf")
    html = client.get("/quick-expense").text
    assert 'aria-label="Vehicle choice"' not in html
    _vehicle(client, "Clio")
    assert 'aria-label="Vehicle choice"' in client.get("/quick-service").text
    chooser = client.get("/add").text
    assert 'href="/quick-service"' in chooser and 'href="/quick-expense"' in chooser


def test_full_add_forms_suggest_the_last_odometer_only(client: TestClient):
    golf = _vehicle(client, "Golf")
    assert 'placeholder="1,000"' not in client.get("/expenses/new").text
    _refuel(client, golf, None, 10, 1000)
    for path in ("/expenses/new", "/expenses/new?kind=service"):
        html = client.get(path).text
        assert 'name="odometer_km" value=""' in html and 'placeholder="1,000"' in html
        assert "Last recorded: 1,000" in html and "data-placeholder" in html
    # Editing shows no suggestion (an empty field there re-estimates).
    _post(client, "/expenses/new", {"vehicle_id": str(golf), "category": "other",
          "title": "x", "amount": "5", "date": date.today().isoformat(), "odometer_km": "1100"})
    assert 'placeholder="1,000"' not in client.get("/expenses/1/edit").text


def _set_fuel(client: TestClient, vehicle: int, fuel: str) -> None:
    _post(client, f"/vehicles/{vehicle}/edit", {"name": "Car", "fuel_type": fuel})


def test_quick_shows_fuel_type_of_chosen_vehicle(client: TestClient):
    diesel = _vehicle(client, "Car")
    _set_fuel(client, diesel, "Diesel")
    plain = _vehicle(client, "Bike")
    assert "· Diesel" in client.get(f"/quick?vehicle={diesel}").text
    assert 'class="fuel-type"' not in client.get(f"/quick?vehicle={plain}").text


def test_full_form_embeds_fuel_types_per_vehicle(client: TestClient):
    diesel = _vehicle(client, "Car")
    _set_fuel(client, diesel, "Diesel")
    plain = _vehicle(client, "Bike")
    html = client.get(f"/refuels/new?vehicle={diesel}").text
    assert f'data-fuel-types=\'{{"{diesel}": "Diesel"}}\'' in html
    assert "· Diesel</span>" in html
    html = client.get(f"/refuels/new?vehicle={plain}").text
    assert "· Diesel</span>" not in html
    assert "data-fuel-types" in html
