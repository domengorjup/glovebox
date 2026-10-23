"""The Core API client against a local fake Home Assistant (REST and websocket)."""

from __future__ import annotations

import socket
import threading
from datetime import date

import pytest

from fake_ha import TOKEN, FakeHa
from glovebox.services.ha_calendar import (
    CREATE_EVENT,
    DELETE_EVENT,
    UPDATE_EVENT,
    HaClient,
    HaForbidden,
    HaNotFound,
    HaRefused,
    HaUnreachable,
)

DAY = date(2027, 3, 1)


@pytest.fixture
def ha():
    with FakeHa() as fake:
        fake.add_calendar("calendar.glovebox", "Glovebox", 7)
        yield fake


@pytest.fixture
def client(ha: FakeHa) -> HaClient:
    return HaClient(TOKEN, ha.rest_url, ha.ws_url, timeout=3)


def test_lists_only_calendars_that_can_create_events(ha: FakeHa, client: HaClient) -> None:
    ha.add_calendar("calendar.adds", "Adds only", CREATE_EVENT)
    ha.add_calendar("calendar.no_delete", "No delete", CREATE_EVENT | UPDATE_EVENT)
    ha.add_calendar("calendar.readonly", "Read only", 0)
    found = {c.entity_id: c for c in client.list_calendars()}
    assert set(found) == {"calendar.glovebox", "calendar.adds", "calendar.no_delete"}
    assert found["calendar.glovebox"].capability == "Adds, changes and removes events"
    assert found["calendar.adds"].capability == "Only adds events"
    assert found["calendar.no_delete"].capability == "Adds and changes events"
    removes = ha.add_calendar("calendar.rm", "Removes", CREATE_EVENT | DELETE_EVENT)
    assert removes.features == 3
    capabilities = {c.entity_id: c.capability for c in client.list_calendars()}
    assert capabilities["calendar.rm"] == "Adds and removes events"


def test_get_calendar_reads_name_and_features(client: HaClient) -> None:
    info = client.get_calendar("calendar.glovebox")
    assert (info.name, info.features) == ("Glovebox", 7)
    assert info.can_create and info.can_update and info.can_delete


def test_create_then_list_returns_uid_and_dates(ha: FakeHa, client: HaClient) -> None:
    client.create_event("calendar.glovebox", "Golf: Registration due", "Notify 30 days before", DAY)
    [event] = client.list_events("calendar.glovebox", date(2027, 2, 1), date(2027, 4, 1))
    assert event.uid and event.start == DAY
    assert event.summary == "Golf: Registration due"
    assert event.description == "Notify 30 days before"
    assert ha.events("calendar.glovebox")[0]["end"] == {"date": "2027-03-02"}


def test_update_and_delete_over_the_websocket(ha: FakeHa, client: HaClient) -> None:
    client.create_event("calendar.glovebox", "A", "d", DAY)
    uid = ha.events("calendar.glovebox")[0]["uid"]
    client.update_event("calendar.glovebox", uid, "B", "e", date(2027, 3, 10))
    event = ha.events("calendar.glovebox")[0]
    assert (event["summary"], event["start"], event["end"]) == (
        "B", {"date": "2027-03-10"}, {"date": "2027-03-11"},
    )
    client.delete_event("calendar.glovebox", uid)
    assert ha.events("calendar.glovebox") == []


def test_every_call_sends_the_bearer_token(ha: FakeHa) -> None:
    bad = HaClient("wrong", ha.rest_url, ha.ws_url, timeout=3)
    with pytest.raises(HaForbidden):
        bad.get_calendar("calendar.glovebox")
    with pytest.raises(HaForbidden):
        bad.delete_event("calendar.glovebox", "x")  # websocket auth_invalid


def test_missing_entity_is_not_found(client: HaClient) -> None:
    with pytest.raises(HaNotFound):
        client.get_calendar("calendar.gone")
    with pytest.raises(HaNotFound):
        client.delete_event("calendar.gone", "x")  # websocket error code not_found
    with pytest.raises(HaNotFound):
        client.list_events("calendar.gone", DAY, DAY)


def test_websocket_error_is_refused(client: HaClient) -> None:
    with pytest.raises(HaRefused, match="event not found"):
        client.update_event("calendar.glovebox", "no-such-uid", "A", "d", DAY)


def test_server_errors_are_unreachable(ha: FakeHa, client: HaClient) -> None:
    ha.status = 503
    with pytest.raises(HaUnreachable):
        client.get_calendar("calendar.glovebox")


def test_unexpected_status_is_refused_and_401_is_forbidden(ha: FakeHa, client: HaClient) -> None:
    ha.status = 400
    with pytest.raises(HaRefused):
        client.get_calendar("calendar.glovebox")
    ha.status = 401
    with pytest.raises(HaForbidden):
        client.get_calendar("calendar.glovebox")


def test_connection_refused_is_unreachable() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = HaClient(TOKEN, f"http://127.0.0.1:{port}/core/api",
                      f"ws://127.0.0.1:{port}/core/websocket", timeout=1)
    with pytest.raises(HaUnreachable):
        client.get_calendar("calendar.glovebox")
    with pytest.raises(HaUnreachable):
        client.delete_event("calendar.glovebox", "x")


def test_a_server_that_never_answers_times_out() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
    held = []
    threading.Thread(target=lambda: held.append(server.accept()), daemon=True).start()
    client = HaClient(TOKEN, f"http://127.0.0.1:{port}/core/api",
                      f"ws://127.0.0.1:{port}/core/websocket", timeout=0.5)
    try:
        with pytest.raises(HaUnreachable):
            client.get_calendar("calendar.glovebox")
    finally:
        server.close()
