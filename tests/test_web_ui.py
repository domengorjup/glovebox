"""
Web UI tests (task group 6).

Service functions are monkeypatched, so these tests check the pages and the
way they call the services, not the services themselves.
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from glovebox.exporters import fuelly as fuelly_exporter
from glovebox.exporters import native as native_exporter
from glovebox.exporters.fuelly import ExportFile
from glovebox.importers import pipeline
from glovebox.importers.base import Ambiguity, HeaderMismatch
from glovebox.importers.pipeline import ImportPreview
from glovebox.models import (
    DerivedField,
    Expense,
    ExpenseCategory,
    ImportBatch,
    Refuel,
    Station,
    Vehicle,
)
from glovebox.services import records, stats
from glovebox.services.records import (
    ConfirmationRequired,
    DerivedFigures,
    RecordCounts,
    RefuelPreview,
    ValidationError,
)
from glovebox.services.stats import (
    Allocation,
    CostBreakdown,
    CostPerKm,
    PeriodCost,
    Segment,
    StationStat,
)

PREFIX = "/api/hassio_ingress/abc123"
INGRESS = {"X-Ingress-Path": PREFIX}
URL_ATTRIBUTE = re.compile(r'(?:href|src|action|formaction)="([^"]*)"')


def make_vehicle(vehicle_id: int = 1, name: str = "Golf", archived: bool = False):
    return Vehicle(id=vehicle_id, name=name, make="VW", model="Golf", plate=None,
                   fuel_type=None, initial_odometer=None, archived=archived,
                   notes=None)


def make_station(station_id: int = 1, name: str = "Petrol Trzaska", brand=None):
    return Station(id=station_id, name=name, brand=brand, location=None)


def make_refuel(refuel_id: int = 1):
    return Refuel(id=refuel_id, vehicle_id=1, date=date(2026, 5, 2), time=None,
                  odometer_km=98000.0, litres_milli=40000,
                  price_per_litre_milli=1500, total_cents=6000,
                  derived_field=DerivedField.TOTAL, station_id=1, is_full=True,
                  missed_previous=False, notes=None)


def make_expense(expense_id: int = 1):
    return Expense(id=expense_id, vehicle_id=1, date=date(2026, 3, 1),
                   odometer_km=None, category=ExpenseCategory.INSURANCE,
                   title="Annual policy", amount_cents=42000,
                   coverage_start=date(2026, 3, 1),
                   coverage_end=date(2027, 2, 28), notes=None)


def make_segment(refuel_id: int, consumption: float | None):
    return Segment(vehicle_id=1, start_refuel_id=None, end_refuel_id=refuel_id,
                   end_date=date(2026, 5, 2), station_id=1, single_station=True,
                   distance_km=600.0, litres_milli=40000,
                   consumption=consumption, valid=consumption is not None,
                   invalid_reason=None if consumption else "missed")


@pytest.fixture
def calls() -> dict[str, list]:
    """Arguments of the mutating/inspected service calls, by function name."""
    return {}


@pytest.fixture(autouse=True)
def fake_services(monkeypatch, calls):
    """Replace every service the pages use with a recording fake."""

    def record(name, result=None):
        def fake(*args, **kwargs):
            calls.setdefault(name, []).append((args[1:], kwargs))
            return result(*args, **kwargs) if callable(result) else result

        monkeypatch.setattr(records, name, fake)

    record("list_vehicles", [make_vehicle()])
    record("get_vehicle", make_vehicle())
    record("create_vehicle", make_vehicle())
    record("update_vehicle", make_vehicle())
    record("archive_vehicle", make_vehicle())
    record("count_vehicle_records", RecordCounts(refuels=12, expenses=3))
    record("delete_vehicle")
    record("list_stations", [make_station(1), make_station(2, "OMV Celje")])
    record("get_station", make_station())
    record("create_station", make_station(7, "New one"))
    record("update_station", make_station())
    record("set_brand_bulk", [])
    record("merge_stations", make_station())
    record("list_refuels", [make_refuel()])
    record("get_refuel", make_refuel())
    record("create_refuel", make_refuel())
    record("update_refuel", make_refuel())
    record("delete_refuel")
    figures = DerivedFigures(40000, 1500, 6000, DerivedField.TOTAL)
    record("preview_refuel", RefuelPreview(figures=figures))
    record("list_expenses", [make_expense()])
    record("get_expense", make_expense())
    record("create_expense", make_expense())
    record("update_expense", make_expense())
    record("delete_expense")

    monkeypatch.setattr(
        stats, "vehicle_summary",
        lambda session, vehicle_id, today=None: SimpleNamespace(
            cost_this_month_cents=6000, last_refuel=None, last_odometer_km=98000.0),
    )
    monkeypatch.setattr(stats, "segments", lambda refuels: [make_segment(1, 6.67)])
    monkeypatch.setattr(stats, "avg_consumption", lambda segs: 6.67 if segs else None)
    by_category = {c: 0 for c in ExpenseCategory} | {ExpenseCategory.INSURANCE: 3100}
    breakdown = CostBreakdown(
        allocation=Allocation.SPREAD,
        fuel_cents=6000,
        by_category=by_category,
        monthly=[PeriodCost("2026-05", 6000, by_category)],
        yearly=[PeriodCost("2026", 6000, by_category)],
    )

    def fake_breakdown(session, flt, allocation=Allocation.SPREAD):
        calls.setdefault("cost_breakdown", []).append((flt, allocation))
        return breakdown

    monkeypatch.setattr(stats, "cost_breakdown", fake_breakdown)
    monkeypatch.setattr(
        stats, "cost_per_km",
        lambda session, flt, allocation=Allocation.SPREAD: CostPerKm(
            allocation, 9100, 600.0, 0.152),
    )
    monkeypatch.setattr(
        stats, "station_stats",
        lambda session, flt, group_by=stats.GroupBy.STATION: [
            StationStat(1, "Petrol Trzaska", 3, 100000, 1450, 1400, 1500, None, 1)],
    )

    monkeypatch.setattr(pipeline, "available_formats",
                        lambda: [SimpleNamespace(name="fuelio"),
                                 SimpleNamespace(name="native")])
    monkeypatch.setattr(pipeline, "list_batches", lambda session: [
        ImportBatch(id=5, format="fuelio", filename="a.csv",
                    created_at=__import__("datetime").datetime(2026, 1, 2, 3, 4),
                    refuels_imported=10, expenses_imported=2, duplicates_skipped=1)])


def use_vehicles(monkeypatch, *vehicles):
    """Make the faked vehicle lookups consistent with this list (get raises if unknown)."""
    def listing(session, include_archived=False):
        return [v for v in vehicles if include_archived or not v.archived]

    def get(session, vehicle_id):
        for v in vehicles:
            if v.id == vehicle_id:
                return v
        raise records.NotFoundError(f"Vehicle {vehicle_id} does not exist")

    monkeypatch.setattr(records, "list_vehicles", listing)
    monkeypatch.setattr(records, "get_vehicle", get)
    return list(vehicles)


def urls_in(html: str) -> list[str]:
    return URL_ATTRIBUTE.findall(html)


PAGES = [
    "/", "/?type=refuel", "/stats", "/manage", "/add",
    "/vehicles", "/vehicles/new", "/vehicles/1/edit", "/vehicles/1/delete",
    "/refuels/new", "/refuels/1/edit",
    "/expenses/new", "/expenses/new?kind=service", "/expenses/1/edit",
    "/stations", "/stations/1/edit", "/import", "/export",
]


# --- 6.1 / 6.8 rendering, prefixes, offline -------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_at_root(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    for target in urls_in(response.text):
        assert target.startswith("/") and not target.startswith("//"), target


@pytest.mark.parametrize("path", PAGES)
def test_page_urls_carry_ingress_prefix(client, path):
    response = client.get(path, headers=INGRESS)
    assert response.status_code == 200, response.text
    targets = urls_in(response.text)
    assert targets
    assert all(t.startswith(PREFIX + "/") for t in targets), targets


@pytest.mark.parametrize("path", PAGES)
def test_pages_reference_no_external_hosts(client, path):
    html = client.get(path).text
    assert not re.search(r"""(?:https?:)?//[\w.-]+\.\w+""", html)


