"""
Web UI tests (task group 6).

Service functions are monkeypatched, so these tests check the pages and the
way they call the services, not the services themselves.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from glovebox.exporters import backup as backup_exporter
from glovebox.exporters import csv_export
from glovebox.importers import pipeline
from glovebox.importers.base import Question, QuestionKind, RowError
from glovebox.importers.pipeline import ImportPreview
from glovebox.importers.presets import load_preset
from glovebox.standard import RECORD_FIELDS
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

    monkeypatch.setattr(pipeline, "list_batches", lambda session: [
        ImportBatch(id=5, format="fuelio-fillups", filename="a.csv",
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
    "/stations", "/stations/1/edit", "/import", "/export", "/presets",
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


def test_timeline_customise_sheet_has_title_and_done(client):
    html = client.get("/").text
    assert 'class="pop-head"' in html and "data-close-customise" in html


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
    assert "420.00\u00a0\u20ac" in html


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


# --- import / export / presets ---------------------------------------------

STANDARD_CSV = (
    b"type,vehicle,date,odometer_km,fuel_l,price_per_l,total\n"
    b"refuel,Golf,2026-05-02,98000,40.000,1.500,60.00\n"
)
PLAIN_CSV = b"when,odo,litres,paid\n2026-05-02,98000,40.000,60.00\n"


class _FormReader(HTMLParser):
    """Collects what a browser would submit for the page's main form."""

    def __init__(self):
        super().__init__()
        self.values: dict[str, list[str]] = {}
        self._select = None
        self._options: list[tuple[str, bool]] = []
        self._textarea = None
        self._text = ""

    def _add(self, name, value):
        self.values.setdefault(name, []).append(value)

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "input" and a.get("name"):
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self._add(a["name"], a.get("value", "on"))
            elif kind != "file":
                self._add(a["name"], a.get("value", ""))
        elif tag == "select":
            self._select, self._options = a.get("name"), []
        elif tag == "option" and self._select:
            self._options.append((a.get("value", ""), "selected" in a))
        elif tag == "textarea":
            self._textarea, self._text = a.get("name"), ""

    def handle_data(self, data):
        if self._textarea:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "select" and self._select:
            chosen = next((v for v, sel in self._options if sel),
                          self._options[0][0] if self._options else "")
            self._add(self._select, chosen)
            self._select = None
        elif tag == "textarea" and self._textarea:
            self._add(self._textarea, self._text.strip("\n"))
            self._textarea = None


def browser_form(html: str, **changes) -> dict:
    """The form as the browser would send it, with ``changes`` typed in."""
    reader = _FormReader()
    reader.feed(html)
    form = {k: (v if len(v) > 1 else v[0]) for k, v in reader.values.items()}
    return form | changes


def hidden(html: str, name: str) -> str:
    """Value of a hidden input of the page."""
    match = re.search(rf'<input type="hidden" name="{name}" value="([^"]*)">', html)
    assert match, f"no hidden field {name}"
    return unescape(match.group(1))


def upload(client, data=STANDARD_CSV, headers=None):
    """Upload; return the location of its mapping page (the upload itself goes to the review)."""
    return upload_location(client, data, headers).replace("/import/preview?", "/import/mapping?")


