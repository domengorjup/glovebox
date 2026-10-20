"""
End-to-end tests through the web forms and the real pipeline (no monkeypatching).

Data is created with the same form posts a browser sends; numbers shown by the
dashboard are compared with values computed by hand (see ``_build_scenario``).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from autotracker.app import create_app
from autotracker.config import Settings
from autotracker.db import make_engine, run_migrations
from autotracker.models import Expense, ImportBatch, Refuel, Station, Vehicle

PREFIX = "/api/hassio_ingress/e2etoken"

# --- HTML helpers -----------------------------------------------------------


def _tile(html: str, header: str) -> str:
    """Text of the dashboard tile with the given header."""
    match = re.search(
        rf"<header>{re.escape(header)}</header>\s*<strong>(.*?)</strong>", html, re.S
    )
    assert match, f"tile {header!r} not found"
    return match.group(1).strip()


def _table_rows(html: str, heading: str) -> list[list[str]]:
    """Cell texts of each body row of the table following ``<h2>heading</h2>``."""
    section = html.split(f"<h2>{heading}</h2>", 1)[1]
    table = re.search(r"<tbody>(.*?)</tbody>", section, re.S).group(1)
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)
    return [
        [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        for r in rows
    ]


class _Form(HTMLParser):
    """Collects the fields a browser would submit for the first import form."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[tuple[str, str]] = []
        self._select: str | None = None
        self._options: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "input":
            kind, name = a.get("type", "text"), a.get("name")
            if name and kind == "hidden":
                self.fields.append((name, a.get("value", "")))
            elif name and kind == "radio" and "checked" in a:
                self.fields.append((name, a.get("value", "")))
        elif tag == "select":
            self._select, self._options = a.get("name"), []
        elif tag == "option" and self._select:
            self._options.append((a.get("value", ""), "selected" in a))

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select:
            chosen = next((v for v, sel in self._options if sel), None)
            if chosen is None and self._options:
                chosen = self._options[0][0]
            self.fields.append((self._select, chosen or ""))
            self._select = None


def _form_fields(html: str) -> list[tuple[str, str]]:
    parser = _Form()
    parser.feed(html)
    return parser.fields