def test_bundled_assets_are_served(client):
    for name in ("app.js", "app.css", "theme.js", "icons.svg"):
        assert client.get(f"/static/{name}").status_code == 200, name


def test_removed_libraries_are_gone(client):
    for name in ("pico.min.css", "chart.umd.min.js", "color.min.js"):
        assert client.get(f"/static/{name}").status_code == 404, name


def test_icon_sprite_url_carries_prefix(client):
    html = client.get("/", headers=INGRESS).text
    assert f"{PREFIX}/static/icons.svg#" in html


def test_pages_have_no_unreplaced_template_text(client):
    for path in PAGES:
        assert "{{" not in client.get(path).text and "{%" not in client.get(path).text


# --- timeline -------------------------------------------------------------


def test_timeline_lists_entries_grouped_by_month(client):
    html = client.get("/").text
    assert "May 2026" in html and "March 2026" in html
    assert 'href="/refuels/1/edit"' in html and 'href="/expenses/1/edit"' in html
    assert "Annual policy" in html and "Refuelling" in html


def test_timeline_type_chip_filters(client):
    html = client.get("/?type=expense").text
    assert "Annual policy" in html and 'href="/refuels/1/edit"' not in html


def test_timeline_unknown_type_is_rejected(client):
    assert client.get("/?type=parking").status_code == 422


