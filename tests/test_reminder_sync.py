"""Calendar sync of reminders against a local fake Home Assistant."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from fake_ha import TOKEN, FakeHa
from glovebox.db import make_session_factory
from glovebox.models import CalendarState, Reminder
from glovebox.services import reminder_sync, reminders, records
from glovebox.services.ha_calendar import HaClient
from glovebox.services.records import VehicleInput
from glovebox.services.reminder_sync import ReminderSync
from glovebox.services.reminders import ReminderInput

ENTITY = "calendar.glovebox"
DUE = date(2027, 3, 1)


@pytest.fixture
def ha():
    with FakeHa() as fake:
        yield fake


@pytest.fixture
def factory(engine: Engine):
    return make_session_factory(engine)


def _client(ha: FakeHa, token: str = TOKEN, timeout: float = 3) -> HaClient:
    return HaClient(token, ha.rest_url, ha.ws_url, timeout=timeout)


def _setup(factory, ha: FakeHa, features: int = 7, entity: str | None = ENTITY):
    """A vehicle, one open reminder and the chosen calendar; returns (sync, id)."""
    ha.add_calendar(ENTITY, "Glovebox", features)
    with factory() as session:
        vehicle = records.create_vehicle(session, VehicleInput(name="Golf"))
        reminder = reminders.create_reminder(session, ReminderInput(
            vehicle.id, "Registration", "registration", DUE, 30, notes="Papers"))
        reminder_sync.set_calendar(session, entity)
        session.commit()
        reminder_id = reminder.id
    return ReminderSync(factory, _client(ha)), reminder_id


def _get(factory, reminder_id: int) -> Reminder:
    with factory() as session:
        return session.get(Reminder, reminder_id)


def _edit(factory, reminder_id: int, **changes) -> None:
    with factory() as session:
        current = session.get(Reminder, reminder_id)
        data = ReminderInput(current.vehicle_id, current.title, current.category.value,
                             current.due_date, current.lead_days, current.notes)
        reminders.update_reminder(session, reminder_id, replace(data, **changes))
        session.commit()


def _call(factory, name: str, reminder_id: int) -> None:
    with factory() as session:
        getattr(reminders, name)(session, reminder_id)
        session.commit()


# --- Features 7: everything --------------------------------------------------------


def test_new_reminder_becomes_an_event_with_uid_and_marker(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    [event] = ha.events(ENTITY)
    reminder = _get(factory, rid)
    assert event["summary"] == "Golf: Registration due"
    assert event["start"] == {"date": "2027-03-01"} and event["end"] == {"date": "2027-03-02"}
    assert event["description"].splitlines() == [
        "Papers", "Notify 30 days before", f"Glovebox reminder {reminder.uid}",
    ]
    assert reminder.cal_uid == event["uid"] and reminder.cal_entity == ENTITY
    assert (reminder.cal_state, reminder.cal_message) == (CalendarState.SYNCED, None)


def test_an_unchanged_reminder_is_not_touched_again(factory, ha) -> None:
    sync, _ = _setup(factory, ha)
    sync.run()
    calls = len(ha.calls)
    sync.run()
    # only the check of the calendar itself: no listing, no create, no update
    assert ha.calls[calls:] == [("GET", f"/core/api/states/{ENTITY}")]


def test_edit_updates_the_same_event(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    uid = ha.events(ENTITY)[0]["uid"]
    _edit(factory, rid, due_date=date(2027, 3, 10), lead_days=7)
    sync.run()
    [event] = ha.events(ENTITY)
    assert event["uid"] == uid and event["start"] == {"date": "2027-03-10"}
    assert "Notify 7 days before" in event["description"]
    assert _get(factory, rid).cal_state is CalendarState.SYNCED


def test_done_removes_the_event_and_reopen_writes_it_again(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    _call(factory, "mark_done", rid)
    sync.run()
    reminder = _get(factory, rid)
    assert ha.events(ENTITY) == []
    assert (reminder.cal_state, reminder.cal_entity, reminder.cal_uid) == (
        CalendarState.NONE, None, None)
    _call(factory, "reopen", rid)
    sync.run()
    assert len(ha.events(ENTITY)) == 1


def test_delete_removes_the_event(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    _call(factory, "delete_reminder", rid)
    sync.run()
    assert ha.events(ENTITY) == []
    with factory() as session:
        assert reminders.load_removal_notes(session) == []


# --- Other capabilities -----------------------------------------------------------------


def test_calendar_that_cannot_change_events(factory, ha) -> None:
    sync, rid = _setup(factory, ha, features=3)  # create + delete
    sync.run()
    _edit(factory, rid, due_date=date(2027, 3, 10))
    sync.run()
    reminder = _get(factory, rid)
    assert ha.events(ENTITY)[0]["start"] == {"date": "2027-03-01"}
    assert reminder.cal_state is CalendarState.UNCHANGED
    assert reminder.cal_message == "This calendar can't change events; edit it there."
    calls = len(ha.calls)
    sync.run()  # no loop: the reminder is settled
    assert [c for c in ha.calls[calls:] if c[0] == "WS"] == []
    _call(factory, "mark_done", rid)
    sync.run()
    assert ha.events(ENTITY) == []  # removing is supported


def test_calendar_that_cannot_remove_events(factory, ha) -> None:
    sync, rid = _setup(factory, ha, features=5)  # create + update
    sync.run()
    _edit(factory, rid, due_date=date(2027, 3, 10))
    sync.run()
    assert ha.events(ENTITY)[0]["start"] == {"date": "2027-03-10"}
    _call(factory, "mark_done", rid)
    sync.run()
    reminder = _get(factory, rid)
    assert len(ha.events(ENTITY)) == 1
    assert reminder.cal_state is CalendarState.UNCHANGED
    assert reminder.cal_message == "This calendar can't remove events; remove it there."


def test_calendar_that_only_adds_events(factory, ha) -> None:
    sync, rid = _setup(factory, ha, features=1)
    sync.run()
    assert len(ha.events(ENTITY)) == 1
    _edit(factory, rid, title="Renewal")
    sync.run()
    assert _get(factory, rid).cal_message == "This calendar can't change events; edit it there."
    _call(factory, "mark_done", rid)
    sync.run()
    assert len(ha.events(ENTITY)) == 1
    assert _get(factory, rid).cal_message == "This calendar can't remove events; remove it there."


# --- Find first -------------------------------------------------------------------------


def test_existing_event_is_reused_not_duplicated(factory, ha) -> None:
    """A restore into a calendar that already holds the event."""
    sync, rid = _setup(factory, ha)
    sync.run()
    uid = ha.events(ENTITY)[0]["uid"]
    with factory() as session:  # as after a restore: no memory of the event
        reminder = session.get(Reminder, rid)
        reminder.cal_entity = reminder.cal_uid = reminder.cal_synced_revision = None
        reminder.cal_state = CalendarState.PENDING
        session.commit()
    sync.run()
    [event] = ha.events(ENTITY)
    assert event["uid"] == uid
    assert _get(factory, rid).cal_uid == uid


def test_retry_after_a_timed_out_create_does_not_duplicate(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    hanging = ReminderSync(factory, _client(ha, timeout=0.3))
    ha.status = 503
    hanging.run()  # create never reached
    ha.status = None
    # the create reached HA but the answer was lost: the event exists, the row does not know
    ha.create(ENTITY, {
        "summary": "Golf: Registration due", "start_date": "2027-03-01",
        "end_date": "2027-03-02",
        "description": f"Notify 30 days before\nGlovebox reminder {_get(factory, rid).uid}",
    })
    sync.run()
    assert len(ha.events(ENTITY)) == 1


def test_event_not_listed_yet_waits_and_does_not_create_again(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    ha.delay_listing = 3
    sync.run()
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.PENDING
    assert reminder.cal_message == "Waiting for the calendar to list the new event."
    sync.run()  # still not listed
    ha.delay_listing = 0
    sync.run()
    assert len(ha.events(ENTITY)) == 1
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.SYNCED and reminder.cal_uid


# --- Changing the calendar ---------------------------------------------------------------


def test_switching_calendar_moves_the_event(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    ha.add_calendar("calendar.other", "Other", 7)
    with factory() as session:
        reminder_sync.set_calendar(session, "calendar.other")
        session.commit()
    sync.run()
    assert ha.events(ENTITY) == [] and len(ha.events("calendar.other")) == 1
    assert _get(factory, rid).cal_entity == "calendar.other"


def test_switching_away_from_a_calendar_that_cannot_remove_reports_it(factory, ha) -> None:
    sync, _ = _setup(factory, ha, features=1)
    sync.run()
    ha.add_calendar("calendar.other", "Other", 7)
    with factory() as session:
        reminder_sync.set_calendar(session, "calendar.other")
        session.commit()
    sync.run()
    assert len(ha.events(ENTITY)) == 1 and len(ha.events("calendar.other")) == 1
    with factory() as session:
        status = reminder_sync.calendar_status(session, available=True)
    assert (status.left_behind, status.left_behind_entity) == (1, ENTITY)


def test_choosing_none_removes_events_and_stops_writing(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    with factory() as session:
        reminder_sync.set_calendar(session, None)
        session.commit()
    sync.run()
    assert ha.events(ENTITY) == []
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.NONE and reminder.cal_entity is None
    _edit(factory, rid, title="Other")
    sync.run()
    assert ha.events(ENTITY) == []


# --- Failures -----------------------------------------------------------------------------


def test_ha_not_answering_keeps_the_reminder_pending_then_retry_writes(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    ha.status = 503
    sync.run()
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.PENDING
    assert reminder.cal_message == "Home Assistant did not answer. Will retry."
    ha.status = None
    sync.run()
    assert _get(factory, rid).cal_state is CalendarState.SYNCED
    assert len(ha.events(ENTITY)) == 1


def test_timeout_is_pending(factory, ha) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
    _, rid = _setup(factory, ha)
    silent = HaClient(TOKEN, f"http://127.0.0.1:{port}/core/api",
                      f"ws://127.0.0.1:{port}/core/websocket", timeout=0.3)
    try:
        ReminderSync(factory, silent).run()
    finally:
        server.close()
    assert _get(factory, rid).cal_state is CalendarState.PENDING


def test_refused_token_is_an_error_with_a_plain_message(factory, ha) -> None:
    _, rid = _setup(factory, ha)
    ReminderSync(factory, _client(ha, token="wrong")).run()
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.ERROR
    assert reminder.cal_message == (
        "Glovebox may not use the Home Assistant API. Update or reinstall the add-on.")


def test_missing_calendar_entity_is_an_error_and_a_warning(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    del ha.calendars[ENTITY]
    _edit(factory, rid, title="Renewal")
    sync.run()
    reminder = _get(factory, rid)
    expected = f"Calendar {ENTITY} no longer exists. Choose another calendar."
    assert (reminder.cal_state, reminder.cal_message) == (CalendarState.ERROR, expected)
    with factory() as session:
        assert reminder_sync.calendar_status(session, True).problem == expected


def test_calendar_removed_while_all_synced_is_noticed_and_rewritten(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    with factory() as session:
        other = reminders.create_reminder(session, ReminderInput(
            _get(factory, rid).vehicle_id, "Insurance", "insurance", DUE, 14))
        session.commit()
        other_id = other.id
    sync.run()
    assert len(ha.events(ENTITY)) == 2
    del ha.calendars[ENTITY]
    sync.run()  # the background pass, nothing edited
    expected = f"Calendar {ENTITY} no longer exists. Choose another calendar."
    for reminder_id in (rid, other_id):
        reminder = _get(factory, reminder_id)
        assert (reminder.cal_state, reminder.cal_message) == (CalendarState.ERROR, expected)
    ha.add_calendar(ENTITY, "Glovebox")  # added again, empty
    sync.run()
    assert len(ha.events(ENTITY)) == 2
    assert _get(factory, other_id).cal_state is CalendarState.SYNCED
    with factory() as session:
        assert reminder_sync.calendar_status(session, True).problem is None


def test_sync_now_rewrites_events_lost_between_passes(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    del ha.calendars[ENTITY]
    ha.add_calendar(ENTITY, "Glovebox")  # removed and added again between passes
    sync.run()
    assert ha.events(ENTITY) == []  # a normal pass only checks the calendar
    sync.run(full=True)
    [event] = ha.events(ENTITY)
    assert _get(factory, rid).cal_uid == event["uid"]
    sync.run(full=True)  # nothing lost: found by its marker, not created again
    assert len(ha.events(ENTITY)) == 1


def test_calendar_that_lost_the_create_feature(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    ha.calendars[ENTITY].features = 0
    _edit(factory, rid, title="Renewal")
    sync.run()
    reminder = _get(factory, rid)
    assert reminder.cal_state is CalendarState.ERROR
    assert reminder.cal_message == (
        "Calendar Glovebox no longer accepts new events. Choose another calendar.")


def test_recovery_clears_the_error_and_the_warning(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    ha.calendars[ENTITY].features = 0
    sync.run()
    ha.calendars[ENTITY].features = 7
    sync.run()
    assert _get(factory, rid).cal_state is CalendarState.SYNCED
    with factory() as session:
        assert reminder_sync.calendar_status(session, True).problem is None


def test_a_failure_never_raises_from_run_safely(factory, ha, caplog) -> None:
    sync, rid = _setup(factory, ha)
    ha.status = 500
    sync.run_safely(10)
    assert _get(factory, rid) is not None


def test_removal_is_postponed_while_ha_is_down(factory, ha) -> None:
    sync, rid = _setup(factory, ha)
    sync.run()
    _call(factory, "delete_reminder", rid)
    ha.status = 503
    sync.run()
    assert len(ha.events(ENTITY)) == 1
    with factory() as session:
        assert len(reminders.load_removal_notes(session)) == 1
    ha.status = None
    sync.run()
    assert ha.events(ENTITY) == []


# --- Without Home Assistant --------------------------------------------------------------


def test_without_a_client_nothing_happens(factory) -> None:
    sync = ReminderSync(factory, None)
    assert not sync.available
    sync.run()
    assert sync.list_choices() == ([], None)


def test_choices_list_calendars_that_can_create(factory, ha) -> None:
    sync, _ = _setup(factory, ha)
    ha.add_calendar("calendar.readonly", "Read only", 0)
    choices, problem = sync.list_choices()
    assert [c.entity_id for c in choices] == [ENTITY] and problem is None
    ha.status = 503
    assert sync.list_choices() == ([], "Home Assistant did not answer. Will retry.")


def test_retry_loop_runs_at_startup_and_repeats(factory, ha) -> None:
    sync, _ = _setup(factory, ha)

    async def scenario() -> None:
        task = asyncio.create_task(sync.retry_forever(interval_seconds=0.05))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(ha.events(ENTITY)) == 1


def test_client_for_needs_a_supervisor_token() -> None:
    from glovebox.config import Settings

    assert reminder_sync.client_for(Settings()) is None
    assert reminder_sync.client_for(Settings(supervisor_token="t")) is not None
