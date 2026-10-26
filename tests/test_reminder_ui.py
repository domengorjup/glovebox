"""
Reminder pages through the real forms: create, edit, done, reopen, delete,
from an expense, vehicle date switches, the Due soon card, the calendar
setting (fake Home Assistant) and the import counts.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fake_ha import TOKEN, FakeHa
from glovebox.app import create_app
from glovebox.config import Settings
from glovebox.db import make_engine
from glovebox.models import Reminder, ReminderStatus
from glovebox.services.ha_calendar import HaClient
from glovebox.services.reminder_sync import ReminderSync
from test_e2e import _as_form, _form_fields

TODAY = date.today()
PREFIX = {"X-Ingress-Path": "/api/hassio_ingress/abc"}


def _vehicle(client: TestClient, name: str = "Golf", **extra: str) -> int:
    client.post("/vehicles/new", data={"name": name, **extra})
    with client.app.state.session_factory() as session:
        from glovebox.models import Vehicle
        return session.scalar(select(Vehicle.id).where(Vehicle.name == name))


def _reminders(client: TestClient) -> list[Reminder]:
    with client.app.state.session_factory() as session:
        found = list(session.scalars(select(Reminder).order_by(Reminder.id)))
        session.expunge_all()
        return found


def _create(client: TestClient, vehicle_id: int, **changes: str):
    data = {
        "vehicle_id": str(vehicle_id), "title": "Registration", "category": "registration",
        "due_date": (TODAY + timedelta(days=10)).isoformat(), "lead_days": "30",
        "notes": "", "expense_id": "", "next": "/reminders",
    }
    return client.post("/reminders/new", data=data | changes, follow_redirects=False)


# --- Create, edit, done, reopen, delete ----------------------------------------------------------


def test_new_form_defaults_to_30_days(client: TestClient) -> None:
    _vehicle(client)
    html = client.get("/reminders/new").text
    assert re.search(r'name="lead_days" value="30"', html)
    assert "Download .ics" not in html  # nothing to download before it exists


def test_create_edit_done_reopen_delete(client: TestClient) -> None:
    vid = _vehicle(client)
    assert _create(client, vid).status_code == 303
    (reminder,) = _reminders(client)
    assert (reminder.title, reminder.lead_days, reminder.status) == (
        "Registration", 30, ReminderStatus.OPEN)

    page = client.get("/reminders").text
    assert "Registration" in page and "in 10 days" in page

    edit = client.get(f"/reminders/{reminder.id}/edit").text
    assert f"/reminders/{reminder.id}.ics" in edit and "Mark done<" in edit
    client.post(f"/reminders/{reminder.id}/edit", data={
        "vehicle_id": str(vid), "title": "Tax", "category": "other",
        "due_date": (TODAY + timedelta(days=40)).isoformat(), "lead_days": "7",
        "notes": "pay online", "expense_id": "", "next": "/reminders"})
    (reminder,) = _reminders(client)
    assert (reminder.title, reminder.lead_days, reminder.revision) == ("Tax", 7, 2)

    client.post(f"/reminders/{reminder.id}/done", data={"next": "/reminders"})
    page = client.get("/reminders").text
    assert "Done (1)" in page and "No open reminders" in page
    assert "Reopen" in client.get(f"/reminders/{reminder.id}/edit").text

    client.post(f"/reminders/{reminder.id}/reopen")
    assert _reminders(client)[0].status is ReminderStatus.OPEN
    client.post(f"/reminders/{reminder.id}/delete")
    assert _reminders(client) == []


def test_invalid_reminder_shows_messages_and_stores_nothing(client: TestClient) -> None:
    vid = _vehicle(client)
    for changes, message in (
        ({"title": " "}, "Enter a title"),
        ({"due_date": ""}, "Enter the due date"),
        ({"lead_days": "400"}, "between 0 and 365"),
        ({"lead_days": "x"}, "whole number"),
        ({"due_date": "31/12/2027"}, "valid date"),
    ):
        response = _create(client, vid, **changes)
        assert response.status_code == 422 and message in response.text
    assert _reminders(client) == []


def test_reminder_dialog_uses_ingress_prefix(client: TestClient) -> None:
    vid = _vehicle(client)
    _create(client, vid)
    html = client.get("/reminders/1/edit", headers=PREFIX).text
    assert "/api/hassio_ingress/abc/reminders/1.ics" in html
    assert "/api/hassio_ingress/abc/reminders/1/delete" in html


# --- Chooser, Manage, Timeline card ----------------------------------------------------------------


def test_manage_row_and_add_action(client: TestClient) -> None:
    vid = _vehicle(client)
    assert "/reminders/new" in client.get("/reminders").text
    assert "Reminders" in client.get("/manage").text
    _create(client, vid)
    assert "1 open" in client.get("/manage").text


def test_due_soon_card_orders_overdue_first_and_hides_when_empty(client: TestClient) -> None:
    vid = _vehicle(client)
    assert "Due soon" not in client.get("/").text
    _create(client, vid, title="Later", due_date=(TODAY + timedelta(days=5)).isoformat())
    _create(client, vid, title="Overdue", due_date=(TODAY - timedelta(days=1)).isoformat())
    _create(client, vid, title="Far", due_date=(TODAY + timedelta(days=90)).isoformat())
    html = client.get("/").text
    card = html.split("Due soon", 1)[1].split("summary", 1)[0]
    assert card.index("Overdue") < card.index("Later") and "Far" not in card
    assert "Overdue by 1 day" in card and "in 5 days" in card
    assert 'href="/reminders"' in html  # the All reminders button


def test_done_button_on_the_timeline_removes_the_row(client: TestClient) -> None:
    vid = _vehicle(client)
    _create(client, vid)
    assert "Due soon" in client.get("/").text
    client.post("/reminders/1/done", data={"next": "/"})
    assert "Due soon" not in client.get("/").text


def test_due_card_follows_the_app_bar_vehicle(client: TestClient) -> None:
    golf, polo = _vehicle(client, "Golf"), _vehicle(client, "Polo")
    _create(client, golf, title="Golf thing")
    _create(client, polo, title="Polo thing")
    client.post("/preferences/vehicle", data={"vehicle": str(golf), "next": "/"})
    html = client.get("/").text
    assert "Golf thing" in html and "Polo thing" not in html


# --- From an expense ---------------------------------------------------------------------------------


def _expense(client: TestClient, vid: int, **changes: str) -> None:
    data = {"vehicle_id": str(vid), "date": "2026-03-01", "category": "insurance",
            "title": "Annual policy", "amount": "400", "odometer_km": "1000"}
    assert client.post("/expenses/new", data=data | changes,
                       follow_redirects=False).status_code == 303


def test_remind_me_on_an_expense_prefills_the_form(client: TestClient) -> None:
    vid = _vehicle(client)
    _expense(client, vid, coverage_start="2026-03-01", coverage_end="2027-02-28")
    edit = client.get("/expenses/1/edit").text
    assert "/reminders/new?expense=1" in edit and "Remind me" in edit
    form = client.get("/reminders/new?expense=1").text
    assert 'value="Annual policy renewal"' in form
    assert 'value="2027-02-28"' in form and 'value="30"' in form
    assert 'value="insurance" selected' in form.replace("\n", " ") or "selected>Insurance" in form
    client.post("/reminders/new", data={
        "vehicle_id": str(vid), "title": "Annual policy renewal", "category": "insurance",
        "due_date": "2027-02-28", "lead_days": "30", "notes": "", "expense_id": "1"})
    assert _reminders(client)[0].expense_id == 1
    assert "Created from: Annual policy" in client.get("/reminders/1/edit").text


def test_expense_without_coverage_suggests_a_year_later(client: TestClient) -> None:
    vid = _vehicle(client)
    _expense(client, vid, category="other", coverage_start="", coverage_end="")
    assert 'value="2027-03-01"' in client.get("/reminders/new?expense=1").text


def test_add_expense_switch_creates_the_reminder(client: TestClient) -> None:
    vid = _vehicle(client)
    assert "Remind me before it runs out" in client.get("/expenses/new").text
    assert "Remind me before it runs out" in client.get("/quick-expense").text
    _expense(client, vid, category="registration", coverage_start="2026-05-01",
             coverage_end="2027-04-30", remind="1", remind_days="14")
    (reminder,) = _reminders(client)
    assert (reminder.due_date, reminder.lead_days, reminder.expense_id) == (
        date(2027, 4, 30), 14, 1)
    assert reminder.category.value == "registration"


def test_quick_expense_switch_and_off_by_default(client: TestClient) -> None:
    vid = _vehicle(client)
    data = {"vehicle_id": str(vid), "date": "2026-03-01", "category": "insurance",
            "title": "Policy", "amount": "100", "odometer_km": "5"}
    client.post("/quick-expense", data=data)
    assert _reminders(client) == []
    client.post("/quick-expense", data=data | {"remind": "1", "remind_days": "30"})
    assert len(_reminders(client)) == 1


def test_bad_remind_days_keep_the_expense_form(client: TestClient) -> None:
    vid = _vehicle(client)
    data = {"vehicle_id": str(vid), "date": "2026-03-01", "category": "insurance",
            "title": "Policy", "amount": "100", "odometer_km": "5",
            "remind": "1", "remind_days": "999"}
    response = client.post("/expenses/new", data=data)
    assert response.status_code == 422 and "between 0 and 365" in response.text
    assert _reminders(client) == []
    assert 'name="remind" value="1" checked' in response.text


def test_deleting_the_expense_keeps_the_reminder(client: TestClient) -> None:
    vid = _vehicle(client)
    _expense(client, vid, remind="1")
    client.post("/expenses/1/delete")
    (reminder,) = _reminders(client)
    assert reminder.expense_id is None
    assert "Created from" not in client.get("/reminders/1/edit").text


# --- Vehicle date switches ----------------------------------------------------------------------------


def test_vehicle_switches_create_move_and_delete_the_reminder(client: TestClient) -> None:
    vid = _vehicle(client, registration_valid_until="2027-04-30",
                   registration_remind="1", registration_remind_days="30")
    (reminder,) = _reminders(client)
    assert (reminder.title, reminder.due_date, reminder.vehicle_field) == (
        "Registration renewal", date(2027, 4, 30), "registration_valid_until")
    edit = client.get(f"/vehicles/{vid}/edit").text
    assert 'name="registration_remind" value="1" checked' in edit
    assert 'name="insurance_remind" value="1" checked' not in edit

    base = {"name": "Golf", "registration_remind": "1", "registration_remind_days": "30"}
    client.post(f"/vehicles/{vid}/edit", data=base | {"registration_valid_until": "2028-04-30"})
    (reminder,) = _reminders(client)
    assert reminder.due_date == date(2028, 4, 30)

    client.post(f"/vehicles/{vid}/edit", data={"name": "Golf",
                                               "registration_valid_until": "2028-04-30"})
    assert _reminders(client) == []


def test_vehicle_switch_after_done_makes_a_new_reminder(client: TestClient) -> None:
    vid = _vehicle(client, insurance_valid_until="2027-01-31",
                   insurance_remind="1", insurance_remind_days="20")
    client.post("/reminders/1/done")
    data = {"name": "Golf", "insurance_remind": "1", "insurance_remind_days": "20"}
    client.post(f"/vehicles/{vid}/edit", data=data | {"insurance_valid_until": "2028-01-31"})
    open_ones = [r for r in _reminders(client) if r.status is ReminderStatus.OPEN]
    assert len(open_ones) == 1 and open_ones[0].due_date == date(2028, 1, 31)


def test_vehicle_switch_with_bad_days_keeps_the_dialog(client: TestClient) -> None:
    response = client.post("/vehicles/new", data={
        "name": "Golf", "insurance_valid_until": "2027-01-31",
        "insurance_remind": "1", "insurance_remind_days": "500"})
    assert response.status_code == 422 and "between 0 and 365" in response.text
    assert _reminders(client) == []


def test_vehicle_delete_page_counts_reminders(client: TestClient) -> None:
    vid = _vehicle(client)
    _create(client, vid)
    assert "<strong>1</strong> reminder" in client.get(f"/vehicles/{vid}/delete").text
    client.post(f"/vehicles/{vid}/delete", data={"confirm": "1"})
    assert _reminders(client) == []


# --- Import ----------------------------------------------------------------------------------------------


def _backup_of_two_reminders(client: TestClient) -> bytes:
    """A real full backup holding one open and one done reminder; the data is then removed."""
    vid = _vehicle(client)
    _create(client, vid, title="Tax")
    _create(client, vid, title="Old")
    client.post("/reminders/2/done")
    backup = client.post("/export/backup").content
    client.post(f"/vehicles/{vid}/delete", data={"confirm": "1"})
    assert _reminders(client) == []
    return backup


def _upload_preview(client: TestClient, backup: bytes) -> str:
    """Upload the backup and return the preview page."""
    response = client.post("/import/upload", files={"file": ("b.zip", backup)},
                           follow_redirects=False)
    assert response.status_code == 303
    return client.get(response.headers["location"]).text


def test_import_preview_and_history_show_reminder_counts(client: TestClient) -> None:
    backup = _backup_of_two_reminders(client)
    preview = _upload_preview(client, backup)
    assert "New reminders: <strong>2</strong>" in preview
    fields = _as_form(_form_fields(preview))
    commit = client.post("/import/commit", data=fields, follow_redirects=False)
    assert commit.status_code == 303
    assert "2 reminders" in client.get("/import").text
    assert len(_reminders(client)) == 2
    assert "already present, skipped: 2 reminders" in _upload_preview(client, backup)


# --- Calendar setting ------------------------------------------------------------------------------------


def test_standalone_hides_the_calendar_setting(client: TestClient) -> None:
    html = client.get("/reminders").text
    assert "Calendar sync needs the Home Assistant add-on" in html
    assert 'name="entity_id"' not in html and "Sync now" not in html


@pytest.fixture
def addon_client(tmp_path: Path):
    """The app wired to a fake HA, on a file database (see test_reminder_routes)."""
    engine = make_engine(tmp_path)
    with FakeHa() as ha:
        ha.add_calendar("calendar.glovebox", "Glovebox reminders", 7)
        ha.add_calendar("calendar.family", "Family", 1)
        ha.add_calendar("calendar.readonly", "Holidays", 0)
        app = create_app(Settings(data_dir=tmp_path), engine)
        app.state.reminder_sync = ReminderSync(
            app.state.session_factory, HaClient(TOKEN, ha.rest_url, ha.ws_url, timeout=3))
        with TestClient(app) as client:
            yield client, ha


def test_calendar_setting_lists_writable_calendars_with_labels(addon_client) -> None:
    client, _ = addon_client
    html = client.get("/reminders").text
    assert "Glovebox reminders - Adds, changes and removes events" in html
    assert "Family - Only adds events" in html
    assert "Holidays" not in html
    assert "Sync now" in html


def test_choosing_a_calendar_through_the_form_writes_events(addon_client) -> None:
    client, ha = addon_client
    vid = _vehicle(client)
    _create(client, vid)
    response = client.post("/reminders/calendar", data={
        "entity_id": "calendar.glovebox", "next": "/reminders"})
    assert response.status_code == 200
    assert len(ha.events("calendar.glovebox")) == 1
    html = client.get("/reminders").text
    assert 'value="calendar.glovebox" selected' in html.replace("\n", " ") or "selected" in html
    assert "In calendar calendar.glovebox" in client.get("/reminders/1/edit").text
    client.post("/reminders/1/done")
    assert ha.events("calendar.glovebox") == []


def test_unsynced_reminder_shows_its_message_and_sync_now(addon_client) -> None:
    client, ha = addon_client
    vid = _vehicle(client)
    client.post("/reminders/calendar", data={"entity_id": "calendar.family"})
    _create(client, vid)
    client.post("/reminders/1/edit", data={
        "vehicle_id": str(vid), "title": "Registration", "category": "registration",
        "due_date": (TODAY + timedelta(days=20)).isoformat(), "lead_days": "30"})
    page = client.get("/reminders").text
    assert "This calendar can&#39;t change events; edit it there." in page
    assert "Sync now" in client.get("/reminders/1/edit").text


def test_missing_calendar_is_flagged_at_the_setting(addon_client) -> None:
    client, ha = addon_client
    vid = _vehicle(client)
    _create(client, vid)
    client.post("/reminders/calendar", data={"entity_id": "calendar.glovebox"})
    del ha.calendars["calendar.glovebox"]
    client.post("/reminders/1/edit", data={
        "vehicle_id": "1", "title": "Registration", "category": "registration",
        "due_date": (TODAY + timedelta(days=20)).isoformat(), "lead_days": "30"})
    html = client.get("/reminders").text
    assert "no longer exists" in html
    assert "calendar.glovebox - not available" in html


def test_changing_calendar_that_cannot_remove_reports_left_behind(addon_client) -> None:
    client, ha = addon_client
    vid = _vehicle(client)
    _create(client, vid)
    client.post("/reminders/calendar", data={"entity_id": "calendar.family"})
    client.post("/reminders/calendar", data={"entity_id": "calendar.glovebox"})
    html = client.get("/reminders").text
    assert "1 event was left in calendar.family" in html