def upload_location(client, data=STANDARD_CSV, headers=None):
    response = client.post("/import/upload",
                           files={"file": ("log.csv", data)}, headers=headers or {},
                           follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def token_of(location: str) -> str:
    return location.split("token=")[1].split("&")[0]


def state(html: str) -> dict:
    """The hidden state that the mapping and preview pages carry."""
    return {key: hidden(html, key)
            for key in ("token", "filename", "base_toml", "selected_preset", "preset_id")}


def fake_preview(**overrides):
    values = dict(format="fuelly-metric", vehicle_names=["My Golf"], new_refuels=5,
                  new_expenses=1, duplicate_refuels=2, duplicate_expenses=0)
    values.update(overrides)
    return ImportPreview(**values)


def test_import_page_has_upload_and_no_format_choice(client):
    html = client.get("/import").text
    assert 'name="file"' in html and 'name="format"' not in html
    assert "Presets" in html


def test_upload_goes_to_the_prefixed_review_page(client):
    location = upload_location(client, headers=INGRESS)
    assert location.startswith(f"{PREFIX}/import/preview?token=")
    page = client.get(location.removeprefix(PREFIX), headers=INGRESS)
    assert page.status_code == 200
    assert all(t.startswith(PREFIX + "/") for t in urls_in(page.text))


def test_mapping_shows_detected_preset_and_one_row_per_field(client):
    html = client.get(upload(client)).text
    assert "Glovebox" in html
    for name in ("type", "date", "odometer_km", "fuel_l", "station", "notes"):
        assert f'name="src.{name}"' in html
    assert re.search(r'<option value="col:date" selected>', html)
    assert 'name="decimal_char"' in html and 'name="date_format"' in html
    assert 'name="header_row"' in html and 'name="encoding"' in html


def test_mapping_of_unknown_headers_starts_empty_and_asks_for_required_fields(client):
    html = client.get(upload(client, PLAIN_CSV)).text
    assert "Custom mapping" in html
    assert "Map the required fields" in html and "type, date" in html
    assert not re.search(r'<option value="col:[^"]*" selected>', html)
    assert '<option value="col:odo" >' in html or '<option value="col:odo">' in html


def test_mapping_keeps_edits_when_updated_and_resets_on_new_preset(client):
    html = client.get(upload(client, PLAIN_CSV)).text
    form = state(html) | {"edited": "1", "src.type": "=", "val.type": "refuel",
                          "src.date": "col:when"}
    updated = client.post("/import/mapping", data=form).text
    assert re.search(r'<option value="col:when" selected>', updated)
    assert re.search(r'<option value="refuel" selected>', updated)
    again = client.post("/import/mapping", data=state(updated) | {"preset": "glovebox"}).text
    assert not re.search(r'<option value="col:when" selected>', again)
    assert re.search(r'<option value="glovebox" selected>', again)


def test_mapping_rejects_invalid_value_with_the_key_name(client):
    html = client.get(upload(client, PLAIN_CSV)).text
    form = state(html) | {"edited": "1", "src.type": "=", "val.type": "bike",
                          "src.date": "col:when"}
    response = client.post("/import/mapping", data=form)
    assert response.status_code == 422 and "fields.type.value" in response.text


def mapped_form(client, extra=None):
    """The mapping page of PLAIN_CSV as a browser submits it after the user maps it."""
    html = client.get(upload(client, PLAIN_CSV)).text
    return browser_form(html, **{
        "src.type": "=", "val.type": "refuel", "src.date": "col:when",
        "src.odometer_km": "col:odo", "src.fuel_l": "col:litres", "src.total": "col:paid",
    } | (extra or {}))


def test_preview_of_an_edited_mapping_asks_for_the_vehicle(client, monkeypatch):
    seen = {}

    def fake(session, data, preset, *, mapping=None, answers=None):
        seen.update(preset=preset, mapping=mapping)
        return fake_preview(vehicle_names=[], needs_vehicle_choice=True,
                            errors=[pipeline.CHOOSE_VEHICLE_MESSAGE])

    monkeypatch.setattr(pipeline, "preview_import", fake)
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert "Which vehicle do these records belong to?" in html
    assert ">Import now</button>" not in html
    assert pipeline.CHOOSE_VEHICLE_MESSAGE not in html
    preset = seen["preset"]
    assert preset.fields["type"].value == "refuel"
    assert preset.fields["date"].columns == ("when",)
    assert preset.id == ""  # an edited mapping is not the stored preset


def test_preview_carries_the_mapping_as_form_fields(client):
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert 'name="base_toml"' in html and "[fields]" in unescape(hidden(html, "base_toml"))
    assert 'name="edited"' not in html  # only the mapping page edits


def test_preview_shows_counts_note_and_vehicle_mapping(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview(
        preset_note="Based on public descriptions.", skipped=2))
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert "My Golf" in html and "skipped: 2" in html and 'name="maps"' in html
    assert "Based on public descriptions." in html
    assert "Rows not imported" in html and ">Import now</button>" in html


def test_preview_preselects_vehicle_with_same_name(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import",
                        lambda *a, **k: fake_preview(vehicle_names=["golf"]))
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert '<option value="1" selected>' in html


def test_preview_lists_first_fifty_row_errors_with_the_total(client, monkeypatch):
    errors = [RowError(i + 2, "date", "31/31/2024", "not a date") for i in range(60)]
    monkeypatch.setattr(pipeline, "preview_import",
                        lambda *a, **k: fake_preview(row_errors=errors))
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert "Rows with errors (60, first 50 shown)" in html
    assert html.count("31/31/2024") == 50
    assert "<td class=\"num\">2</td>" in html and ">Import now</button>" in html


def test_preview_asks_questions_and_blocks_commit(client, monkeypatch):
    question = Question(QuestionKind.DATE_ORDER, "Which order do the dates use?",
                        ("dmy", "mdy"))
    monkeypatch.setattr(pipeline, "preview_import",
                        lambda *a, **k: fake_preview(questions=[question]))
    html = client.post("/import/preview", data=mapped_form(client)).text
    assert 'name="ans_date_order" value="dmy"' in html and ">Import now</button>" not in html


def test_answered_question_stays_changeable(client, monkeypatch):
    seen = {}

    def fake(session, data, preset, *, mapping=None, answers=None):
        seen["answers"] = answers
        return fake_preview()

    monkeypatch.setattr(pipeline, "preview_import", fake)
    html = client.post("/import/preview",
                       data=mapped_form(client) | {"ans_date_order": "mdy"}).text
    assert seen["answers"].date_order == "mdy"
    assert re.search(r'value="mdy"[^>]*checked', html)


def test_commit_uses_preset_answers_mapping_and_removes_upload(
        client, monkeypatch, settings):
    committed = {}

    def fake_commit(session, data, filename, mapping, preset, *, answers=None):
        committed.update(data=data, filename=filename, mapping=mapping,
                         preset=preset, answers=answers)
        return ImportBatch(id=9)

    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    monkeypatch.setattr(pipeline, "commit_import", fake_commit)
    form = mapped_form(client) | {"names": ["My Golf", "Polo"], "maps": ["1", "new"],
                                  "ans_date_order": "dmy"}
    response = client.post("/import/commit", data=form, headers=INGRESS,
                           follow_redirects=False)
    assert response.headers["location"] == f"{PREFIX}/import?done=9"
    assert committed["data"] == PLAIN_CSV and committed["filename"] == "log.csv"
    assert committed["mapping"].by_name == {"My Golf": 1, "Polo": None}
    assert committed["answers"].date_order == "dmy"
    assert committed["preset"].fields["total"].columns == ("paid",)
    assert not list((settings.data_dir / "uploads").glob("*.upload"))


def test_commit_of_an_untouched_preset_keeps_its_id(client, monkeypatch):
    committed = {}
    monkeypatch.setattr(pipeline, "commit_import", lambda session, data, filename,
                        mapping, preset, *, answers=None:
                        committed.update(preset=preset) or ImportBatch(id=1))
    form = browser_form(client.get(upload(client)).text)
    client.post("/import/commit", data=form, follow_redirects=False)
    assert committed["preset"].id == "glovebox"
    form = browser_form(client.get(upload(client)).text, **{"default.notes": "x"})
    client.post("/import/commit", data=form, follow_redirects=False)
    assert committed["preset"].id == ""


def test_commit_error_returns_to_preview(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())

    def boom(*a, **k):
        raise ValueError("cannot import")

    monkeypatch.setattr(pipeline, "commit_import", boom)
    response = client.post("/import/commit", data=mapped_form(client))
    assert response.status_code == 422 and "cannot import" in response.text


def test_commit_of_a_file_with_more_sections_says_so(client, monkeypatch):
    monkeypatch.setattr(pipeline, "commit_import", lambda *a, **k: ImportBatch(id=1))
    data = b'## Log\nData,Odo (km)\n2026-05-02,98000\n## Costs\nCostTitle\nOil\n'
    html = client.get(upload(client, data)).text
    form = state(html)
    form["base_toml"] = form["base_toml"].replace("[format]", '[file]\nsection = "Log"\n\n[format]', 1)
    response = client.post("/import/commit", data=form, follow_redirects=False)
    location = response.headers["location"]
    assert "done=1" in location and "seen=Log" in location and "more=Costs" in location
    page = client.get(location).text
    assert "Import next section: Costs" in page
    assert "section=Costs" in page and "seen=Log" in page
    # the upload is kept for the next section
    assert len(list((client.app.state.settings.data_dir / "uploads").glob("*.upload"))) == 1


def test_import_page_without_a_stored_upload_offers_no_next_button(client):
    page = client.get("/import?done=1&more=Costs&token=" + "0" * 32).text
    assert "More sections in this file: Costs" in page
    assert "Import next section" not in page


def test_save_preset_from_the_preview_then_it_is_listed(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    form = mapped_form(client) | {"preset_name": "My bank"}
    response = client.post("/import/save-preset", data=form)
    assert response.status_code == 200 and 'Saved as preset: My bank' in response.text
    assert hidden(response.text, "preset_id") == "user-my-bank"
    assert "My bank" in client.get("/presets").text
    clash = client.post("/import/save-preset", data=form)
    assert clash.status_code == 422 and "already exists" in clash.text


def test_unknown_or_malicious_token_is_404(client):
    assert client.get("/import/mapping?token=../../etc/passwd").status_code == 404
    assert client.get("/import/preview?token=" + "0" * 32).status_code == 404
    assert client.post("/import/preview", data={"token": "0" * 32}).status_code == 404


def test_import_page_lists_batches_with_undo(client, monkeypatch):
    html = client.get("/import", headers=INGRESS).text
    assert "a.csv" in html and f'action="{PREFIX}/import/5/undo"' in html
    assert "Fuelio (fill-ups)" in html  # the preset name, not its id
    undone = []
    monkeypatch.setattr(pipeline, "undo_batch", lambda session, batch_id: undone.append(batch_id))
    client.post("/import/5/undo", follow_redirects=False)
    assert undone == [5]


def test_backup_upload_goes_straight_to_the_preview(client, monkeypatch):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("datapackage.json", "{}")
        archive.writestr("records.csv", "type,vehicle,date\n")
    monkeypatch.setattr(pipeline, "preview_import",
                        lambda *a, **k: fake_preview(is_backup=True))
    location = upload_location(client, buffer.getvalue())
    assert "/import/preview?token=" in location
    html = client.get(location).text
    assert "Glovebox" in html and 'name="src.' not in html


def test_import_walks_through_the_real_engine_and_pipeline(client, monkeypatch, engine):
    """No fakes: upload, map, preview, save the preset, commit, undo."""
    from sqlalchemy import select

    from glovebox.db import make_session_factory
    from glovebox.models import Refuel, Vehicle

    monkeypatch.undo()
    with make_session_factory(engine)() as session:
        session.add(Vehicle(name="Golf"))
        session.commit()
        vehicle_id = session.scalar(select(Vehicle.id))
    form = mapped_form(client) | {"default_vehicle": str(vehicle_id)}
    preview = client.post("/import/preview", data=form).text
    assert "New refuels: <strong>1</strong>" in preview and ">Import now</button>" in preview
    saved = client.post("/import/save-preset", data=form | {"preset_name": "Plain"})
    assert hidden(saved.text, "preset_id") == "user-plain"
    committed = client.post("/import/commit", data=form, follow_redirects=False)
    assert committed.status_code == 303
    with make_session_factory(engine)() as session:
        refuel = session.scalars(select(Refuel)).one()
        assert (refuel.litres_milli, refuel.total_cents) == (40000, 6000)
    # The next upload of this layout finds the saved preset.
    assert 'value="user-plain" selected' in client.get(upload(client, PLAIN_CSV)).text


# --- export ---------------------------------------------------------------


def test_export_page_offers_presets_backup_and_format_description(client):
    html = client.get("/export").text
    assert "Glovebox" in html and "Fuelly (metric)" in html
    assert "Fuelio (fill-ups)" not in html  # not usable for export
    assert 'formaction="/export/csv"' in html and 'formaction="/export/backup"' in html
    assert 'href="/export/format.json"' in html
    assert "Expenses are not included" not in html


def test_export_page_for_fuelly_says_expenses_are_not_included(client):
    html = client.get("/export?preset=fuelly-metric").text
    assert "Expenses are not included" in html
    assert re.search(r'<option value="fuelly-metric" selected>', html)


def test_export_page_rejects_unknown_or_non_exportable_preset(client):
    assert client.get("/export?preset=nope").status_code == 404
    assert client.get("/export?preset=fuelio-fillups").status_code == 422


def test_export_preset_change_keeps_the_ticked_vehicles(client):
    html = client.post("/export", data={"preset": "fuelly-metric", "vehicle": "1"}).text
    assert re.search(r'name="vehicle" value="1" checked', html)
    assert re.search(r'<option value="fuelly-metric" selected>', html)


def test_export_page_names_a_vehicle_that_is_renamed(client, monkeypatch):
    monkeypatch.setattr(csv_export, "renamed_vehicles",
                        lambda session, ids=None: {"Golf": "Golf (archived)"})
    assert 'Golf" is exported as "Golf (archived)' in unescape(client.get("/export").text)


def test_csv_download_uses_the_preset_and_vehicles(client, monkeypatch):
    seen = {}

    def fake(session, settings, preset, vehicle_ids=None):
        seen.update(preset=preset, ids=vehicle_ids)
        return b"a,b\r\n", "text/csv"

    monkeypatch.setattr(csv_export, "export_csv", fake)
    base = {"base_preset": "glovebox"}
    response = client.post("/export/csv", data=base | {"vehicle": ["1", "2"]}
                           | {f"include.{f.name}": "1" for f in RECORD_FIELDS}
                           | {f"header.{f.name}": f.name for f in RECORD_FIELDS})
    assert response.content == b"a,b\r\n" and seen["ids"] == [1, 2]
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith('.csv"')
    assert list(seen["preset"].fields) == [f.name for f in RECORD_FIELDS]


def test_csv_download_with_customised_columns_and_format(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(csv_export, "export_csv", lambda session, settings, preset,
                        ids=None: seen.update(preset=preset, ids=ids) or (b"x", "text/csv"))
    client.post("/export/csv", data={
        "base_preset": "glovebox", "delimiter": ";", "decimal_char": ",",
        "date_format": "%d.%m.%Y", "distance_unit": "mi", "volume_unit": "gal_us",
        "include.date": "1", "header.date": "Datum",
        "include.fuel_l": "1", "header.fuel_l": "fuel_l",
        "include.total": "1", "header.total": "total",
    })
    preset = seen["preset"]
    assert [m.columns[0] for m in preset.fields.values()] == ["Datum", "fuel_l", "total"]
    assert preset.file.delimiter == ";" and preset.format.decimal_char == ","
    assert preset.format.date_format == "%d.%m.%Y"
    assert (preset.format.distance_unit, preset.format.volume_unit) == ("mi", "gal_us")
    assert seen["ids"] is None


def test_csv_download_of_fuelly_keeps_the_type_filter_and_zips(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(csv_export, "export_csv", lambda session, settings, preset,
                        ids=None: seen.update(preset=preset) or (b"PK", "application/zip"))
    page = client.get("/export?preset=fuelly-metric").text
    form = {"base_preset": "fuelly-metric"}
    for name in re.findall(r'name="include\.([a-z_]+)" value="1" checked', page):
        form[f"include.{name}"] = "1"
        form[f"header.{name}"] = unescape(re.search(
            rf'name="header\.{name}" value="([^"]*)"', page).group(1))
    response = client.post("/export/csv", data=form)
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')
    assert seen["preset"].fields["type"].value == "refuel"
    assert seen["preset"].split_by_vehicle


def test_csv_download_without_columns_is_an_error(client):
    response = client.post("/export/csv", data={"base_preset": "glovebox"})
    assert response.status_code == 422 and "choose at least one column" in response.text


def test_save_export_as_preset_makes_it_exportable_and_importable(client):
    response = client.post("/export/preset", data={
        "base_preset": "glovebox", "preset_name": "Mine", "delimiter": ";",
        "include.date": "1", "header.date": "Datum",
        "include.total": "1", "header.total": "Summe"})
    assert response.status_code == 200 and 'Saved as preset: Mine' in response.text
    assert re.search(r'<option value="user-mine" selected>', response.text)
    own = get_preset_for_test(client, "user-mine")
    assert own.export and own.file.delimiter == ";"
    assert own.fields["date"].columns == ("Datum",)


def get_preset_for_test(client, preset_id):
    from glovebox.importers.presets import get_preset

    with client.app.state.session_factory() as session:
        return get_preset(session, preset_id)


def test_backup_download(client, monkeypatch):
    seen = []
    monkeypatch.setattr(backup_exporter, "export_backup",
                        lambda session, settings, ids=None: seen.append(ids) or b"PK-zip")
    response = client.post("/export/backup", data={"vehicle": "1"})
    assert response.content == b"PK-zip" and seen == [[1]]
    assert response.headers["content-type"] == "application/zip"
    assert "glovebox-backup-" in response.headers["content-disposition"]


def test_format_description_is_a_data_package(client):
    response = client.get("/export/format.json")
    descriptor = json.loads(response.content)
    assert [r["name"] for r in descriptor["resources"]][:1] == ["records"]
    assert "attachment" in response.headers["content-disposition"]


# --- presets page -----------------------------------------------------------

USER_PRESET = """name = "Bank export"
[fields]
date = { column = "when" }
"""


def test_presets_page_lists_shipped_presets_with_status_and_download(client):
    html = client.get("/presets", headers=INGRESS).text
    assert "Glovebox" in html and "Verified" in html and "Unverified" in html
    assert "Never tested against a real export" in html
    assert f'href="{PREFIX}/presets/glovebox/download"' in html
    assert "No own presets yet." in html and "Delete" not in html.split("Shipped presets")[1]


def test_shipped_preset_download_is_the_original_file(client):
    response = client.get("/presets/fuelly-metric/download")
    assert response.status_code == 200 and b"name =" in response.content
    assert 'filename="fuelly-metric.toml"' in response.headers["content-disposition"]
    assert client.get("/presets/nope/download").status_code == 404


def test_preset_upload_download_and_delete(client):
    response = client.post("/presets/upload", files={"file": ("bank.toml", USER_PRESET.encode())},
                           follow_redirects=False)
    assert response.status_code == 303
    html = client.get("/presets").text
    assert "Bank export" in html and "Delete" not in html.split("<h2>Shipped presets")[0].split("<h2>Your presets")[1]
    assert 'formaction="/presets/user-bank-export/delete"' in client.get("/presets/user-bank-export").text
    download = client.get("/presets/user-bank-export/download")
    assert load_preset(download.text).fields["date"].columns == ("when",)
    deleted = client.post("/presets/user-bank-export/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert "Bank export" not in client.get("/presets").text
    assert client.post("/presets/user-bank-export/delete").status_code == 404


def test_preset_upload_errors_name_the_key(client):
    bad = USER_PRESET + '[fields.litres]\ncolumn = "l"\n'
    response = client.post("/presets/upload", files={"file": ("bad.toml", bad.encode())})
    assert response.status_code == 422 and "fields.litres" in response.text
    assert "Bank export" not in client.get("/presets").text


def test_preset_upload_rejects_a_name_clash_and_non_text(client):
    clash = USER_PRESET.replace("Bank export", "Glovebox")
    response = client.post("/presets/upload", files={"file": ("a.toml", clash.encode())})
    assert response.status_code == 422 and "already exists" in response.text
    binary = client.post("/presets/upload", files={"file": ("a.toml", b"\xff\xfe\x00")})
    assert binary.status_code == 422


def test_shipped_preset_cannot_be_deleted(client):
    response = client.post("/presets/glovebox/delete")
    assert response.status_code == 422 and "cannot be deleted" in response.text


def test_manage_links_to_import_export_and_presets(client):
    html = client.get("/manage", headers=INGRESS).text
    assert "CSV files with presets" in html
    assert "Standard CSV, Fuelly-compatible CSV or full backup" in html
    assert f'href="{PREFIX}/presets"' in html


def test_vehicle_edit_prefills_form(client):
    html = client.get("/vehicles/1/edit").text
    assert 'name="name" value="Golf"' in html and 'name="make" value="VW"' in html


# --- round 2: sub-page header, links, currency, summary picker --------------


@pytest.mark.parametrize("path", ["/vehicles", "/stations", "/import", "/export", "/presets"])
def test_manage_sub_pages_have_the_back_icon_button(client, path):
    html = client.get(path, headers=INGRESS).text
    assert 'aria-label="Back to Manage"' in html
    assert f'href="{PREFIX}/manage"' in html
    head = html.split('class="page-head"', 1)[1].split("</div>", 1)[0]
    assert head.index("icon-btn") < head.index("<h1>")
    assert "‹" not in html


def test_import_steps_go_back_to_import(client, monkeypatch):
    monkeypatch.setattr(pipeline, "preview_import", lambda *a, **k: fake_preview())
    for html in (client.get(upload(client)).text,
                 client.post("/import/preview", data=mapped_form(client)).text):
        assert 'aria-label="Back to Import"' in html and 'class="page-head"' in html


@pytest.mark.parametrize("path", PAGES)
def test_no_plain_text_links_for_navigation(client, path):
    # Every in-app link is a styled element (button, icon button, row, tab, chip ...).
    html = client.get(path).text
    for tag in re.findall(r"<a\b[^>]*>", html):
        assert 'class="' in tag, tag
    assert "link-btn" not in html


def test_currency_symbols():
    from glovebox.web.formatting import currency_symbol, money

    assert [currency_symbol(c) for c in ("EUR", "USD", "GBP", "CHF", "SEK")] == [
        "€", "$", "£", "CHF", "SEK"]
    assert money(12345, "EUR") == "123.45 €"
    assert money(12345, "CHF") == "123.45 CHF"


def test_currency_symbol_shows_in_forms_and_cards(client):
    assert "€" in client.get("/refuels/new").text
    assert "EUR" not in client.get("/").text


def test_summary_picker_only_with_all_vehicles_and_several_vehicles(client, monkeypatch):
    assert "Summaries" not in client.get("/").text  # a single vehicle
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    html = client.get("/").text
    assert "All vehicles (combined)" in html and 'name="summary" value="2"' in html
    client.post("/preferences/vehicle", data={"vehicle": "1"})
    assert "Summaries" not in client.get("/").text


def test_summary_picker_stores_only_unticked_groups(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    client.post("/preferences/cards", data={
        "card": ["cost_month"], "offered": ["all", "1", "2"], "summary": ["all", "2"]})
    html = client.get("/").text
    assert re.search(r'data-summary="1"\s+hidden', html)
    assert not re.search(r'data-summary="2"\s+hidden', html)
    assert not re.search(r'data-summary="all"\s+hidden', html)
    assert re.search(r'name="summary" value="1"\s*>', html)  # not ticked


def test_hidden_combined_summary_and_new_vehicle_defaults_to_shown(client, monkeypatch):
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"))
    client.post("/preferences/cards", data={
        "offered": ["all", "1", "2"], "summary": ["1", "2"]})
    assert re.search(r'data-summary="all"\s+hidden', client.get("/").text)
    use_vehicles(monkeypatch, make_vehicle(), make_vehicle(2, "Polo"), make_vehicle(3, "Fiat"))
    html = client.get("/").text
    assert not re.search(r'data-summary="3"\s+hidden', html)
    assert 'name="summary" value="3" checked' in html


def test_phone_page_end_clears_fab_and_bottom_nav():
    """Bottom padding of main on phones exceeds the FAB's top edge (80 + 56 px)."""
    css = (Path(__file__).parents[1] / "src/glovebox/web/static/app.css").read_text()
    phone = css.split("@media (max-width: 699px)", 1)[1]
    padding = re.search(r"main \{ padding: [^;]*calc\((\d+)px", phone)
    assert padding and int(padding.group(1)) >= 80 + 56


def test_autosubmit_is_attached_before_the_page_script_loads():
    """The deferred app.js can load late; theme.js (in head) must own the handler."""
    static = Path(__file__).parents[1] / "src/glovebox/web/static"
    assert "data-autosubmit" in (static / "theme.js").read_text()
    assert "data-autosubmit" not in (static / "app.js").read_text()


# --- preset detail and note editing; version label ---------------------------

LONG_NOTE = "Tested with a real export. " * 12


def test_own_preset_note_is_shown_in_full_and_can_be_edited(client):
    body = USER_PRESET.replace('name = "Bank export"', f'name = "Bank export"\nnote = "{LONG_NOTE}"')
    client.post("/presets/upload", files={"file": ("bank.toml", body.encode())})
    assert LONG_NOTE.strip() in client.get("/presets").text
    dialog = client.get("/presets/user-bank-export").text
    assert "<textarea" in dialog and LONG_NOTE.strip() in dialog
    response = client.post("/presets/user-bank-export/edit",
                           data={"note": "Line one\nline  two"}, follow_redirects=False)
    assert response.status_code == 303
    saved = load_preset(client.get("/presets/user-bank-export/download").text)
    assert saved.note == "Line one line two" and saved.name == "Bank export"
    assert saved.fields["date"].columns == ("when",)


def test_shipped_preset_is_readable_with_steps_but_not_editable(client):
    html = client.get("/presets/drivvo-refuelling").text
    assert "<textarea" not in html and "Steps" in html and "<ol" in html
    assert "Shipped presets are always locked" in html and "/duplicate" in html
    assert client.post("/presets/drivvo-refuelling/edit", data={"note": "x"}).status_code == 403
    assert client.get("/presets/nope").status_code == 404
    assert client.post("/presets/user-nope/edit", data={"note": "x"}).status_code == 404


def test_app_bar_shows_the_installed_version(client):
    from importlib.metadata import version

    html = client.get("/").text
    assert f'<span class="app-version" title="Glovebox version">v{version("glovebox")}</span>' in html


def test_timeline_period_picker_is_a_plain_form(client):
    html = client.get("/").text
    assert 'action="/preferences/period"' in html
    assert 'name="owner" value="combined"' in html and 'name="date_from"' in html
    assert 'type="radio" name="period" value="12m" checked' in html
    assert "Last 12 months" in html