def test_timeline_shows_consumption_or_dash_for_cards(client, monkeypatch):
    assert "6.67" in client.get("/").text
    monkeypatch.setattr(stats, "avg_consumption", lambda segs: None)
    assert 'data-card="consumption"' in client.get("/").text


def test_timeline_numbers_do_not_break_across_lines(client):
    html = client.get("/").text
    assert "420.00\u00a0EUR" in html


def test_add_chooser_links_to_the_three_forms(client):
    html = client.get("/add").text
    assert 'href="/refuels/new"' in html
    assert 'href="/expenses/new?kind=service"' in html
    assert 'href="/expenses/new"' in html


def test_dialog_request_returns_only_the_content(client):
    page = client.get("/refuels/new").text
    dialog = client.get("/refuels/new", headers={"X-Glovebox-Dialog": "1"}).text
    assert "<html" in page and "<html" not in dialog and 'name="odometer_km"' in dialog


def test_service_form_posts_maintenance(client):
    html = client.get("/expenses/new?kind=service").text
    assert 'name="category" value="maintenance"' in html


def test_expense_form_offers_no_maintenance_category(client):
    html = client.get("/expenses/new").text
    assert 'value="insurance"' in html and 'value="maintenance"' not in html


# --- stats ----------------------------------------------------------------


def test_stats_filter_is_applied(client, calls):
    url = ("/stats?what=all&when=custom&date_from=2026-01-01&date_to=2026-12-31"
           "&allocation=paid")
    response = client.get(url)
    assert response.status_code == 200
    flt, allocation = calls["cost_breakdown"][0]
    assert flt.date_from == date(2026, 1, 1) and flt.date_to == date(2026, 12, 31)
    assert allocation is Allocation.PAID
    assert 'value="2026-01-01"' in response.text


def test_stats_default_allocation_is_spread(client, calls):
    client.get("/stats")
    assert calls["cost_breakdown"][0][1] is Allocation.SPREAD


def test_stats_follow_the_selected_vehicle(client, calls):
    client.get("/stats")
    assert calls["cost_breakdown"][0][0].vehicles == ()
    client.post("/preferences/vehicle", data={"vehicle": "1"})
    client.get("/stats")
    assert calls["cost_breakdown"][1][0].vehicles == (1,)


