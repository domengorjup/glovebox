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

from glovebox.app import create_app
from glovebox.config import Settings
from glovebox.db import make_engine, run_migrations
from glovebox.models import Expense, ImportBatch, Refuel, Setting, Station, Vehicle

PREFIX = "/api/hassio_ingress/e2etoken"

# --- HTML helpers -----------------------------------------------------------


def _text(fragment: str) -> str:
    """Visible text of an HTML fragment (tags dropped, no-break spaces as spaces)."""
    plain = re.sub(r"<[^>]+>", " ", fragment).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", plain).strip()


def _kpi(html: str, label: str) -> str:
    """Text of the Stats KPI card with the given label, e.g. ``0.375 EUR/km``."""
    match = re.search(
        rf'data-kpi="{re.escape(label)}".*?<div class="value">(.*?)</div>', html, re.S
    )
    assert match, f"KPI {label!r} not found"
    return _text(match.group(1))


def _legend(html: str) -> dict[str, str]:
    """Cost total per type from the legend under the monthly cost chart."""
    return {
        key: _text(total)
        for key, total in re.findall(
            r'<span data-key="(\w+)">.*?<b>(.*?)</b>', html, re.S
        )
    }


def _price_rows(html: str) -> list[list[str]]:
    """Cell texts of each row of the price per litre table (station/brand + stats)."""
    table = html.split("data-price-table", 1)[1]
    body = re.search(r"<tbody>(.*?)</tbody>", table, re.S).group(1)
    rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        first = re.sub(r'<div class="sub">.*?</div>', "", cells[0], flags=re.S)
        rows.append([_text(first)] + [_text(c) for c in cells[1:]])
    return rows


class _Form(HTMLParser):
    """Collects the fields a browser would submit for the first form on a page."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[tuple[str, str]] = []
        self._select: str | None = None
        self._options: list[tuple[str, bool]] = []
        self._area: str | None = None
        self._text = ""
        self._skip_form = False  # the navbar's vehicle switch is not part of the page's form

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "form":
            self._skip_form = "vehicle-select" in a.get("class", "")
        if self._skip_form:
            return
        if tag == "input":
            kind, name = a.get("type", "text"), a.get("name")
            if name and kind in ("radio", "checkbox"):
                if "checked" in a:
                    self.fields.append((name, a.get("value", "on")))
            elif name and kind not in ("submit", "button", "file"):
                self.fields.append((name, a.get("value", "")))
        elif tag == "textarea" and a.get("name"):
            self._area, self._text = a["name"], ""
        elif tag == "select":
            self._select, self._options = a.get("name"), []
        elif tag == "option" and self._select:
            self._options.append((a.get("value", ""), "selected" in a))

    def handle_data(self, data: str) -> None:
        if self._area and not self._skip_form:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._skip_form = False
        if self._skip_form:
            return
        if tag == "textarea" and self._area:
            self.fields.append((self._area, self._text))
            self._area = None
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


ALL_TIME = {"when": "all"}
JAN_MAY = {"when": "custom", "date_from": "2025-01-01", "date_to": "2025-05-31"}


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


# --- Stats numbers ------------------------------------------------------------


def test_stats_numbers_match_hand_computation(client: TestClient) -> None:
    _build_scenario(client)
    html = client.get("/stats", params=ALL_TIME).text

    # fuel 209.50 + insurance 365 + service 100 (full year = same in both modes)
    assert _kpi(html, "Total cost") == "674.50 €"
    # segments: 500 km/30 L, 500 km/35 L, 800 km/(15+20) L -> 100 L / 1800 km
    assert _kpi(html, "Avg consumption").startswith("5.56 L/100 km")
    # 674.50 EUR over 11800 - 10000 km
    assert _kpi(html, "Cost per km").startswith("0.37 €/km")
    assert _kpi(html, "Distance") == "1,800 km"


def test_timeline_summary_matches_hand_computation(client: TestClient) -> None:
    _build_scenario(client)
    html = client.get("/").text
    assert 'data-card="consumption"' in html and 'data-card="cost_km"' in html
    # all five refuels and both expenses are listed, newest first
    assert html.count('class="row"') == 7
    assert html.index("May 2025") < html.index("January 2025")


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

    spread = client.get("/stats", params=JAN_MAY).text
    paid = client.get("/stats", params={**JAN_MAY, "allocation": "paid"}).text

    # Jan-May is 151 of 365 days: 151.00 of the policy, plus 209.50 fuel + 100
    assert _kpi(spread, "Total cost") == "460.50 €"
    assert _kpi(spread, "Cost per km").startswith("0.26 €/km")  # 460.5 / 1800
    # as paid: the whole 365.00 sits on 2025-01-01
    assert _kpi(paid, "Total cost") == "674.50 €"
    assert _kpi(paid, "Cost per km").startswith("0.37 €/km")
    # the toggle is view-only
    with Session(engine) as session:
        assert session.scalar(select(func.sum(Expense.amount_cents))) == before
    assert _legend(spread)["insurance"] == "151.00 €"
    assert _legend(paid)["insurance"] == "365.00 €"
    assert _legend(paid)["fuel"] == "209.50 €" and _legend(paid)["service"] == "100.00 €"


def test_choice_links_keep_filters(client: TestClient) -> None:
    _build_scenario(client)
    html = client.get("/stats", params=JAN_MAY).text
    assert "allocation=paid" in html and "date_from=2025-01-01" in html
    assert "when=custom" in html


def test_spread_choice_is_only_offered_with_expenses(client: TestClient) -> None:
    _build_scenario(client)
    assert "As paid" in client.get("/stats", params={**ALL_TIME, "what": "expense"}).text
    assert "As paid" not in client.get("/stats", params={**ALL_TIME, "what": "refuel"}).text


def test_what_choice_narrows_the_numbers(client: TestClient) -> None:
    _build_scenario(client)
    fuel = client.get("/stats", params={**ALL_TIME, "what": "refuel"}).text
    assert _kpi(fuel, "Fuel cost") == "209.50 €"
    service = client.get("/stats", params={**ALL_TIME, "what": "service"}).text
    assert _kpi(service, "Total cost") == "100.00 €"
    expense = client.get("/stats", params={**ALL_TIME, "what": "expense"}).text
    assert _kpi(expense, "Total cost") == "365.00 €"


def test_station_table_by_station_and_brand(client: TestClient) -> None:
    _build_scenario(client)
    rows = {r[0]: r for r in _price_rows(client.get("/stats", params=ALL_TIME).text)}
    # Alpha: 4 fills, 110 L, 161.50 / 110 L = 1.468, min 1.400, max 1.500;
    # single-source segments: 500 km/35 L and 800 km/35 L -> 70 L / 1300 km
    assert rows["Alpha"][1:4] == ["4", "110.00", "1.468"]
    assert rows["Alpha"][4:6] == ["1.400", "1.500"]
    assert rows["Alpha"][7] == "5.38 (2)"
    # Beta: one fill, one segment only, so consumption is n/a below 2
    assert rows["Beta"][1:6] == ["1", "30.00", "1.600", "1.600", "1.600"]
    assert rows["Beta"][7].startswith("n/a")

    alpha = _station_id(client, "Alpha")
    _post(client, "/stations/brand", {"station_ids": str(alpha), "brand": "Shell"})
    by_brand = _price_rows(client.get("/stats", params={**ALL_TIME, "group": "brand"}).text)
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


def test_api_summary_equals_stats_page(client: TestClient) -> None:
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

    client.post("/preferences/vehicle", data={"vehicle": str(vid)})
    for allocation in ("spread", "paid"):
        summary = client.get(
            f"/api/v1/vehicles/{vid}/summary", params={"allocation": allocation}
        ).json()
        assert summary["allocation"] == allocation
        window = {"when": "custom", "allocation": allocation,
                  "date_from": (today.replace(year=today.year - 1) + timedelta(days=1)).isoformat(),
                  "date_to": today.isoformat()}  # fmt: skip
        page = client.get("/stats", params=window).text
        per_km = _kpi(page, "Cost per km").split()[0]
        assert per_km == f"{summary['cost_per_km_12m']:.2f}"
        consumption = _kpi(page, "Avg consumption").split()[0]
        assert consumption == f"{summary['avg_consumption_12m']:.2f}"

        year = {"when": "custom", "allocation": allocation,
                "date_from": f"{today.year}-01-01", "date_to": f"{today.year}-12-31"}  # fmt: skip
        total = _kpi(client.get("/stats", params=year).text, "Total cost")
        assert total == f"{summary['cost_this_year']:.2f} €"

    # hand check of the consumption: 3 valid segments, 1650 km, 104 L
    summary = client.get(f"/api/v1/vehicles/{vid}/summary").json()
    assert summary["avg_consumption_12m"] == pytest.approx(104 / 1700 * 100, abs=0.01)
    assert summary["last_odometer_km"] == 21700


def test_api_station_stats_equal_stats_table(client: TestClient) -> None:
    _build_scenario(client)
    api = {s["label"]: s for s in client.get("/api/v1/stations/stats").json()["stations"]}
    rows = {r[0]: r for r in _price_rows(client.get("/stats", params=ALL_TIME).text)}
    for label, row in rows.items():
        assert f"{api[label]['avg_price_per_litre']:.3f}" == row[3]
        assert str(api[label]["fills"]) == row[1]
    assert api["Alpha"]["consumption_segments"] == 2
    assert api["Alpha"]["consumption"] == pytest.approx(5.3846, abs=1e-3)


# --- Imports through the web flow ------------------------------------------


def _upload(client: TestClient, name: str, data: bytes) -> str:
    """Upload; return the next page's URL path with query (mapping or backup preview)."""
    response = client.post(
        "/import/upload", files={"file": (name, data)}, follow_redirects=False
    )
    assert response.status_code == 303
    return response.headers["location"].removeprefix(
        client.headers.get("X-Ingress-Path", "")
    )