def _as_form(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Repeated names kept as lists (httpx form-encodes dicts, not pair lists)."""
    form: dict[str, list[str]] = {}
    for key, value in pairs:
        form.setdefault(key, []).append(value)
    return form


# --- Data entry through forms ----------------------------------------------


def _post(client: TestClient, path: str, data: dict) -> None:
    response = client.post(path, data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[:500]


def _vehicle_id(client: TestClient, name: str) -> int:
    vehicles = client.get("/api/v1/vehicles").json()
    return next(v["id"] for v in vehicles if v["name"] == name)


def _station_id(client: TestClient, name: str) -> int:
    html = client.get("/refuels/new").text
    match = re.search(rf'<option value="(\d+)"[^>]*>{re.escape(name)}\b', html)
    assert match, f"station {name!r} not offered in the refuel form"
    return int(match.group(1))


def _add_refuel(client: TestClient, vehicle_id: int, day: date, odometer: int, **kw):
    data = {
        "vehicle_id": str(vehicle_id), "date": day.isoformat(),
        "odometer_km": str(odometer), "is_full": "1",
    }  # fmt: skip
    data.update({k: str(v) for k, v in kw.items() if v not in (None, False)})
    if kw.get("is_full") is False:
        data.pop("is_full")
    _post(client, "/refuels/new", data)


def _add_expense(client: TestClient, vehicle_id: int, day: date, **kw):
    data = {"vehicle_id": str(vehicle_id), "date": day.isoformat()}
    data.update({k: str(v) for k, v in kw.items()})
    _post(client, "/expenses/new", data)


def _build_scenario(client: TestClient) -> int:
    """
    Create the hand-computed 2025 data set; return the vehicle id.

    Refuels (odometer, litres, EUR/L, total, station, full):
      R1 2025-01-10  10000  40.0  1.500  60.00  Alpha  full
      R2 2025-02-10  10500  30.0  1.600  48.00  Beta   full   (total typed)
      R3 2025-03-10  11000  35.0  1.400  49.00  Alpha  full   (price typed)
      R4 2025-04-10  11300  15.0  1.500  22.50  Alpha  partial
      R5 2025-05-10  11800  20.0  1.500  30.00  Alpha  full
    Expenses: insurance 365.00 covering all of 2025 (1.00 per day) and a
    100.00 service without coverage dates at odometer 11100 on 2025-03-15.
    """
    _post(client, "/vehicles/new", {"name": "Golf", "make": "VW", "model": "Golf"})
    vid = _vehicle_id(client, "Golf")
    _add_refuel(client, vid, date(2025, 1, 10), 10000, litres="40",
                price_per_litre="1.5", new_station_name="Alpha")  # fmt: skip
    _add_refuel(client, vid, date(2025, 2, 10), 10500, litres="30", total="48.00",
                new_station_name="Beta")  # fmt: skip
    alpha = _station_id(client, "Alpha")
    _add_refuel(client, vid, date(2025, 3, 10), 11000, litres="35",
                price_per_litre="1.4", station_id=alpha)  # fmt: skip
    _add_refuel(client, vid, date(2025, 4, 10), 11300, litres="15", total="22.50",
                station_id=alpha, is_full=False)  # fmt: skip
    _add_refuel(client, vid, date(2025, 5, 10), 11800, litres="20",
                price_per_litre="1.5", station_id=alpha)  # fmt: skip
    _add_expense(client, vid, date(2025, 1, 1), category="insurance",
                 title="Policy", amount="365.00", coverage_start="2025-01-01",
                 coverage_end="2025-12-31")  # fmt: skip
    _add_expense(client, vid, date(2025, 3, 15), category="maintenance",
                 title="Service", amount="100", odometer_km="11100")  # fmt: skip
    return vid


JAN_MAY = {"date_from": "2025-01-01", "date_to": "2025-05-31"}


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def ingress_client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """Client that talks like the HA Ingress proxy."""
    headers = {"X-Ingress-Path": PREFIX}
    with TestClient(create_app(settings, engine), headers=headers) as c:
        yield c


@pytest.fixture
def second_app(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    """A second, empty app (fresh database) to re-import exports into."""
    engine = make_engine()
    run_migrations(engine)
    settings = Settings(data_dir=tmp_path / "second")
    with TestClient(create_app(settings, engine)) as c:
        yield c, engine
    engine.dispose()


# --- Dashboard numbers ------------------------------------------------------


def test_dashboard_numbers_match_hand_computation(client: TestClient) -> None:
    _build_scenario(client)
    html = client.get("/").text

    # fuel 209.50 + insurance 365 + service 100 (full year = same in both modes)
    assert _tile(html, "Total cost") == "674.50 EUR"
    # segments: 500 km/30 L, 500 km/35 L, 800 km/(15+20) L -> 100 L / 1800 km
    assert _tile(html, "Average consumption").startswith("5.56 L/100 km")
    assert "3 valid segments" in html
    # 674.50 EUR over 11800 - 10000 km
    assert _tile(html, "Cost per km").startswith("0.375 EUR/km")


def test_two_of_three_price_entry_stored(client: TestClient, engine: Engine) -> None:
    _build_scenario(client)
    with Session(engine) as session:
        by_odo = {r.odometer_km: r for r in session.scalars(select(Refuel))}
    assert by_odo[10500].price_per_litre_milli == 1600  # from litres + total
    assert by_odo[11000].total_cents == 4900  # from litres + price
    assert by_odo[10000].total_cents == 6000


def test_spread_versus_paid_toggle(client: TestClient, engine: Engine) -> None:
    _build_scenario(client)
    with Session(engine) as session:
        before = session.scalar(select(func.sum(Expense.amount_cents)))

    spread = client.get("/", params=JAN_MAY).text
    paid = client.get("/", params={**JAN_MAY, "allocation": "paid"}).text

    # Jan-May is 151 of 365 days: 151.00 of the policy, plus 209.50 fuel + 100
    assert _tile(spread, "Total cost") == "460.50 EUR"
    assert _tile(spread, "Cost per km").startswith("0.256 EUR/km")  # 460.5 / 1800
    # as paid: the whole 365.00 sits on 2025-01-01
    assert _tile(paid, "Total cost") == "674.50 EUR"
    assert _tile(paid, "Cost per km").startswith("0.375 EUR/km")
    # the toggle is view-only
    with Session(engine) as session:
        assert session.scalar(select(func.sum(Expense.amount_cents))) == before
    insurance = _table_rows(spread, "Cost by category")
    assert ["insurance", "151.00 EUR"] in insurance
    assert ["insurance", "365.00 EUR"] in _table_rows(paid, "Cost by category")


def test_toggle_links_keep_filters(client: TestClient) -> None:
    _build_scenario(client)
    html = client.get("/", params=JAN_MAY).text
    assert "allocation=paid" in html and "date_from=2025-01-01" in html


def test_station_table_by_station_and_brand(client: TestClient) -> None:
    _build_scenario(client)
    rows = {r[0]: r for r in _table_rows(client.get("/").text, "Stations and brands")}
    # Alpha: 4 fills, 110 L, 161.50 / 110 L = 1.468, min 1.400, max 1.500;
    # single-source segments: 500 km/35 L and 800 km/35 L -> 70 L / 1300 km
    assert rows["Alpha"][1:] == ["4", "110.00", "1.468", "1.400", "1.500", "5.38 (2)"]
    # Beta: one fill, one segment only, so consumption is n/a below 2
    assert rows["Beta"][1:6] == ["1", "30.00", "1.600", "1.600", "1.600"]
    assert rows["Beta"][6].startswith("n/a")

    alpha = _station_id(client, "Alpha")
    _post(client, "/stations/brand", {"station_ids": str(alpha), "brand": "Shell"})
    by_brand = _table_rows(client.get("/", params={"group": "brand"}).text,
                           "Stations and brands")  # fmt: skip
    labels = [r[0] for r in by_brand]
    assert "Shell" in labels and len(by_brand) == 2
    shell = next(r for r in by_brand if r[0] == "Shell")
    assert shell[1] == "4"


def test_expense_title_is_required(client: TestClient) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    response = client.post(
        "/expenses/new",
        data={"vehicle_id": "1", "date": "2025-01-01", "category": "other",
              "title": "  ", "amount": "5"},
    )  # fmt: skip
    assert response.status_code == 422 and "Title is required" in response.text


# --- API equals dashboard ---------------------------------------------------


def test_api_summary_equals_dashboard(client: TestClient) -> None:
    today = date.today()
    _post(client, "/vehicles/new", {"name": "Golf"})
    vid = _vehicle_id(client, "Golf")
    for days_ago, odo, litres, ppl in [(100, 20000, 40, "1.5"), (70, 20500, 30, "1.6"),
                                       (40, 21100, 36, "1.4"), (10, 21700, 38, "1.5")]:  # fmt: skip
        _add_refuel(client, vid, today - timedelta(days=days_ago), odo,
                    litres=litres, price_per_litre=ppl)  # fmt: skip
    _add_expense(client, vid, today - timedelta(days=20), category="insurance",
                 title="Policy", amount="240.00",
                 coverage_start=(today - timedelta(days=20)).isoformat(),
                 coverage_end=(today + timedelta(days=219)).isoformat())  # fmt: skip

    for allocation in ("spread", "paid"):
        summary = client.get(
            f"/api/v1/vehicles/{vid}/summary", params={"allocation": allocation}
        ).json()
        assert summary["allocation"] == allocation
        window = {"vehicle": vid, "allocation": allocation,
                  "date_from": (today.replace(year=today.year - 1) + timedelta(days=1)).isoformat(),
                  "date_to": today.isoformat()}  # fmt: skip
        page = client.get("/", params=window).text
        per_km = _tile(page, "Cost per km").split()[0]
        assert per_km == f"{summary['cost_per_km_12m']:.3f}"
        consumption = _tile(page, "Average consumption").split()[0]
        assert consumption == f"{summary['avg_consumption_12m']:.2f}"

        year = {"vehicle": vid, "allocation": allocation,
                "date_from": f"{today.year}-01-01", "date_to": f"{today.year}-12-31"}  # fmt: skip
        total = _tile(client.get("/", params=year).text, "Total cost")
        assert total == f"{summary['cost_this_year']:.2f} EUR"

    # hand check of the consumption: 3 valid segments, 1650 km, 104 L
    summary = client.get(f"/api/v1/vehicles/{vid}/summary").json()
    assert summary["avg_consumption_12m"] == pytest.approx(104 / 1700 * 100, abs=0.01)
    assert summary["last_odometer_km"] == 21700


def test_api_station_stats_equal_dashboard_table(client: TestClient) -> None:
    _build_scenario(client)
    api = {s["label"]: s for s in client.get("/api/v1/stations/stats").json()["stations"]}
    rows = {r[0]: r for r in _table_rows(client.get("/").text, "Stations and brands")}
    for label, row in rows.items():
        assert f"{api[label]['avg_price_per_litre']:.3f}" == row[3]
        assert str(api[label]["fills"]) == row[1]
    assert api["Alpha"]["consumption_segments"] == 2
    assert api["Alpha"]["consumption"] == pytest.approx(5.3846, abs=1e-3)


# --- Imports through the web flow ------------------------------------------


def _upload(client: TestClient, name: str, data: bytes, fmt: str = "") -> str:
    """Upload; return the preview URL path with query."""
    response = client.post(
        "/import/upload", data={"format": fmt}, files={"file": (name, data)},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code == 303
    return response.headers["location"].removeprefix(
        client.headers.get("X-Ingress-Path", "")
    )


def _import_file(
    client: TestClient, name: str, data: bytes, answers: dict[str, str] | None = None
) -> str:
    """Upload, answer the preview questions, commit; return the preview HTML."""
    location = _upload(client, name, data)
    preview = client.get(location)
    assert preview.status_code == 200
    # answer the questions the way a user would: change fields, update preview
    pairs = [(k, v) for k, v in _form_fields(preview.text) if k not in (answers or {})]
    pairs += list((answers or {}).items())
    updated = client.get("/import/preview", params=pairs)
    assert updated.status_code == 200
    pairs = _form_fields(updated.text)
    committed = client.post("/import/commit", data=_as_form(pairs), follow_redirects=False)
    assert committed.status_code == 303, committed.text[:800]
    return updated.text


def _counts(engine: Engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count(Refuel.id))),
            session.scalar(select(func.count(Expense.id))),
            session.scalar(select(func.count(Vehicle.id))),
        )


# file, answers, (refuels, expenses, vehicles) after commit
IMPORT_CASES = [
    ("drivvo_refuel_en.csv", {"default_vehicle": "1"}, (2, 0, 1)),
    ("drivvo_service_en.csv", {"default_vehicle": "1"}, (0, 3, 1)),
    ("drivvo_expense_en.csv", {"default_vehicle": "1"}, (0, 2, 1)),
    ("fuelio_comma_km.csv", {}, (4, 3, 2)),
    ("fuelio_semicolon_miles.csv", {}, (2, 1, 2)),
    ("fuelly_import_metric.csv", {"default_vehicle": "1"}, (3, 0, 1)),
    ("fuelly_import_gallons.csv", {"default_vehicle": "1"}, (2, 0, 1)),
    ("fuelly_import_ambiguous_dates.csv",
     {"default_vehicle": "1", "date_order": "dmy"}, (2, 0, 1)),
    ("fuelly_export.csv", {"units": "imperial"}, (2, 0, 2)),
]  # fmt: skip


@pytest.mark.parametrize(("name", "answers", "expected"), IMPORT_CASES)
def test_import_each_fixture_then_undo(
    client: TestClient, engine: Engine, fixtures_dir: Path,
    name: str, answers: dict, expected: tuple,
) -> None:  # fmt: skip
    _post(client, "/vehicles/new", {"name": "Existing"})
    base = _counts(engine)
    _import_file(client, name, (fixtures_dir / name).read_bytes(), answers)
    refuels, expenses, vehicles = _counts(engine)
    assert (refuels, expenses) == expected[:2]
    assert vehicles - base[2] == expected[2] - 1  # vehicles created by the file

    page = client.get("/import").text
    batch_id = int(re.search(r"/import/(\d+)/undo", page).group(1))
    # importing the same file again adds nothing
    again = _import_file(client, name, (fixtures_dir / name).read_bytes(), answers)
    assert _counts(engine)[:2] == (refuels, expenses)
    assert "New refuels: <strong>0</strong>" in again

    batches = [int(b) for b in re.findall(r"/import/(\d+)/undo", client.get("/import").text)]
    for undo_id in batches:
        _post(client, f"/import/{undo_id}/undo", {})
    assert _counts(engine)[:2] == (0, 0)
    with Session(engine) as session:
        assert session.scalar(select(func.count(Station.id))) == 0
        assert session.scalar(select(func.count(ImportBatch.id))) == 0
    assert batch_id in batches


def test_preview_writes_nothing(client: TestClient, engine: Engine, fixtures_dir: Path):
    _post(client, "/vehicles/new", {"name": "Existing"})
    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    assert client.get(_upload(client, "f.csv", data)).status_code == 200
    assert _counts(engine) == (0, 0, 1)


def test_vehicle_question_is_not_shown_as_failure(
    client: TestClient, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    data = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
    html = client.get(_upload(client, "f.csv", data)).text
    assert "Which vehicle do these records belong to?" in html
    assert "Choose a target vehicle" not in html
    assert 'class="error"' not in html and "Import now" not in html


def test_unknown_headers_show_found_and_expected(
    client: TestClient, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "drivvo_unknown_headers.csv").read_bytes()
    html = client.get(_upload(client, "f.csv", data, "drivvo")).text
    assert "Found:" in html and "Datum" in html and "Expected:" in html


def test_choosing_new_vehicle_when_name_is_taken_is_reported(
    client: TestClient, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Test Golf"})
    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    html = _preview_with(client, data, {"maps": "new", "names": "Test Golf"})
    assert "already exists" in html and "Import now" not in html


def _preview_with(client: TestClient, data: bytes, extra: dict) -> str:
    location = _upload(client, "f.csv", data)
    token = re.search(r"token=([0-9a-f]+)", location).group(1)
    return client.get("/import/preview", params={"token": token, **extra}).text


def test_undo_unknown_batch_is_404(client: TestClient) -> None:
    assert client.post("/import/999/undo", follow_redirects=False).status_code == 404


# --- Exports and re-import --------------------------------------------------


def _dashboard_numbers(client: TestClient) -> dict:
    html = client.get("/").text
    return {
        "total": _tile(html, "Total cost"),
        "per_km": _tile(html, "Cost per km"),
        "consumption": _tile(html, "Average consumption"),
        "stations": _table_rows(html, "Stations and brands"),
    }


def test_native_export_reimports_identically(
    client: TestClient, second_app: tuple[TestClient, Engine]
) -> None:
    _build_scenario(client)
    exported = client.get("/export/native")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist()) == {
            "vehicles.csv", "stations.csv", "refuels.csv", "expenses.csv",
            "manifest.json",
        }  # fmt: skip

    other, other_engine = second_app
    _import_file(other, "export.zip", exported.content)
    assert _counts(other_engine) == (5, 2, 1)
    assert _dashboard_numbers(other) == _dashboard_numbers(client)
    # exporting again gives the same tables
    again = other.get("/export/native").content
    assert _tables(again) == _tables(exported.content)
    # the manifest carries the running app's currency
    assert b'"currency": "EUR"' in zipfile.ZipFile(io.BytesIO(again)).read("manifest.json")


def _tables(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n).decode() for n in archive.namelist() if n != "manifest.json"}


def test_native_manifest_uses_app_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CURRENCY", "USD")  # must not leak into the export
    engine = make_engine()
    run_migrations(engine)
    with TestClient(create_app(Settings(data_dir=tmp_path, currency="CHF"), engine)) as c:
        data = c.get("/export/native").content
    engine.dispose()
    assert b'"currency": "CHF"' in zipfile.ZipFile(io.BytesIO(data)).read("manifest.json")


def test_fuelly_export_reimports_with_stations(
    client: TestClient, second_app: tuple[TestClient, Engine]
) -> None:
    _build_scenario(client)
    exported = client.get("/export/fuelly")
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.text.splitlines()[0] == (
        "fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags"
    )

    other, other_engine = second_app
    _post(other, "/vehicles/new", {"name": "Golf"})
    _import_file(other, "fuelly.csv", exported.content, {"default_vehicle": "1"})
    assert _counts(other_engine) == (5, 0, 1)  # expenses are not in this format
    mine, theirs = _dashboard_numbers(client), _dashboard_numbers(other)
    assert theirs["stations"] == mine["stations"]  # station survived via tags
    assert theirs["consumption"] == mine["consumption"]


# --- Everything under an Ingress prefix ------------------------------------

PAGES = ["/", "/vehicles", "/vehicles/new", "/refuels", "/refuels/new", "/expenses",
         "/expenses/new", "/stations", "/import", "/export"]  # fmt: skip
_URL_ATTR = re.compile(r'(?:href|src|action)="(/[^"]*)"')


def _assert_prefixed(html: str) -> None:
    for target in _URL_ATTR.findall(html):
        assert target == PREFIX or target.startswith(PREFIX + "/"), target


def test_whole_flow_under_ingress_prefix(
    ingress_client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    client = ingress_client
    vid = _build_scenario(client)  # redirects asserted inside helpers
    for page in PAGES + [f"/vehicles/{vid}/edit", "/refuels/1/edit", "/expenses/1/edit",
                         "/stations/1/edit", f"/vehicles/{vid}/delete"]:  # fmt: skip
        response = client.get(page)
        assert response.status_code == 200, page
        _assert_prefixed(response.text)

    redirect = client.post("/vehicles/new", data={"name": "Second"}, follow_redirects=False)
    assert redirect.headers["location"] == f"{PREFIX}/vehicles"

    dashboard = client.get("/", params=JAN_MAY).text
    assert _tile(dashboard, "Total cost") == "460.50 EUR"
    assert f'{PREFIX}/?' in dashboard or f'href="{PREFIX}/' in dashboard
    assert f"{PREFIX}/static/chart.umd.min.js" in dashboard

    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    location = client.post(
        "/import/upload", files={"file": ("f.csv", data)}, follow_redirects=False
    ).headers["location"]
    assert location.startswith(f"{PREFIX}/import/preview?")
    preview = client.get(location.removeprefix(PREFIX))
    _assert_prefixed(preview.text)
    fields = _form_fields(preview.text)
    commit = client.post("/import/commit", data=_as_form(fields), follow_redirects=False)
    assert commit.headers["location"] == f"{PREFIX}/import"
    batches = client.get("/import").text
    _assert_prefixed(batches)
    batch_id = re.search(r"/import/(\d+)/undo", batches).group(1)
    assert f'action="{PREFIX}/import/{batch_id}/undo"' in batches

    assert client.get("/export/native").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_api_unaffected_by_ingress_prefix(ingress_client: TestClient) -> None:
    _build_scenario(ingress_client)
    summary = ingress_client.get("/api/v1/vehicles/1/summary").json()
    assert summary["name"] == "Golf" and summary["allocation"] == "spread"
