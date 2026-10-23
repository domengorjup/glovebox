"""Template-free reminder routes, the Core API settings and the blueprint file."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fake_ha import TOKEN, FakeHa
from glovebox.app import create_app
from glovebox.config import Mode, Settings, load_settings
from glovebox.models import Reminder, ReminderStatus
from glovebox.services import reminder_sync, records, reminders
from glovebox.services.ha_calendar import HaClient
from glovebox.services.records import VehicleInput
from glovebox.services.reminder_sync import ReminderSync
from glovebox.services.reminders import ReminderInput

ROOT = Path(__file__).resolve().parents[1]
PREFIX = {"X-Ingress-Path": "/api/hassio_ingress/abc"}


def _add(client: TestClient, **changes) -> int:
    with client.app.state.session_factory() as session:
        vehicle = records.create_vehicle(session, VehicleInput(name="Golf"))
        values = dict(vehicle_id=vehicle.id, title="Registration", category="registration",
                      due_date=date(2027, 3, 1), lead_days=30, notes="Papers; green, card")
        reminder = reminders.create_reminder(session, ReminderInput(**{**values, **changes}))
        session.commit()
        return reminder.id


def _state(client: TestClient, reminder_id: int) -> Reminder:
    with client.app.state.session_factory() as session:
        return session.get(Reminder, reminder_id)


def test_download_returns_the_ics_file(client: TestClient) -> None:
    reminder_id = _add(client)
    response = client.get(f"/reminders/{reminder_id}.ics", headers=PREFIX)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="glovebox-registration.ics"')
    text = response.content.decode()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and "SUMMARY:Golf: Registration due" in text
    assert "DTSTART;VALUE=DATE:20270301" in text


def test_download_of_an_unknown_reminder_is_404(client: TestClient) -> None:
    assert client.get("/reminders/99.ics").status_code == 404


def test_done_reopen_delete_redirect_with_the_ingress_prefix(client: TestClient) -> None:
    reminder_id = _add(client)
    done = client.post(f"/reminders/{reminder_id}/done", data={"next": "/"},
                       headers=PREFIX, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == "/api/hassio_ingress/abc/"
    assert _state(client, reminder_id).status is ReminderStatus.DONE
    client.post(f"/reminders/{reminder_id}/reopen", follow_redirects=False)
    assert _state(client, reminder_id).status is ReminderStatus.OPEN
    deleted = client.post(f"/reminders/{reminder_id}/delete", follow_redirects=False)
    assert deleted.headers["location"] == "/reminders"
    assert _state(client, reminder_id) is None


def test_next_must_stay_inside_the_app(client: TestClient) -> None:
    reminder_id = _add(client)
    response = client.post(f"/reminders/{reminder_id}/done",
                           data={"next": "//evil.example"}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_unknown_reminder_actions_are_404(client: TestClient) -> None:
    assert client.post("/reminders/99/done").status_code == 404
    assert client.post("/reminders/99/delete").status_code == 404


def test_standalone_ignores_the_calendar_choice(client: TestClient) -> None:
    assert not client.app.state.reminder_sync.available
    response = client.post("/reminders/calendar", data={"entity_id": "calendar.x"},
                           follow_redirects=False)
    assert response.status_code == 303
    with client.app.state.session_factory() as session:
        assert reminder_sync.get_calendar_entity(session) is None
    assert client.post("/reminders/sync", follow_redirects=False).status_code == 303


@pytest.fixture
def addon_client(engine: Engine, settings: Settings):
    """The app wired to a fake Home Assistant."""
    with FakeHa() as ha:
        ha.add_calendar("calendar.glovebox", "Glovebox", 7)
        app = create_app(settings, engine)
        app.state.reminder_sync = ReminderSync(
            app.state.session_factory, HaClient(TOKEN, ha.rest_url, ha.ws_url, timeout=3))
        with TestClient(app) as client:
            yield client, ha


def test_choosing_a_calendar_writes_events_and_actions_follow(addon_client) -> None:
    client, ha = addon_client
    reminder_id = _add(client)
    client.post("/reminders/calendar", data={"entity_id": "calendar.glovebox"})
    assert len(ha.events("calendar.glovebox")) == 1
    assert _state(client, reminder_id).cal_state.value == "synced"
    client.post(f"/reminders/{reminder_id}/done")
    assert ha.events("calendar.glovebox") == []
    client.post(f"/reminders/{reminder_id}/reopen")
    assert len(ha.events("calendar.glovebox")) == 1
    client.post(f"/reminders/{reminder_id}/delete")
    assert ha.events("calendar.glovebox") == []


def test_deleting_a_vehicle_removes_its_reminders_events(addon_client) -> None:
    client, ha = addon_client
    _add(client)
    client.post("/reminders/calendar", data={"entity_id": "calendar.glovebox"})
    assert len(ha.events("calendar.glovebox")) == 1
    response = client.post("/vehicles/1/delete", data={"confirm": "1"}, follow_redirects=False)
    assert response.status_code == 303
    assert ha.events("calendar.glovebox") == []


def test_a_calendar_failure_does_not_fail_the_save(addon_client) -> None:
    client, ha = addon_client
    reminder_id = _add(client)
    client.post("/reminders/calendar", data={"entity_id": "calendar.glovebox"})
    ha.status = 503
    response = client.post(f"/reminders/{reminder_id}/done", follow_redirects=False)
    assert response.status_code == 303
    assert _state(client, reminder_id).status is ReminderStatus.DONE


# --- Settings ------------------------------------------------------------------------------


def test_supervisor_token_is_read_in_addon_mode_only(tmp_path: Path) -> None:
    options = tmp_path / "options.json"
    options.write_text("{}")
    env = {"GLOVEBOX_MODE": "addon", "SUPERVISOR_TOKEN": "abc"}
    assert load_settings(env, options).supervisor_token == "abc"
    assert load_settings({"SUPERVISOR_TOKEN": "abc"}, options).supervisor_token is None
    assert load_settings({"GLOVEBOX_MODE": "addon"}, options).supervisor_token is None
    assert load_settings({"GLOVEBOX_MODE": "addon"}, options).mode is Mode.ADDON


def test_addon_config_asks_for_core_api_access() -> None:
    config = yaml.safe_load((ROOT / "addon/glovebox/config.yaml").read_text())
    assert config["homeassistant_api"] is True
    assert set(config["options"]) == {"currency"}  # no new add-on option


# --- Blueprint ------------------------------------------------------------------------------


class _Input(str):
    """A parsed ``!input name``."""


def _load_blueprint() -> dict:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!input", lambda loader, node: _Input(loader.construct_scalar(node)))
    path = ROOT / "blueprints/automation/glovebox/reminders.yaml"
    return yaml.load(path.read_text(), Loader)  # noqa: S506 - SafeLoader subclass


def test_blueprint_declares_its_inputs_and_source() -> None:
    blueprint = _load_blueprint()
    meta = blueprint["blueprint"]
    assert meta["domain"] == "automation"
    assert meta["source_url"].endswith("/master/blueprints/automation/glovebox/reminders.yaml")
    inputs = meta["input"]
    assert set(inputs) == {"calendar", "notify_time", "notify_action"}
    assert inputs["calendar"]["selector"] == {"entity": {"domain": "calendar"}}
    assert inputs["notify_time"]["default"] == "09:00:00"
    assert inputs["notify_action"]["default"] == "notify.notify"


def test_every_input_reference_is_declared() -> None:
    blueprint = _load_blueprint()
    used: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, _Input):
            used.add(str(node))
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk({k: v for k, v in blueprint.items() if k != "blueprint"})
    assert used == {"calendar", "notify_time", "notify_action"}
    assert used <= set(blueprint["blueprint"]["input"])


def test_blueprint_reads_the_event_format_glovebox_writes() -> None:
    text = (ROOT / "blueprints/automation/glovebox/reminders.yaml").read_text()
    assert reminders.MARKER_PREFIX in text
    assert "Notify (\\\\d+) days? before" in text
    assert "days: 366" in text and reminders.MAX_LEAD_DAYS == 365