def _merged(fields: list[tuple[str, str]], changes: dict[str, str]) -> dict[str, list[str]]:
    """The form a browser sends after the user changed some fields."""
    kept = [(k, v) for k, v in fields if k not in changes]
    return _as_form(kept + list(changes.items()))


def _preview_of(
    client: TestClient, name: str, data: bytes, changes: dict[str, str] | None = None
) -> str:
    """
    Upload, open the mapping (when there is one), change fields, press Preview, answer
    the questions and press Update preview; return the preview HTML.
    """
    changes = changes or {}
    page = client.get(_upload(client, name, data))
    assert page.status_code == 200
    if "Map columns" in page.text:
        page = client.post("/import/preview", data=_merged(_form_fields(page.text), changes))
        assert page.status_code == 200, page.text[:500]
    page = client.post("/import/preview", data=_merged(_form_fields(page.text), changes))
    assert page.status_code == 200, page.text[:500]
    return page.text


def _import_file(
    client: TestClient, name: str, data: bytes, changes: dict[str, str] | None = None
) -> str:
    """Upload, go through the mapping and the preview, commit; return the preview HTML."""
    preview = _preview_of(client, name, data, changes)
    committed = client.post(
        "/import/commit", data=_merged(_form_fields(preview), changes or {}),
        follow_redirects=False,
    )
    assert committed.status_code == 303, committed.text[:800]
    return preview


def _counts(engine: Engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count(Refuel.id))),
            session.scalar(select(func.count(Expense.id))),
            session.scalar(select(func.count(Vehicle.id))),
        )