def test_stats_choice_links_keep_prefix_and_filters(client):
    html = client.get("/stats?allocation=paid&what=expense", headers=INGRESS).text
    assert f'href="{PREFIX}/stats?' in html and "allocation=paid" in html


def test_stats_spread_choice_only_with_expenses(client):
    assert "As paid" in client.get("/stats?what=all").text
    assert "As paid" not in client.get("/stats?what=refuel").text


def test_stats_invalid_values_are_rejected(client):
    assert client.get("/stats?allocation=weekly").status_code == 422
    assert client.get("/stats?what=parking").status_code == 422
    assert client.get("/stats?date_from=yesterday").status_code == 422


def test_stats_embeds_chart_data_and_caveat(client):
    html = client.get("/stats").text
    assert 'id="chart-data"' in html
    assert "mixed-station tanks are left out" in html
    assert "6.67" in html


def test_stats_price_table_by_station_and_brand(client):
    assert "data-price-table" in client.get("/stats").text
    assert "Brand" in client.get("/stats?group=brand").text


def test_all_vehicles_includes_archived_history(client, calls, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Old", True))
    client.get("/stats")
    assert calls["cost_breakdown"][0][0].vehicles == ()


# --- preferences ----------------------------------------------------------


def test_selected_vehicle_is_remembered_across_clients(client, settings, engine):
    from fastapi.testclient import TestClient

    from glovebox.app import create_app

    client.post("/preferences/vehicle", data={"vehicle": "1"})
    with TestClient(create_app(settings, engine)) as other:
        assert re.search(r'<option value="1"[^>]*selected', other.get("/").text)


def test_all_vehicles_does_not_overwrite_last_vehicle(client):
    client.post("/preferences/vehicle", data={"vehicle": "1"})
    client.post("/preferences/vehicle", data={"vehicle": "all"})
    html = client.get("/refuels/new").text
    assert re.search(r'<option value="1"[^>]*selected', html)


def test_vehicle_preference_validation(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle())
    assert client.post("/preferences/vehicle", data={"vehicle": "abc"}).status_code == 422
    assert client.post("/preferences/vehicle", data={"vehicle": "99"}).status_code == 404


def test_vehicle_preference_redirects_under_prefix(client):
    response = client.post("/preferences/vehicle", data={"vehicle": "1", "next": "/stats"},
                           headers=INGRESS, follow_redirects=False)
    assert response.headers["location"] == f"{PREFIX}/stats"


def test_vehicle_preference_rejects_external_next(client):
    response = client.post("/preferences/vehicle",
                           data={"vehicle": "1", "next": "https://evil.example/x"},
                           follow_redirects=False)
    assert response.headers["location"] == "/"


def test_summary_card_choice_is_stored_and_unknown_names_ignored(client):
    client.post("/preferences/cards", data={"card": ["odometer", "bogus", "cost_km"]})
    html = client.get("/").text
    shown = {k for k in re.findall(r'data-card="(\w+)"\s*>', html)}
    assert shown == {"odometer", "cost_km"}
    hidden = re.findall(r'data-card="(\w+)"\s+hidden', html)
    assert "cost_month" in hidden and "odometer" not in hidden


def test_summary_cards_default_when_nothing_stored(client):
    html = client.get("/").text
    assert re.search(r'data-card="cost_month"\s*>', html)
    assert re.search(r'data-card="odometer"\s+hidden', html)


def test_summary_cards_can_all_be_switched_off(client):
    client.post("/preferences/cards", data={})
    assert not re.findall(r'data-card="\w+"\s*>', client.get("/").text)


def test_form_vehicle_defaults_to_navbar_vehicle(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    client.post("/preferences/vehicle", data={"vehicle": "2"})
    html = client.get("/refuels/new").text
    assert re.search(r'<option value="2"[^>]*selected', html)


def test_form_vehicle_with_all_vehicles_uses_last_specific(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    client.post("/preferences/vehicle", data={"vehicle": "2"})
    client.post("/preferences/vehicle", data={"vehicle": "all"})
    for path in ("/refuels/new", "/expenses/new"):
        assert re.search(r'<option value="2"[^>]*selected', client.get(path).text), path


def test_form_vehicle_ignores_archived_last_vehicle(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    client.post("/preferences/vehicle", data={"vehicle": "2"})
    client.post("/preferences/vehicle", data={"vehicle": "all"})
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo", archived=True))
    html = client.get("/refuels/new").text
    assert 'value="2"' not in html.split('name="vehicle_id"')[1].split("</select>")[0]


def test_every_form_has_a_vehicle_dropdown(client):
    for path in ("/refuels/new", "/refuels/1/edit", "/expenses/new",
                 "/expenses/new?kind=service", "/expenses/1/edit"):
        assert '<select id="i-vehicle_id" name="vehicle_id"' in client.get(path).text, path


def test_app_bar_lists_vehicles_and_all_option(client):
    html = client.get("/").text
    assert 'value="all"' in html and "All vehicles" in html and "Golf" in html


def test_app_bar_hides_archived_vehicles(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Retired", True))
    assert "Retired" not in client.get("/").text.split("</header>")[0]


# --- 6.2 vehicles ---------------------------------------------------------


def test_vehicle_delete_page_shows_counts(client):
    html = client.get("/vehicles/1/delete").text
    assert "<strong>12</strong> refuels" in html and "<strong>3</strong> expenses" in html


def test_vehicle_delete_needs_confirmation(client, monkeypatch):
    def refuse(session, vehicle_id, *, confirm=False):
        raise ConfirmationRequired(12, 3)

    monkeypatch.setattr(records, "delete_vehicle", refuse)
    response = client.post("/vehicles/1/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/vehicles/1/delete")


def test_vehicle_delete_with_confirm(client, calls):
    client.post("/vehicles/1/delete", data={"confirm": "1"}, follow_redirects=False)
    assert calls["delete_vehicle"][0][1] == {"confirm": True}


def test_vehicle_create_shows_validation_message(client, monkeypatch):
    def reject(session, data):
        raise ValidationError(["Name 'Golf' is already used"])

    monkeypatch.setattr(records, "create_vehicle", reject)
    response = client.post("/vehicles/new", data={"name": "Golf"})
    assert response.status_code == 422
    assert "already used" in response.text and 'value="Golf"' in response.text


def test_vehicle_create_redirects_under_prefix(client, calls):
    response = client.post("/vehicles/new", data={"name": " Polo ", "initial_odometer": "1000,5"},
                           headers=INGRESS, follow_redirects=False)
    assert response.headers["location"] == f"{PREFIX}/vehicles"
    data = calls["create_vehicle"][0][0][0]
    assert data.name == "Polo" and data.initial_odometer == 1000.5 and data.make is None


def test_vehicle_list_shows_secondary_text_and_stats(client):
    html = client.get("/vehicles").text
    assert "VW Golf" in html and "records" in html


def test_archived_vehicles_sit_in_a_collapsible_section(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Retired", True))
    html = client.get("/vehicles").text
    assert "<details" in html and "Archived (1)" in html and "Retired" in html


def test_vehicle_archive_and_restore(client, calls):
    client.post("/vehicles/1/archive", data={"archived": "0"}, follow_redirects=False)
    assert calls["archive_vehicle"][0][0] == (1, False)


# --- 6.3 refuels ----------------------------------------------------------


def test_timeline_refuel_shows_consumption_and_hides_na(client, monkeypatch):
    assert "6.67 L/100 km" in client.get("/").text.replace("\u00a0", " ")
    monkeypatch.setattr(stats, "segments", lambda r: [make_segment(1, None)])
    monkeypatch.setattr(stats, "avg_consumption", lambda segs: None)
    html = client.get("/").text.replace("\u00a0", " ")
    assert "6.67" not in html and "\u2013" in html


def test_refuel_two_of_three_entry(client, calls):
    form = {"vehicle_id": "1", "date": "2026-05-02", "odometer_km": "98000",
            "litres": "40,00", "total": "60.00", "is_full": "1"}
    response = client.post("/refuels/new", data=form, follow_redirects=False)
    assert response.status_code == 303
    data = calls["create_refuel"][0][0][0]
    assert (data.litres_milli, data.price_per_litre_milli, data.total_cents) == (
        40000, None, 6000)
    assert data.is_full is True and data.missed_previous is False


def test_refuel_warning_is_shown_before_save(client, calls, monkeypatch):
    figures = DerivedFigures(40000, 1500, 7000, None)
    monkeypatch.setattr(records, "preview_refuel", lambda s, d, exclude_id=None:
                        RefuelPreview(figures, ["Total differs from litres x price by 16 %"]))
    form = {"vehicle_id": "1", "date": "2026-05-02", "odometer_km": "98000",
            "litres": "40", "price_per_litre": "1.5", "total": "70"}
    response = client.post("/refuels/new", data=form)
    assert response.status_code == 200
    assert "differs" in response.text and "Save anyway" in response.text
    assert "create_refuel" not in calls
    form["confirm_warnings"] = "1"
    assert client.post("/refuels/new", data=form, follow_redirects=False).status_code == 303
    assert len(calls["create_refuel"]) == 1


def test_refuel_inline_station_creation(client, calls):
    form = {"vehicle_id": "1", "date": "2026-05-02", "odometer_km": "98000",
            "litres": "40", "total": "60", "new_station_name": "New one"}
    client.post("/refuels/new", data=form, follow_redirects=False)
    assert calls["create_station"][0][0][0].name == "New one"
    assert calls["create_refuel"][0][0][0].station_id == 7


def test_refuel_service_error_is_shown(client, monkeypatch):
    def reject(session, data, exclude_id=None):
        raise ValidationError(["Give at least two of litres, price and total"])

    monkeypatch.setattr(records, "preview_refuel", reject)
    form = {"vehicle_id": "1", "date": "2026-05-02", "odometer_km": "98000", "litres": "40"}
    response = client.post("/refuels/new", data=form)
    assert response.status_code == 422 and "at least two" in response.text


def test_refuel_bad_number_is_reported(client):
    form = {"vehicle_id": "1", "date": "2026-05-02", "odometer_km": "abc"}
    response = client.post("/refuels/new", data=form)
    assert response.status_code == 422 and "not a number" in response.text


def test_refuel_form_never_suggests_a_brand(client):
    html = client.get("/refuels/new").text
    assert 'name="brand"' not in html


def test_refuel_edit_prefills_form(client):
    html = client.get("/refuels/1/edit").text
    assert 'value="98000"' in html and 'value="2026-05-02"' in html


# --- 6.4 expenses ---------------------------------------------------------


def test_expense_create_redirects_to_timeline_under_prefix(client):
    form = {"vehicle_id": "1", "date": "2026-03-01", "category": "insurance",
            "title": "Annual policy", "amount": "420.00"}
    response = client.post("/expenses/new", data=form, headers=INGRESS,
                           follow_redirects=False)
    assert response.headers["location"] == f"{PREFIX}/"


def test_expense_create_with_coverage(client, calls):
    form = {"vehicle_id": "1", "date": "2026-03-01", "category": "insurance",
            "title": "Annual policy", "amount": "420.00",
            "coverage_start": "2026-03-01", "coverage_end": "2027-02-28"}
    assert client.post("/expenses/new", data=form, follow_redirects=False).status_code == 303
    data = calls["create_expense"][0][0][0]
    assert data.amount_cents == 42000 and data.coverage_end == date(2027, 2, 28)


def test_expense_unknown_category_rejected(client, calls):
    form = {"vehicle_id": "1", "date": "2026-03-01", "category": "parking",
            "title": "x", "amount": "5"}
    response = client.post("/expenses/new", data=form)
    assert response.status_code == 422 and "Unknown category" in response.text
    assert "create_expense" not in calls


def test_expense_coverage_error_from_service(client, monkeypatch):
    def reject(session, data):
        raise ValidationError(["Coverage needs both dates"])

    monkeypatch.setattr(records, "create_expense", reject)
    form = {"vehicle_id": "1", "date": "2026-03-01", "category": "insurance",
            "title": "x", "amount": "5", "coverage_start": "2026-03-01"}
    response = client.post("/expenses/new", data=form)
    assert response.status_code == 422 and "both dates" in response.text


# --- 6.5 stations ---------------------------------------------------------


def test_bulk_brand(client, calls):
    response = client.post("/stations/brand", data={"station_ids": ["1", "2"], "brand": " OMV "},
                           follow_redirects=False)
    assert response.status_code == 303
    assert calls["set_brand_bulk"][0][0] == ([1, 2], "OMV")


def test_bulk_clear_brand(client, calls):
    client.post("/stations/brand", data={"station_ids": ["1"], "clear": "1"})
    assert calls["set_brand_bulk"][0][0] == ([1], None)


def test_bulk_brand_requires_selection(client, calls):
    response = client.post("/stations/brand", data={"brand": "OMV"})
    assert response.status_code == 422 and "set_brand_bulk" not in calls


def test_merge(client, calls):
    client.post("/stations/merge", data={"source_id": "1", "target_id": "2"},
                follow_redirects=False)
    assert calls["merge_stations"][0][0] == (1, 2)


def test_merge_same_station_rejected(client, calls):
    response = client.post("/stations/merge", data={"source_id": "1", "target_id": "1"})
    assert response.status_code == 422 and "merge_stations" not in calls


def test_station_rename(client, calls):
    client.post("/stations/1/edit", data={"name": "Petrol Tržaška", "brand": "Petrol"},
                follow_redirects=False)
    data = calls["update_station"][0][0][1]
    assert data.name == "Petrol Tržaška" and data.brand == "Petrol"


# --- 6.7 import / export --------------------------------------------------


def fake_preview(**overrides):
    values = dict(format="fuelio", vehicle_names=["My Golf"], new_refuels=5,
                  new_expenses=1, duplicate_refuels=2, duplicate_expenses=0)
    values.update(overrides)
    return ImportPreview(**values)


def upload(client, headers=None):
    response = client.post("/import/upload",
                           files={"file": ("log.csv", b"a,b\n1,2\n")},
                           data={"format": ""}, headers=headers or {},
                           follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def test_upload_redirects_to_prefixed_preview(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    location = upload(client, INGRESS)
    assert location.startswith(f"{PREFIX}/import/preview?token=")
    page = client.get(location.removeprefix(PREFIX), headers=INGRESS)
    assert page.status_code == 200
    assert all(t.startswith(PREFIX + "/") for t in urls_in(page.text))


def test_preview_shows_mapping_counts_and_duplicates(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    html = client.get(upload(client)).text
    assert "My Golf" in html and "skipped: 2" in html
    assert 'name="maps"' in html and "Import now" in html


def test_preview_preselects_vehicle_with_same_name(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import",
                        lambda *a, **k: fake_preview(vehicle_names=["golf"]))
    html = client.get(upload(client)).text
    assert '<option value="1" selected>' in html


def test_preview_asks_date_order_and_blocks_commit(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k:
                        fake_preview(ambiguities=[Ambiguity.DATE_ORDER]))
    html = client.get(upload(client)).text
    assert 'name="date_order"' in html and "Import now" not in html


def test_preview_header_mismatch_lists_headers(client, monkeypatch):
    mismatch = HeaderMismatch(found=["colA", "colB"], expected=["Odo", "Fuel"])
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k:
                        fake_preview(header_mismatch=mismatch))
    html = client.get(upload(client)).text
    assert "colA, colB" in html and "Odo, Fuel" in html and "Import now" not in html


def test_preview_passes_answers_to_pipeline(client, monkeypatch):
    seen = {}

    def fake(session, data, *, format=None, options=None, mapping=None):
        seen.update(format=format, options=options, mapping=mapping)
        return fake_preview()

    monkeypatch.setattr(pipeline, "preview_import", fake)
    location = upload(client)
    client.get(f"{location}&format=fuelio&date_order=dmy&names=My+Golf&maps=1")
    assert seen["format"] == "fuelio" and seen["options"].date_order == "dmy"
    assert seen["mapping"].by_name == {"My Golf": 1}


def test_commit_uses_mapping_and_removes_upload(client, monkeypatch, settings, calls):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    committed = {}

    def fake_commit(session, data, filename, mapping, *, format=None, options=None):
        committed.update(data=data, filename=filename, mapping=mapping)
        return ImportBatch(id=9)

    monkeypatch.setattr(pipeline, "commit_import", fake_commit)
    token = upload(client).split("token=")[1].split("&")[0]
    response = client.post("/import/commit", data={
        "token": token, "filename": "log.csv", "names": ["My Golf", "Polo"],
        "maps": ["1", "new"]}, headers=INGRESS, follow_redirects=False)
    assert response.headers["location"] == f"{PREFIX}/import"
    assert committed["data"] == b"a,b\n1,2\n" and committed["filename"] == "log.csv"
    assert committed["mapping"].by_name == {"My Golf": 1, "Polo": None}
    assert not list((settings.data_dir / "uploads").glob("*.upload"))


def test_commit_error_returns_to_preview(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())

    def boom(*a, **k):
        raise ValueError("cannot import")

    monkeypatch.setattr(pipeline, "commit_import", boom)
    token = upload(client).split("token=")[1].split("&")[0]
    response = client.post("/import/commit", data={"token": token})
    assert response.status_code == 422 and "cannot import" in response.text


def test_unknown_or_malicious_token_is_404(client):
    assert client.get("/import/preview?token=../../etc/passwd").status_code == 404
    assert client.get("/import/preview?token=" + "0" * 32).status_code == 404


def test_import_page_lists_batches_with_undo(client, monkeypatch):
    html = client.get("/import", headers=INGRESS).text
    assert "a.csv" in html and f'action="{PREFIX}/import/5/undo"' in html
    undone = []
    monkeypatch.setattr(pipeline, "undo_batch", lambda session, batch_id: undone.append(batch_id))
    client.post("/import/5/undo", follow_redirects=False)
    assert undone == [5]


def test_export_page_notes_expenses_omitted(client):
    html = client.get("/export").text
    assert "Expenses are not included" in html
    assert 'action="/export/native"' in html and 'action="/export/fuelly"' in html


def test_native_download(client, monkeypatch):
    seen = []
    monkeypatch.setattr(native_exporter, "export_native",
                        lambda session, settings, ids=None: seen.append(ids) or b"PK-zip")
    response = client.get("/export/native?vehicle=1")
    assert response.content == b"PK-zip" and seen == [[1]]
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in response.headers["content-disposition"]


def test_fuelly_download_all_vehicles(client, monkeypatch):
    seen = []

    def fake(session, ids=None):
        seen.append(ids)
        return ExportFile("golf.csv", "text/csv", b"fuelup_date\n")

    monkeypatch.setattr(fuelly_exporter, "export_fuelly", fake)
    response = client.get("/export/fuelly?vehicle=")
    assert response.content == b"fuelup_date\n" and seen == [None]
    assert 'filename="golf.csv"' in response.headers["content-disposition"]


def test_vehicle_edit_prefills_form(client):
    html = client.get("/vehicles/1/edit").text
    assert 'name="name" value="Golf"' in html and 'name="make" value="VW"' in html