# file, form changes, (refuels, expenses, vehicles) after commit
IMPORT_CASES = [
    ("drivvo_en_sections.csv", {"default_vehicle": "1"}, (4, 0, 1)),
    ("fuelio_comma_km.csv", {"default_vehicle": "1"}, (4, 0, 1)),
    ("fuelio_semicolon_miles.csv", {"default_vehicle": "1", "ans_distance_unit": "mi"}, (2, 0, 1)),
    ("fuelly_import_metric.csv", {"default_vehicle": "1"}, (3, 0, 1)),
    ("fuelly_import_gallons.csv", {"default_vehicle": "1"}, (2, 0, 1)),
    ("fuelly_import_ambiguous_dates.csv",
     {"default_vehicle": "1", "ans_date_order": "dmy"}, (2, 0, 1)),
    ("fuelly_export.csv", {"ans_distance_unit": "mi", "ans_volume_unit": "gal_us"}, (2, 0, 2)),
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
    # importing the same file again adds nothing, offers no import and writes no batch
    again = _preview_of(client, name, (fixtures_dir / name).read_bytes(), answers)
    assert "New refuels: <strong>0</strong>" in again
    assert "Nothing new to import" in again and ">Import now</button>" not in again
    forced = client.post("/import/commit", data=_merged(_form_fields(again), answers))
    assert forced.status_code == 422 and "Nothing new to import" in forced.text
    assert _counts(engine)[:2] == (refuels, expenses)

    batches = [int(b) for b in re.findall(r"/import/(\d+)/undo", client.get("/import").text)]
    for undo_id in batches:
        _post(client, f"/import/{undo_id}/undo", {})
    assert _counts(engine)[:2] == (0, 0)
    with Session(engine) as session:
        assert session.scalar(select(func.count(Station.id))) == 0
        assert session.scalar(select(func.count(ImportBatch.id))) == 0
    assert batch_id in batches


def test_drivvo_file_is_imported_once_per_section(
    client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
    page = client.get(_upload(client, "d.csv", data)).text
    assert _selected_option(page, "preset") == "drivvo-refuelling"
    _import_file(client, "d.csv", data, {"default_vehicle": "1"})
    done = client.get("/import?done=1&more=Expense&more=Service").text
    assert "More sections in this file: Expense, Service" in done
    for preset_id in ("drivvo-expenses", "drivvo-services"):
        _import_file(client, "d.csv", data, {"default_vehicle": "1", "preset": preset_id})
    # 3 expenses, 4 priced service items (the 0-cost item is skipped)
    assert _counts(engine) == (4, 7, 1)


def _next_section_url(client: TestClient, page: str, section: str) -> str:
    """Path of the "Import next section: <section>" button."""
    match = re.search(
        rf'<a class="btn primary[^"]*" href="([^"]+)">(?:(?!</a>).)*Import next section: {section}',
        page, re.S,
    )
    assert match, f"no 'Import next section: {section}' button"
    href = match.group(1).replace("&amp;", "&")
    return href.removeprefix(client.headers.get("X-Ingress-Path", ""))


def test_drivvo_sections_guided_with_new_vehicle(
    client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
    mapping = client.get(_upload(client, "d.csv", data)).text
    assert _selected_option(mapping, "preset") == "drivvo-refuelling"
    assert "Choose the vehicle, or add a new one." in mapping  # the preset's steps

    # No vehicle exists yet: create one at the preview.
    new = {"default_vehicle": "new", "new_vehicle_name": "Passat"}
    preview = client.post("/import/preview", data=_merged(_form_fields(mapping), new)).text
    assert 'value="new" selected' in preview and ">Import now</button>" in preview
    done = client.post("/import/commit", data=_merged(_form_fields(preview), new),
                       follow_redirects=False)
    assert _counts(engine) == (4, 0, 1)
    page = client.get(done.headers["location"].removeprefix(
        client.headers.get("X-Ingress-Path", ""))).text
    assert "Imported 4 refuels and 0 expenses" in _text(page)

    for section, preset_id, expected in (
        ("Expense", "drivvo-expenses", (4, 3, 1)),
        ("Service", "drivvo-services", (4, 7, 1)),
    ):
        mapping = client.get(_next_section_url(client, page, section))
        assert _selected_option(mapping.text, "preset") == preset_id
        form = _form_fields(mapping.text)
        assert ("default_vehicle", "1") in form  # the new vehicle is carried over
        preview = client.post("/import/preview", data=_merged(form, {})).text
        assert _selected_option(preview, "default_vehicle") == "1"
        done = client.post("/import/commit", data=_merged(_form_fields(preview), {}),
                           follow_redirects=False)
        assert _counts(engine) == expected
        page = client.get(done.headers["location"].removeprefix(
            client.headers.get("X-Ingress-Path", ""))).text
    assert "Import next section" not in page  # last section: upload removed
    assert not list((client.app.state.settings.data_dir / "uploads").glob("*.upload"))

    with Session(engine) as session:
        oil = session.scalar(select(Expense).where(Expense.title == "Oil Change"))
        assert oil.notes == "Also: Oil Filter"
        assert session.scalar(select(func.count(Expense.id)).where(Expense.title == "Oil Filter")) == 0
        assert session.scalar(select(Vehicle.name)) == "Passat"

    # A re-import of the services section is a no-op, free items included.
    again = _preview_of(client, "d.csv", data,
                        {"default_vehicle": "1", "preset": "drivvo-services"})
    assert "New expenses: <strong>0</strong>" in again


def test_known_file_opens_the_review_and_mapping_is_optional(
    client: TestClient, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "drivvo_en_sections.csv").read_bytes()
    page = client.get(_upload(client, "d.csv", data)).text
    assert "Map columns" not in page and 'name="src.' not in page
    assert _selected_option(page, "preset") == "drivvo-refuelling"
    assert "Choose the vehicle, or add a new one." in page
    assert "New refuels: <strong>" in page and "Adjust mapping" in page
    assert ">Import now</button>" not in page  # a vehicle is needed first

    # switching the preset updates the review in place
    switched = client.post("/import/preview", data=_merged(
        _form_fields(page), {"preset": "drivvo-services"})).text
    assert _selected_option(switched, "preset") == "drivvo-services"
    assert "Zero-cost items become notes" in switched and "Map columns" not in switched

    # the mapping is one button away and returns to the review
    mapping = client.post("/import/mapping", data=_merged(_form_fields(page), {}))
    assert "Map columns" in mapping.text and "Back to review" in mapping.text
    assert 'class="key">odometer_km</span>' in mapping.text and "Odometer" in mapping.text
    back = client.post("/import/preview", data=_merged(
        _form_fields(mapping.text), {"default_vehicle": "new", "new_vehicle_name": "Passat"}))
    assert "Map columns" not in back.text and ">Import now</button>" in back.text


def test_file_no_preset_fits_opens_the_mapping(
    client: TestClient, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "drivvo_unknown_headers.csv").read_bytes()
    page = client.get(_upload(client, "f.csv", data)).text
    assert "Map columns" in page and "No preset fits this file" in page
    assert page.count(">Back to review</button>") == 2  # at the top and at the bottom


def test_new_vehicle_at_import_needs_a_free_name(
    client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    name = "fuelly_import_metric.csv"
    data = (fixtures_dir / name).read_bytes()
    for typed, message in (("  ", "Enter a name for the new vehicle."),
                           ("Golf", "already exists")):
        preview = _preview_of(client, name, data,
                              {"default_vehicle": "new", "new_vehicle_name": typed})
        assert message in preview and ">Import now</button>" not in preview
    assert _counts(engine)[2] == 1


def test_commit_shows_the_result_with_undo(client: TestClient, fixtures_dir: Path) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    name = "fuelly_import_metric.csv"
    preview = _preview_of(client, name, (fixtures_dir / name).read_bytes(), {"default_vehicle": "1"})
    done = client.post(
        "/import/commit", data=_merged(_form_fields(preview), {"default_vehicle": "1"}),
        follow_redirects=True,
    )
    assert done.status_code == 200
    notice = re.search(r'<div class="alert success".*?</div>', done.text, re.S).group(0)
    assert "Imported 3 refuels and 0 expenses" in _text(notice)
    assert re.search(r'action="/import/\d+/undo"', notice)


def test_mapping_page_labels_fit_and_header_row_is_enabled(
    client: TestClient, fixtures_dir: Path
) -> None:
    name = "fuelly_import_metric.csv"
    location = _upload(client, name, (fixtures_dir / name).read_bytes())
    page = client.get(location.replace("/import/preview?", "/import/mapping?")).text
    assert "Auto (UTF-8)" in page and "Detected" not in page
    header_row = re.search(r'<input id="i-header_row"[^>]*>', page).group(0)
    assert "disabled" not in header_row and "readonly" not in header_row


def test_mapping_and_preview_write_nothing(
    client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    assert client.get(_upload(client, "f.csv", data)).status_code == 200
    _preview_of(client, "f.csv", data, {"default_vehicle": "1"})
    assert _counts(engine) == (0, 0, 1)


def test_the_best_preset_is_preselected_on_the_mapping_page(
    client: TestClient, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    page = client.get(_upload(client, "f.csv", data)).text
    assert _selected_option(page, "preset") == "fuelio-fillups"
    other = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
    page = client.get(_upload(client, "f.csv", other)).text
    assert _selected_option(page, "preset") == "fuelly-metric"


def test_vehicle_question_is_not_shown_as_failure(
    client: TestClient, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    data = (fixtures_dir / "fuelly_import_metric.csv").read_bytes()
    html = _preview_of(client, "f.csv", data)
    assert "Which vehicle do these records belong to?" in html
    assert "Choose a target vehicle" not in html
    assert 'class="alert error' not in html and ">Import now</button>" not in html


def test_unknown_headers_open_the_mapping_and_block_the_import(
    client: TestClient, fixtures_dir: Path
) -> None:
    data = (fixtures_dir / "drivvo_unknown_headers.csv").read_bytes()
    page = client.get(_upload(client, "f.csv", data)).text
    assert "Map columns" in page and "Datum" in page
    assert _selected_option(page, "preset") == ""  # "Custom mapping"
    html = _preview_of(client, "f.csv", data)
    assert ">Import now</button>" not in html and "or adjust the mapping" in html


def test_choosing_new_vehicle_when_name_is_taken_is_reported(
    client: TestClient, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Test Golf"})
    data = (fixtures_dir / "standard_records.csv").read_bytes()
    first = _preview_of(client, "f.csv", data)
    name = re.search(r'name="names" value="([^"]+)"', first).group(1)
    _post(client, "/vehicles/new", {"name": name})
    html = _preview_of(client, "f.csv", data, {"maps": "new"})
    assert "already exists" in html and ">Import now</button>" not in html


def test_user_preset_saved_from_the_mapping_is_detected_next_time(
    client: TestClient, engine: Engine
) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    first = (
        "Datum;Stand;Liter;Preis pro Liter;Tankstelle\n"
        "05.03.2024;10000;40,5;1,550;Alpha\n19.03.2024;10600;38,0;1,600;Alpha\n"
    ).encode()
    second = first.replace(b"05.03", b"05.04").replace(b"19.03", b"19.04")
    page = client.get(_upload(client, "bank.csv", first))
    assert _selected_option(page.text, "preset") == ""
    mapping = {
        "src.type": "=", "val.type": "refuel", "src.date": "col:Datum",
        "src.odometer_km": "col:Stand", "src.fuel_l": "col:Liter",
        "src.price_per_l": "col:Preis pro Liter", "src.station": "col:Tankstelle",
        "date_format": "%d.%m.%Y", "decimal_char": ",", "default_vehicle": "1",
    }
    preview = client.post(
        "/import/preview", data=_merged(_form_fields(page.text), mapping)
    )
    assert "New refuels: <strong>2</strong>" in preview.text
    saved = client.post(
        "/import/save-preset",
        data=_merged(_form_fields(preview.text), {"preset_name": "My bank"}),
    )
    assert saved.status_code == 200 and "Saved as preset: My bank" in saved.text
    committed = client.post(
        "/import/commit", data=_as_form(_form_fields(saved.text)), follow_redirects=False
    )
    assert committed.status_code == 303 and _counts(engine)[0] == 2

    # a later file with the same headers selects the saved preset and imports cleanly
    again = client.get(_upload(client, "bank2.csv", second)).text
    assert _selected_option(again, "preset") == "user-my-bank"
    html = _preview_of(client, "bank2.csv", second, {"default_vehicle": "1"})
    assert "New refuels: <strong>2</strong>" in html and "Rows with errors" not in html


def test_zip_with_vehicles_and_stations_but_no_datapackage(
    client: TestClient, engine: Engine
) -> None:
    records = (
        "type,vehicle,date,odometer_km,fuel_l,price_per_l,total,station,station_location\n"
        "refuel,Golf,2025-01-10,10000,40,1.5,60.00,Alpha,Celje\n"
    )
    members = {
        "records.csv": records,
        "vehicles.csv": "name,make,plate\nGolf,VW,LJ AB-123\n",
        "stations.csv": "name,location,brand\nAlpha,Celje,OMV\nBeta,Maribor,\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, text in members.items():
            archive.writestr(member, text)
    html = _import_file(client, "tables.zip", buffer.getvalue())
    assert "Vehicles and stations from the file" in html
    with Session(engine) as session:
        golf = session.scalar(select(Vehicle))
        assert (golf.make, golf.plate) == ("VW", "LJ AB-123")
        brands = {s.name: s.brand for s in session.scalars(select(Station))}
        assert brands == {"Alpha": "OMV", "Beta": None}


def test_undo_unknown_batch_is_404(client: TestClient) -> None:
    assert client.post("/import/999/undo", follow_redirects=False).status_code == 404


# --- Exports and re-import --------------------------------------------------


def _stats_numbers(client: TestClient) -> dict:
    html = client.get("/stats", params=ALL_TIME).text
    return {
        "total": _kpi(html, "Total cost"),
        "per_km": _kpi(html, "Cost per km"),
        "consumption": _kpi(html, "Avg consumption"),
        "stations": _price_rows(html),
    }


def _backup(client: TestClient) -> bytes:
    response = client.post("/export/backup")
    assert response.status_code == 200
    return response.content


def test_backup_round_trip_restores_identically(
    client: TestClient, second_app: tuple[TestClient, Engine]
) -> None:
    _build_scenario(client)
    exported = _backup(client)
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert set(archive.namelist()) == {
            "records.csv", "vehicles.csv", "stations.csv", "reminders.csv",
            "datapackage.json",
        }  # fmt: skip

    other, other_engine = second_app
    _import_file(other, "backup.zip", exported)
    assert _counts(other_engine) == (5, 2, 1)
    assert _stats_numbers(other) == _stats_numbers(client)
    # backing up again gives the same tables
    again = _backup(other)
    assert _tables(again) == _tables(exported)
    # the descriptor carries the running app's currency
    assert b'"currency": "EUR"' in zipfile.ZipFile(io.BytesIO(again)).read("datapackage.json")


def _tables(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {
            n: archive.read(n).decode() for n in archive.namelist() if n != "datapackage.json"
        }


def test_backup_descriptor_uses_app_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CURRENCY", "USD")  # must not leak into the export
    engine = make_engine()
    run_migrations(engine)
    with TestClient(create_app(Settings(data_dir=tmp_path, currency="CHF"), engine)) as c:
        data = c.post("/export/backup").content
    engine.dispose()
    assert b'"currency": "CHF"' in zipfile.ZipFile(io.BytesIO(data)).read("datapackage.json")


def _download(client: TestClient, preset: str):
    """Press Download on the export page of ``preset`` with its default columns."""
    page = client.get("/export", params={"preset": preset})
    return client.post("/export/csv", data=_as_form(_form_fields(page.text)))


def test_standard_export_has_the_standard_columns(client: TestClient) -> None:
    _build_scenario(client)
    exported = _download(client, "glovebox")
    assert exported.headers["content-type"].startswith("text/csv")
    header = exported.text.splitlines()[0].split(",")
    assert header[:5] == ["type", "vehicle", "date", "time", "odometer_km"]
    assert len(exported.text.splitlines()) == 1 + 5 + 2  # refuels and expenses


def test_fuelly_export_reimports_with_stations(
    client: TestClient, second_app: tuple[TestClient, Engine]
) -> None:
    _build_scenario(client)
    exported = _download(client, "fuelly-metric")
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.text.splitlines()[0] == (
        "fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags"
    )

    other, other_engine = second_app
    _post(other, "/vehicles/new", {"name": "Golf"})
    _import_file(other, "fuelly.csv", exported.content, {"default_vehicle": "1"})
    assert _counts(other_engine) == (5, 0, 1)  # expenses are not in this format
    mine, theirs = _stats_numbers(client), _stats_numbers(other)
    assert theirs["stations"] == mine["stations"]  # station survived via tags
    assert theirs["consumption"] == mine["consumption"]


def test_export_vehicle_rows_have_no_line_break(client: TestClient) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    rows = client.get("/export").text.split("Nothing ticked", 1)[0]
    assert "<br" not in rows.split("<h2>Vehicles</h2>", 1)[1]


def test_split_export_skips_vehicles_without_rows(client: TestClient) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    _post(client, "/vehicles/new", {"name": "Empty"})
    empty = _download(client, "fuelly-metric")  # nothing to export at all
    assert empty.status_code == 422 and "Nothing to export" in empty.text
    _add_refuel(client, _vehicle_id(client, "Golf"), date(2026, 1, 5), 1000, litres="40",
                price_per_litre="1.5")
    exported = _download(client, "fuelly-metric")  # one file left: plain CSV, no empty one
    assert exported.headers["content-type"].startswith("text/csv")
    assert len(exported.text.splitlines()) == 2


# --- Everything under an Ingress prefix ------------------------------------

PAGES = ["/", "/?type=service", "/stats", "/manage", "/add", "/vehicles", "/vehicles/new",
         "/refuels/new", "/expenses/new", "/expenses/new?kind=service", "/stations",
         "/import", "/export"]  # fmt: skip
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

    stats_page = client.get("/stats", params=JAN_MAY).text
    assert _kpi(stats_page, "Total cost") == "460.50 €"
    assert f'href="{PREFIX}/stats?' in stats_page
    assert f"{PREFIX}/static/icons.svg#" in stats_page
    assert f"{PREFIX}/static/app.js" in stats_page

    chosen = client.post("/preferences/vehicle", data={"vehicle": str(vid), "next": "/stats"},
                         follow_redirects=False)
    assert chosen.headers["location"] == f"{PREFIX}/stats"
    cards = client.post("/preferences/cards", data={"card": "odometer"}, follow_redirects=False)
    assert cards.headers["location"] == f"{PREFIX}/"

    data = (fixtures_dir / "fuelio_comma_km.csv").read_bytes()
    location = client.post(
        "/import/upload", files={"file": ("f.csv", data)}, follow_redirects=False
    ).headers["location"]
    assert location.startswith(f"{PREFIX}/import/preview?")
    mapping = client.get(location.removeprefix(PREFIX))
    _assert_prefixed(mapping.text)
    fields = _merged(_form_fields(mapping.text), {"default_vehicle": str(vid)})
    preview = client.post("/import/preview", data=fields)
    _assert_prefixed(preview.text)
    fields = _merged(_form_fields(preview.text), {"default_vehicle": str(vid)})
    commit = client.post("/import/commit", data=fields, follow_redirects=False)
    assert commit.headers["location"].startswith(f"{PREFIX}/import")
    batches = client.get("/import").text
    _assert_prefixed(batches)
    batch_id = re.search(r"/import/(\d+)/undo", batches).group(1)
    assert f'action="{PREFIX}/import/{batch_id}/undo"' in batches

    export_page = client.get("/export")
    _assert_prefixed(export_page.text)
    assert client.post("/export/backup").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_api_unaffected_by_ingress_prefix(ingress_client: TestClient) -> None:
    _build_scenario(ingress_client)
    summary = ingress_client.get("/api/v1/vehicles/1/summary").json()
    assert summary["name"] == "Golf" and summary["allocation"] == "spread"


# --- UI preferences (stored in the database) --------------------------------


def _two_vehicles(client: TestClient) -> tuple[int, int]:
    _post(client, "/vehicles/new", {"name": "Golf"})
    _post(client, "/vehicles/new", {"name": "Clio"})
    return _vehicle_id(client, "Golf"), _vehicle_id(client, "Clio")


def _selected_option(html: str, select_name: str) -> str | None:
    """Value of the selected option of ``<select name=...>`` (None if no select)."""
    block = re.search(rf'<select[^>]*name="{select_name}".*?</select>', html, re.S)
    if not block:
        return None
    chosen = re.search(r'<option value="([^"]*)"[^>]*selected', block.group(0))
    return chosen.group(1) if chosen else ""


def test_preferences_survive_a_restart(
    settings: Settings, engine: Engine, client: TestClient
) -> None:
    golf, clio = _two_vehicles(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(clio)})
    _post(client, "/preferences/cards", {"card": ["odometer", "avg_price"]})
    with Session(engine) as session:
        keys = set(session.scalars(select(Setting.key)))
    assert keys == {"selected_vehicle", "last_vehicle", "summary_cards"}

    with TestClient(create_app(settings, engine)) as restarted:
        page = restarted.get("/").text
        assert _selected_option(page, "vehicle") == str(clio)
        shown = re.findall(r'data-card="(\w+)"\s*>', page)
        assert set(shown) == {"odometer", "avg_price"}


def test_form_vehicle_default_follows_navbar_then_last_vehicle(client: TestClient) -> None:
    golf, clio = _two_vehicles(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(golf)})
    for path in ("/refuels/new", "/expenses/new", "/expenses/new?kind=service"):
        assert _selected_option(client.get(path).text, "vehicle_id") == str(golf), path
    _post(client, "/preferences/vehicle", {"vehicle": str(clio)})
    _post(client, "/preferences/vehicle", {"vehicle": "all"})
    assert _selected_option(client.get("/").text, "vehicle") == "all"
    for path in ("/refuels/new", "/expenses/new", "/expenses/new?kind=service"):
        assert _selected_option(client.get(path).text, "vehicle_id") == str(clio), path
    # an explicit ?vehicle= still wins
    assert _selected_option(client.get(f"/refuels/new?vehicle={golf}").text,
                            "vehicle_id") == str(golf)  # fmt: skip


def test_timeline_and_stats_follow_the_navbar_vehicle(client: TestClient) -> None:
    golf, clio = _two_vehicles(client)
    _add_expense(client, golf, date(2025, 3, 1), category="other", title="Golf thing", amount="10")
    _add_expense(client, clio, date(2025, 3, 2), category="other", title="Clio thing", amount="20")
    _post(client, "/preferences/vehicle", {"vehicle": str(clio)})
    only = client.get("/").text
    assert "Clio thing" in only and "Golf thing" not in only
    assert _kpi(client.get("/stats", params=ALL_TIME).text, "Total cost") == "20.00 €"
    _post(client, "/preferences/vehicle", {"vehicle": "all"})
    both = client.get("/").text
    assert "Clio thing" in both and "Golf thing" in both
    assert _kpi(client.get("/stats", params=ALL_TIME).text, "Total cost") == "30.00 €"


def test_all_vehicles_timeline_has_per_vehicle_summary(client: TestClient) -> None:
    _two_vehicles(client)
    html = client.get("/").text
    assert 'data-vehicle-group' in html and "Golf" in html and "Clio" in html


# --- Vehicle management -------------------------------------------------------


def test_vehicle_full_lifecycle_through_the_forms(client: TestClient, engine: Engine) -> None:
    _post(client, "/vehicles/new", {
        "name": "Golf", "make": "VW", "model": "Golf VII", "plate": "LJ 1",
        "fuel_type": "Petrol", "initial_odometer": "1200", "notes": "blue",
    })  # fmt: skip
    vid = _vehicle_id(client, "Golf")
    form = client.get(f"/vehicles/{vid}/edit").text
    for value in ("VW", "Golf VII", "LJ 1", "Petrol", "1200", "blue"):
        assert value in form, value
    _post(client, f"/vehicles/{vid}/edit", {"name": "Golf 7", "make": "VW"})
    _add_refuel(client, vid, date(2025, 1, 10), 1500, litres="40", price_per_litre="1.5")
    listing = _text(client.get("/vehicles").text)
    assert "Golf 7" in listing and "1 record" in listing

    _post(client, f"/vehicles/{vid}/archive", {"archived": "1"})
    assert "Golf 7" not in client.get("/").text.split("</header>")[0]
    assert "Golf 7" not in client.get("/refuels/new").text.split('name="vehicle_id"')[1].split("</select>")[0]
    assert "Archived (1)" in _text(client.get("/vehicles").text)
    _post(client, f"/vehicles/{vid}/archive", {"archived": "0"})
    assert "Golf 7" in client.get("/").text.split("</header>")[0]

    confirm = client.get(f"/vehicles/{vid}/delete").text
    assert "<strong>1</strong> refuels" in confirm and "cannot be undone" in confirm
    assert 'formaction="/export/backup"' in confirm and "Download full backup" in confirm
    backup = client.post("/export/backup")
    assert backup.status_code == 200 and backup.headers["content-type"] == "application/zip"
    gone = client.post(f"/vehicles/{vid}/delete", data={"confirm": "1"}, follow_redirects=False)
    assert gone.status_code == 303 and _counts(engine) == (0, 0, 0)


def test_selected_vehicle_that_gets_archived_falls_back_to_all(client: TestClient) -> None:
    golf, _ = _two_vehicles(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(golf)})
    _post(client, f"/vehicles/{golf}/archive", {"archived": "1"})
    assert _selected_option(client.get("/").text, "vehicle") == "all"


def test_hidden_summaries_are_stored_and_survive_card_changes(
    engine: Engine, client: TestClient
) -> None:
    golf, clio = _two_vehicles(client)
    _post(client, "/preferences/cards", {"card": ["odometer"], "offered": ["all", str(golf), str(clio)],
                                         "summary": ["all", str(clio)]})  # fmt: skip
    with Session(engine) as session:
        stored = session.scalar(select(Setting.value).where(Setting.key == "hidden_summaries"))
    assert stored == f'["{golf}"]'
    # a card change from a single-vehicle view does not offer groups: nothing is reset
    _post(client, "/preferences/cards", {"card": ["cost_km"]})
    page = client.get("/").text
    assert re.search(rf'data-summary="{golf}"\s+hidden', page)
    assert not re.search(rf'data-summary="{clio}"\s+hidden', page)
    # a vehicle added later is shown by default
    _post(client, "/vehicles/new", {"name": "Fiat"})
    fiat = _vehicle_id(client, "Fiat")
    assert not re.search(rf'data-summary="{fiat}"\s+hidden', client.get("/").text)


def test_hidden_summaries_ignore_junk_values(client: TestClient) -> None:
    golf, _ = _two_vehicles(client)
    _post(client, "/preferences/cards", {"offered": ["all", "x;drop", str(golf)], "summary": []})
    assert client.get("/").status_code == 200


def test_avg_price_card_shows_price_per_litre(client: TestClient) -> None:
    golf, _ = _two_vehicles(client)
    today = date.today()
    _add_refuel(client, golf, today, 10000, litres="40", total="60.00")
    _post(client, "/preferences/vehicle", {"vehicle": str(golf)})
    page = client.get("/").text
    card = re.search(r'data-card="avg_price".*?<div class="value">([^<]*)<', page, re.S)
    assert card and card.group(1) == "1.500"


# --- Deleting a station -----------------------------------------------------


def _station_refuel_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        rows = session.execute(
            select(Station.name, func.count(Refuel.id))
            .join(Refuel, Refuel.station_id == Station.id, isouter=True)
            .group_by(Station.id)
        )
        return dict(rows.all())


def test_delete_used_station_moves_refuels(client: TestClient, engine: Engine) -> None:
    _build_scenario(client)
    alpha, beta = _station_id(client, "Alpha"), _station_id(client, "Beta")

    page = client.get(f"/stations/{alpha}/delete").text
    assert "<strong>4</strong> refuellings use this station" in page
    select = re.search(r'<select id="i-move_to_id".*?</select>', page, re.S).group(0)
    options = re.findall(r'<option value="(\d*)"[^>]*>([^<]*)</option>', select)
    assert options == [("", "No station"), (str(beta), "Beta")]

    _post(client, f"/stations/{alpha}/delete", {"move_to_id": str(beta)})
    assert _station_refuel_counts(engine) == {"Beta": 5}
    rows = {r[0]: r for r in _price_rows(client.get("/stats", params=ALL_TIME).text)}
    assert "Alpha" not in rows and rows["Beta"][1] == "5"


def test_delete_station_without_target_clears_the_station(
    client: TestClient, engine: Engine
) -> None:
    _build_scenario(client)
    _post(client, f"/stations/{_station_id(client, 'Beta')}/delete", {"move_to_id": ""})
    assert _station_refuel_counts(engine) == {"Alpha": 4}
    with Session(engine) as session:
        assert session.scalar(select(func.count(Refuel.id))) == 5


def test_delete_unused_station_only_confirms(client: TestClient, engine: Engine) -> None:
    _build_scenario(client)
    vid = _vehicle_id(client, "Golf")
    _add_refuel(client, vid, date(2025, 6, 1), 12000, litres="10",
                price_per_litre="1.5", new_station_name="Spare")  # fmt: skip
    spare = _station_id(client, "Spare")
    with Session(engine) as session:
        session.execute(Refuel.__table__.update().where(Refuel.station_id == spare)
                        .values(station_id=None))
        session.commit()
    page = client.get(f"/stations/{spare}/delete").text
    assert "No refuelling uses this station" in page and "move_to_id" not in page
    _post(client, f"/stations/{spare}/delete", {})
    assert "Spare" not in _station_refuel_counts(engine)


def test_delete_station_rejects_itself_and_unknown_target(
    client: TestClient, engine: Engine
) -> None:
    _build_scenario(client)
    alpha = _station_id(client, "Alpha")
    for bad in (str(alpha), "9999", "abc"):
        response = client.post(f"/stations/{alpha}/delete", data={"move_to_id": bad})
        assert response.status_code == 422
    assert _station_refuel_counts(engine) == {"Alpha": 4, "Beta": 1}
    assert client.get("/stations/9999/delete").status_code == 404


def test_station_edit_dialog_offers_delete(client: TestClient) -> None:
    _build_scenario(client)
    alpha = _station_id(client, "Alpha")
    assert f'href="/stations/{alpha}/delete"' in client.get(f"/stations/{alpha}/edit").text


def test_import_undo_after_moving_a_station_keeps_the_target(
    client: TestClient, engine: Engine, fixtures_dir: Path
) -> None:
    _post(client, "/vehicles/new", {"name": "Existing"})
    vid = _vehicle_id(client, "Existing")
    _add_refuel(client, vid, date(2020, 1, 1), 1, litres="10", price_per_litre="1",
                new_station_name="Keep")  # fmt: skip
    name, answers, _ = IMPORT_CASES[1]
    _import_file(client, name, (fixtures_dir / name).read_bytes(), answers)
    keep = _station_id(client, "Keep")
    with Session(engine) as session:
        imported = session.scalars(
            select(Station.id).where(Station.import_batch_id.is_not(None))
        ).all()
    assert imported
    for station_id in imported:
        _post(client, f"/stations/{station_id}/delete", {"move_to_id": str(keep)})

    batch_id = int(re.search(r"/import/(\d+)/undo", client.get("/import").text).group(1))
    _post(client, f"/import/{batch_id}/undo", {})
    assert _station_refuel_counts(engine) == {"Keep": 1}


def test_preset_lock_unlock_and_duplicate_through_the_forms(client: TestClient) -> None:
    toml = 'name = "Bank"\nnote = "first"\n[fields]\ndate = { column = "when" }\n'
    client.post("/presets/upload", files={"file": ("bank.toml", toml.encode())})
    pid = "user-bank"
    assert "<textarea" in client.get(f"/presets/{pid}").text

    _post(client, f"/presets/{pid}/lock", {"locked": "1"})
    locked = client.get(f"/presets/{pid}").text
    assert "<textarea" not in locked and "Locked. Unlock it to edit" in locked
    assert "Unlock" in locked and "Duplicate" in locked and "Locked" in client.get("/presets").text
    assert client.post(f"/presets/{pid}/edit", data={"note": "x"}).status_code == 403
    refused = client.post(f"/presets/{pid}/delete")
    assert refused.status_code == 422 and "locked" in refused.text
    assert "Bank" in client.get("/presets").text

    _post(client, f"/presets/{pid}/duplicate", {})
    _post(client, f"/presets/{pid}/duplicate", {})
    listing = client.get("/presets").text
    assert "Bank (copy)" in listing and "Bank (copy 2)" in listing
    assert "<textarea" in client.get("/presets/user-bank-copy").text  # copy is unlocked
    _post(client, "/presets/user-bank-copy/edit", {"note": "changed"})
    assert "changed" in client.get("/presets/user-bank-copy/download").text
    assert "first" in client.get(f"/presets/{pid}/download").text

    _post(client, f"/presets/{pid}/lock", {"locked": "0"})
    assert "<textarea" in client.get(f"/presets/{pid}").text
    _post(client, f"/presets/{pid}/delete", {})
    assert client.get(f"/presets/{pid}").status_code == 404


def test_shipped_preset_can_be_duplicated_but_not_locked_or_changed(client: TestClient) -> None:
    assert client.post("/presets/glovebox/lock", data={"locked": "0"}).status_code == 403
    assert client.post("/presets/glovebox/delete").status_code == 422
    _post(client, "/presets/glovebox/duplicate", {})
    copy = client.get("/presets/user-glovebox-copy").text
    assert "<textarea" in copy and "Your preset" in copy


# --- Timeline summary period ------------------------------------------------


def _cards(html: str, group: int = 0) -> dict[str, dict[str, str]]:
    """Label, value and hint of each shown card of the n-th summary grid."""
    grid = html.split('class="summary-grid')[group + 1].split('<div class="chips">')[0]
    cards = {}
    for tag, key, label, value, hint in re.findall(
        r'(<div class="card stat" data-card="(\w+)"[^>]*>)\s*'
        r'<div class="label">(.*?)</div>\s*<div class="value">(.*?)</div>\s*'
        r'<div class="hint">(.*?)</div>',
        grid, re.S,
    ):
        if "hidden" not in tag:
            cards[key] = {"label": _text(label), "value": _text(value), "hint": _text(hint)}
    return cards


def _chip(html: str, nth: int = 0) -> str:
    """Label of the n-th period chip."""
    return _text(re.findall(r'<summary class="chip period-chip[^>]*>(.*?)</summary>', html, re.S)[nth])


def _period_post(client: TestClient, owner: str, period: str, **dates: str) -> None:
    _post(client, "/preferences/period", {"owner": owner, "period": period, **dates})


def test_period_defaults_to_last_12_months(client: TestClient) -> None:
    _two_vehicles(client)
    assert _chip(client.get("/").text) == "Last 12 months"


def test_cards_for_a_custom_range_match_hand_computation(client: TestClient) -> None:
    vid = _build_scenario(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(vid)})
    _period_post(client, str(vid), "custom", date_from="2025-01-01", date_to="2025-05-31")
    html = client.get("/").text
    assert _chip(html) == "1 Jan – 31 May"
    cards = _cards(html)
    # fuel 209.50 + service 100 + insurance 151 days at 1.00
    assert cards["cost_month"]["label"] == "Cost"
    assert cards["cost_month"]["value"] == "460.50 €"
    assert cards["cost_month"]["hint"] == "No full earlier period to compare"
    assert cards["consumption"]["value"].startswith("5.56")
    assert cards["consumption"]["hint"] == "1 Jan – 31 May 2025"
    assert cards["cost_km"]["hint"] == "All costs, 1 Jan – 31 May 2025"
    _post(client, "/preferences/cards", {"card": ["avg_price"]})
    # 209.50 EUR for 140 L
    assert _cards(client.get("/").text)["avg_price"]["value"].startswith("1.496")


def test_cost_card_compares_with_the_preceding_range(client: TestClient) -> None:
    vid = _build_scenario(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(vid)})
    _add_expense(client, vid, date(2024, 11, 15), category="other", title="Early", amount="5")
    _period_post(client, str(vid), "custom", date_from="2025-03-01", date_to="2025-05-31")
    cost = _cards(client.get("/").text)["cost_month"]
    # 49 + 22.50 + 30 fuel, 92 insurance, 100 service = 293.50; before: 108 + 59 = 167
    assert cost["value"] == "293.50 €"
    assert cost["hint"] == "+126.50 € vs previous 92 days"


def test_period_without_refuelling_shows_dashes(client: TestClient) -> None:
    vid = _build_scenario(client)
    _post(client, "/preferences/vehicle", {"vehicle": str(vid)})
    _post(client, "/preferences/cards", {"card": ["cost_month", "consumption",
          "last_refuel", "cost_km", "avg_price"]})
    _period_post(client, str(vid), "month")  # nothing in the current month
    cards = _cards(client.get("/").text)
    assert cards["cost_month"]["label"] == "Cost this month"
    for key in ("consumption", "cost_km", "avg_price"):
        assert cards[key]["value"] == "–"
        assert cards[key]["hint"] == "No refuelling in period"
    assert cards["last_refuel"]["value"] != "–"  # ignores the period


def test_period_is_remembered_per_vehicle_and_across_views(client: TestClient) -> None:
    golf, clio = _two_vehicles(client)
    _period_post(client, str(golf), "30d")
    _period_post(client, "combined", "all")
    html = client.get("/").text  # All vehicles: combined chip, then Clio, then Golf (by name)
    assert [_chip(html, i) for i in range(3)] == ["All time", "Last 12 months", "Last 30 days"]
    _post(client, "/preferences/vehicle", {"vehicle": str(golf)})
    assert _chip(client.get("/").text) == "Last 30 days"
    _post(client, "/preferences/vehicle", {"vehicle": str(clio)})
    assert _chip(client.get("/").text) == "Last 12 months"


def test_period_survives_a_restart(
    settings: Settings, engine: Engine, client: TestClient
) -> None:
    golf, _ = _two_vehicles(client)
    _period_post(client, str(golf), "custom", date_from="2025-06-01", date_to="2025-06-30")
    with TestClient(create_app(settings, engine)) as restarted:
        _post(restarted, "/preferences/vehicle", {"vehicle": str(golf)})
        assert _chip(restarted.get("/").text) == "1 Jun – 30 Jun"


def test_period_form_validation(client: TestClient) -> None:
    golf, _ = _two_vehicles(client)
    for data in (
        {"owner": "x", "period": "30d"},
        {"owner": str(golf), "period": "week"},
        {"owner": str(golf), "period": "custom"},
        {"owner": str(golf), "period": "custom", "date_from": "nope", "date_to": "2025-01-01"},
    ):
        assert client.post("/preferences/period", data=data).status_code == 422, data


def test_period_redirects_back_and_ignores_external_next(client: TestClient) -> None:
    response = client.post(
        "/preferences/period",
        data={"owner": "combined", "period": "year", "next": "https://evil.example/"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303) and response.headers["location"] == "/"


def test_no_comparison_when_the_earlier_period_is_only_partly_covered(client: TestClient) -> None:
    vid = _build_scenario(client)  # first record 2025-01-10
    _post(client, "/preferences/vehicle", {"vehicle": str(vid)})
    # earlier period 2024-12-01 .. 2025-02-28 starts before the first record
    _period_post(client, str(vid), "custom", date_from="2025-03-01", date_to="2025-05-31")
    assert _cards(client.get("/").text)["cost_month"]["hint"] == "No full earlier period to compare"
    # earlier period 2025-01-10 .. 2025-02-28 starts on the first record: full coverage
    _period_post(client, str(vid), "custom", date_from="2025-03-01", date_to="2025-04-19")
    hint = _cards(client.get("/").text)["cost_month"]["hint"]
    assert hint.endswith("vs previous 50 days") and hint[0] in "+-"


# --- Vehicle details ----------------------------------------------------------

DETAILS = {
    "name": "Golf", "vin": "wvwzzz1kz6w000001", "model_year": "2018",
    "engine": "1.5 TSI, 96 kW", "tyre_size": "205/55 R16",
    "insurance_policy": "POL-2026-0042", "insurance_valid_until": "2027-03-14",
    "registration_valid_until": "2027-05-30",
}  # fmt: skip


def _fold_of(html: str) -> str:
    """The opening tag and summary text of the "More details" card."""
    match = re.search(r'<details class="card fold"([^>]*)>\s*<summary>(.*?)</summary>', html, re.S)
    assert match, "More details card not found"
    return f"{match.group(1)}|{_text(match.group(2))}"


def test_vehicle_form_stores_details_and_keeps_them_folded(client: TestClient) -> None:
    _post(client, "/vehicles/new", DETAILS)
    vehicle_id = _vehicle_id(client, "Golf")
    form = client.get(f"/vehicles/{vehicle_id}/edit").text
    assert 'value="WVWZZZ1KZ6W000001"' in form
    assert 'value="2027-03-14"' in form
    assert 'data-copy="i-vin"' in form
    folded, summary = _fold_of(form).split("|")
    assert "open" not in folded
    assert summary == "More details 7 filled"

    row = client.get("/vehicles").text
    assert "2018 · 1.5 TSI, 96 kW · 205/55 R16" in _text(row)
    assert "Insurance until 14 Mar 2027 · Registration until 30 May 2027" in _text(row)
    assert "WVWZZZ1KZ6W000001" not in row


def test_vehicle_form_without_details_says_nothing_filled(client: TestClient) -> None:
    _post(client, "/vehicles/new", {"name": "Golf"})
    form = client.get(f"/vehicles/{_vehicle_id(client, 'Golf')}/edit").text
    assert _fold_of(form).endswith("|More details")


@pytest.mark.parametrize(
    "bad",
    [{"model_year": "19xx"}, {"model_year": "1700"}, {"insurance_valid_until": "2027-13-40"}],
)
def test_vehicle_form_error_opens_details_and_keeps_input(
    client: TestClient, bad: dict
) -> None:
    response = client.post("/vehicles/new", data={**DETAILS, **bad})
    assert response.status_code == 422
    folded, _ = _fold_of(response.text).split("|")
    assert "open" in folded
    assert 'value="205/55 R16"' in response.text
    assert list(bad.values())[0] in response.text


def test_other_form_error_leaves_details_folded(client: TestClient) -> None:
    response = client.post("/vehicles/new", data={**DETAILS, "name": ""})
    assert response.status_code == 422
    assert "open" not in _fold_of(response.text).split("|")[0]


def test_backup_with_details_restores_them(
    client: TestClient, second_app: tuple[TestClient, Engine]
) -> None:
    _post(client, "/vehicles/new", DETAILS)
    exported = _backup(client)
    tables = _tables(exported)
    assert "vin,model_year,engine,tyre_size" in tables["vehicles.csv"]
    assert "WVWZZZ1KZ6W000001,2018,\"1.5 TSI, 96 kW\",205/55 R16,POL-2026-0042,2027-03-14,2027-05-30" in tables["vehicles.csv"]
    assert '"name": "registration_valid_until"' in zipfile.ZipFile(io.BytesIO(exported)).read("datapackage.json").decode()

    other, other_engine = second_app
    _import_file(other, "backup.zip", exported)
    with Session(other_engine) as session:
        golf = session.scalar(select(Vehicle))
        assert (golf.vin, golf.model_year, golf.engine, golf.tyre_size) == (
            "WVWZZZ1KZ6W000001", 2018, "1.5 TSI, 96 kW", "205/55 R16",
        )
        assert golf.insurance_policy == "POL-2026-0042"
        assert golf.insurance_valid_until == date(2027, 3, 14)
        assert golf.registration_valid_until == date(2027, 5, 30)
    assert _tables(_backup(other)) == tables


OLD_BACKUP_RECORDS = (
    "type,vehicle,date,odometer_km,fuel_l,price_per_l,total,station,station_location\n"
    "refuel,Golf,2025-01-10,10000,40,1.5,60.00,Alpha,Celje\n"
)


def _zip_of(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, content in members.items():
            archive.writestr(member, content)
    return buffer.getvalue()


def test_backup_from_before_vehicle_details_still_restores(
    client: TestClient, engine: Engine
) -> None:
    old = _zip_of({
        "records.csv": OLD_BACKUP_RECORDS,
        "vehicles.csv": (
            "name,make,model,plate,fuel_type,initial_odometer_km,archived,notes\n"
            "Golf,VW,Golf VII,LJ AB-123,Diesel,85000,false,Company car\n"
        ),
        "stations.csv": "name,location,brand\nAlpha,Celje,OMV\n",
        "datapackage.json": '{"name": "glovebox-standard-format", "resources": []}',
    })
    html = _import_file(client, "old.zip", old)
    assert "Rows with errors" not in html
    with Session(engine) as session:
        golf = session.scalar(select(Vehicle))
        assert (golf.make, golf.initial_odometer, golf.notes) == ("VW", 85000, "Company car")
        assert golf.vin is None and golf.model_year is None


def test_unreadable_vehicle_detail_is_a_row_error_not_a_failure(
    client: TestClient, engine: Engine
) -> None:
    broken = _zip_of({
        "records.csv": OLD_BACKUP_RECORDS,
        "vehicles.csv": (
            "name,vin,model_year,insurance_valid_until\nGolf,WVWZZZ1KZ6W000001,abcd,soon\n"
        ),
    })
    html = _import_file(client, "broken.zip", broken)
    assert "model_year" in html and "insurance_valid_until" in html
    with Session(engine) as session:
        golf = session.scalar(select(Vehicle))
        assert golf.vin == "WVWZZZ1KZ6W000001"
        assert golf.model_year is None and golf.insurance_valid_until is None


def test_existing_vehicle_is_only_completed_with_details(
    client: TestClient, engine: Engine
) -> None:
    _post(client, "/vehicles/new", {"name": "Golf", "vin": "KEEPME"})
    data = _zip_of({
        "records.csv": OLD_BACKUP_RECORDS,
        "vehicles.csv": "name,vin,tyre_size\nGolf,OTHER,205/55 R16\n",
    })
    _import_file(client, "fill.zip", data)
    with Session(engine) as session:
        golf = session.scalar(select(Vehicle))
        assert (golf.vin, golf.tyre_size) == ("KEEPME", "205/55 R16")
