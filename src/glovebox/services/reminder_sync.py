"""
Calendar sync of reminders (design D4, D5): one-way, open reminders to one
Home Assistant calendar.

The pass adapts only to the calendar's ``supported_features``. It finds an
event by the marker line in its description before it creates one, so retries
and restores do not duplicate events. A failure never undoes a save: the
reminder keeps a state and a plain-language message, and the pass runs again
at startup and every 15 minutes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from glovebox.config import Settings
from glovebox.models import CalendarState, Reminder, ReminderStatus, Vehicle
from glovebox.services import reminders as reminder_service
from glovebox.services.ha_calendar import (
    CalendarEvent,
    CalendarInfo,
    HaClient,
    HaError,
    HaForbidden,
    HaNotFound,
    HaRefused,
    HaUnreachable,
)
from glovebox.services.preferences import get_setting, set_setting

logger = logging.getLogger(__name__)

CALENDAR_SETTING = "reminders.calendar"
PROBLEM_SETTING = "reminders.calendar_problem"
LEFT_BEHIND_SETTING = "reminders.left_behind"
RETRY_INTERVAL_SECONDS = 15 * 60
SAVE_DEADLINE_SECONDS = 10.0
# Events are looked up this many days around the due dates, so that an event
# the user moved a little in the calendar is still found.
LOOKUP_MARGIN_DAYS = 31

MSG_UNREACHABLE = "Home Assistant did not answer. Will retry."
MSG_FORBIDDEN = (
    "Glovebox may not use the Home Assistant API. Update or reinstall the add-on."
)
MSG_WAITING = "Waiting for the calendar to list the new event."
MSG_CANT_CHANGE = "This calendar can't change events; edit it there."
MSG_CANT_REMOVE = "This calendar can't remove events; remove it there."


def msg_entity_gone(entity_id: str) -> str:
    """Message for a calendar entity that no longer exists."""
    return f"Calendar {entity_id} no longer exists. Choose another calendar."


def msg_cannot_create(name: str) -> str:
    """Message for a calendar that no longer accepts new events."""
    return f"Calendar {name} no longer accepts new events. Choose another calendar."


# --- The calendar setting -------------------------------------------------------


def get_calendar_entity(session: Session) -> str | None:
    """The chosen calendar entity id, or ``None``."""
    return get_setting(session, CALENDAR_SETTING) or None


def set_calendar(session: Session, entity_id: str | None) -> None:
    """
    Choose the calendar (``None`` stops writing).

    Events already written are noted for removal from the old calendar, and
    open reminders are marked to be written to the new one. The next sync pass
    does the work.
    """
    entity_id = (entity_id or "").strip() or None
    if entity_id == get_calendar_entity(session):
        return
    set_setting(session, CALENDAR_SETTING, entity_id or "")
    set_setting(session, PROBLEM_SETTING, "")
    set_setting(session, LEFT_BEHIND_SETTING, "")
    for reminder in session.scalars(select(Reminder)):
        reminder_service.leave_removal_note(session, reminder)
        reminder.cal_entity = reminder.cal_uid = None
        reminder.cal_synced_revision = reminder.cal_synced_due = None
        reminder.cal_message = None
        wanted = entity_id and reminder.status is ReminderStatus.OPEN
        reminder.cal_state = CalendarState.PENDING if wanted else CalendarState.NONE
    session.flush()


@dataclass(frozen=True)
class CalendarStatus:
    """What the calendar setting shows besides the choice."""

    available: bool  # add-on mode with a token
    entity_id: str | None
    problem: str | None  # the calendar is gone or cannot take events
    left_behind: int  # events the old calendar could not remove
    left_behind_entity: str | None


def calendar_status(session: Session, available: bool) -> CalendarStatus:
    """Read the stored sync status for the Reminders page."""
    raw = get_setting(session, LEFT_BEHIND_SETTING)
    try:
        left = json.loads(raw) if raw else {}
    except ValueError:
        left = {}
    return CalendarStatus(
        available=available,
        entity_id=get_calendar_entity(session),
        problem=get_setting(session, PROBLEM_SETTING) or None,
        left_behind=int(left.get("count", 0)),
        left_behind_entity=left.get("entity"),
    )


# --- The sync pass ---------------------------------------------------------------


class _Removal(Enum):
    DONE = "done"  # removed, or there was nothing to remove
    CANNOT = "cannot"  # the calendar cannot remove events


class ReminderSync:
    """
    Runs the sync pass. One pass at a time (a lock); every call opens its own
    session, so it can run in a worker thread.

    Parameters
    ----------
    session_factory : sessionmaker[Session]
        Database sessions.
    client : HaClient | None
        ``None`` when there is no Home Assistant connection (standalone mode):
        every method then does nothing.
    """

    def __init__(
        self, session_factory: sessionmaker[Session], client: HaClient | None
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """True if there is a Home Assistant connection."""
        return self._client is not None

    def list_choices(self) -> tuple[list[CalendarInfo], str | None]:
        """Calendars that can create events, and a message if listing failed."""
        if self._client is None:
            return [], None
        try:
            return self._client.list_calendars(), None
        except HaForbidden:
            return [], MSG_FORBIDDEN
        except HaError:
            return [], MSG_UNREACHABLE

    def run(self, deadline_seconds: float | None = None) -> None:
        """
        Run one pass: removals, then every reminder that is out of date.

        Parameters
        ----------
        deadline_seconds : float | None, optional
            Stop starting new work after this long; what is left waits for
            the background retry.
        """
        if self._client is None:
            return
        deadline = None if deadline_seconds is None else time.monotonic() + deadline_seconds
        with self._lock, self._session_factory() as session:
            try:
                _Pass(self._client, session, deadline).run()
            except BaseException:
                session.rollback()
                raise

    def run_safely(self, deadline_seconds: float | None = None) -> None:
        """``run`` for callers that must never fail: errors are logged."""
        try:
            self.run(deadline_seconds)
        except Exception:  # noqa: BLE001 - a save must not fail on the calendar
            logger.exception("Reminder calendar sync failed")

    async def retry_forever(
        self, interval_seconds: float = RETRY_INTERVAL_SECONDS
    ) -> None:
        """Background task: sync once at startup, then every ``interval_seconds``."""
        while True:
            await asyncio.to_thread(self.run_safely)
            await asyncio.sleep(interval_seconds)


def client_for(settings: Settings) -> HaClient | None:
    """A Core API client in add-on mode with a Supervisor token, else ``None``."""
    return HaClient(settings.supervisor_token) if settings.supervisor_token else None


class _Pass:
    """State of one sync pass."""

    def __init__(
        self, client: HaClient, session: Session, deadline: float | None
    ) -> None:
        self.client = client
        self.session = session
        self.deadline = deadline
        self._infos: dict[str, CalendarInfo] = {}

    def run(self) -> None:
        self._process_removal_notes()
        entity = get_calendar_entity(self.session)
        if entity is None:
            self._settle_unwritten()
            return
        targets = self._targets()
        info = self._check_calendar(entity, targets)
        if info is None:
            return
        for index, reminder in enumerate(targets):
            if self.deadline is not None and time.monotonic() > self.deadline:
                return
            try:
                self._sync(reminder, info)
            except (HaUnreachable, HaForbidden, HaNotFound) as error:
                for rest in targets[index:]:
                    self._record_failure(rest, error, entity)
                self.session.commit()
                return
            except HaRefused as error:
                self._record_failure(reminder, error, entity)
            self.session.commit()

    # --- Choosing the work -------------------------------------------------

    def _targets(self) -> list[Reminder]:
        found = []
        for reminder in self.session.scalars(select(Reminder).order_by(Reminder.id)):
            retry = reminder.cal_state in (CalendarState.PENDING, CalendarState.ERROR)
            stale = reminder.cal_synced_revision != reminder.revision
            if reminder.status is ReminderStatus.OPEN:
                if stale or retry:
                    found.append(reminder)
            elif reminder.cal_entity and (stale or retry):
                found.append(reminder)
        return found

    def _settle_unwritten(self) -> None:
        """No calendar chosen: nothing is pending."""
        for reminder in self.session.scalars(select(Reminder)):
            if reminder.cal_state is not CalendarState.NONE and not reminder.cal_entity:
                reminder.cal_state, reminder.cal_message = CalendarState.NONE, None
        self.session.commit()

    def _check_calendar(
        self, entity: str, targets: list[Reminder]
    ) -> CalendarInfo | None:
        """The chosen calendar if it can take events; else record why not."""
        try:
            info = self._info(entity)
        except HaError as error:
            for reminder in targets:
                self._record_failure(reminder, error, entity)
            self.session.commit()
            return None
        if info.can_create:
            set_setting(self.session, PROBLEM_SETTING, "")
            return info
        message = msg_cannot_create(info.name)
        set_setting(self.session, PROBLEM_SETTING, message)
        for reminder in targets:
            reminder.cal_state, reminder.cal_message = CalendarState.ERROR, message
        self.session.commit()
        return None

    def _info(self, entity: str) -> CalendarInfo:
        if entity not in self._infos:
            self._infos[entity] = self.client.get_calendar(entity)
        return self._infos[entity]

    # --- One reminder --------------------------------------------------------

    def _sync(self, reminder: Reminder, info: CalendarInfo) -> None:
        if reminder.status is ReminderStatus.DONE:
            self._sync_done(reminder)
        else:
            self._sync_open(reminder, info)

    def _sync_open(self, reminder: Reminder, info: CalendarInfo) -> None:
        found = self._find(info.entity_id, reminder.uid, _lookup_days(reminder))
        if found is not None:
            self._sync_existing(reminder, info, found)
            return
        waiting = (
            reminder.cal_state is CalendarState.PENDING
            and reminder.cal_message == MSG_WAITING
        )
        if waiting:  # created earlier, not listed yet: look again, do not create
            return
        reminder.cal_entity = info.entity_id  # recorded first: the create may time out
        self.session.commit()
        name = self._vehicle_name(reminder)
        self.client.create_event(
            info.entity_id,
            reminder_service.event_summary(name, reminder.title),
            reminder_service.event_description(reminder),
            reminder.due_date,
        )
        found = self._find(info.entity_id, reminder.uid, _lookup_days(reminder))
        if found is None:
            reminder.cal_state, reminder.cal_message = CalendarState.PENDING, MSG_WAITING
            return
        self._mark_synced(reminder, info.entity_id, found.uid)

    def _sync_existing(
        self, reminder: Reminder, info: CalendarInfo, found: CalendarEvent
    ) -> None:
        summary = reminder_service.event_summary(
            self._vehicle_name(reminder), reminder.title
        )
        description = reminder_service.event_description(reminder)
        current = (found.summary, found.description, found.start) == (
            summary, description, reminder.due_date,
        )  # fmt: skip
        if current:
            self._mark_synced(reminder, info.entity_id, found.uid)
        elif info.can_update and found.uid:
            self.client.update_event(
                info.entity_id, found.uid, summary, description, reminder.due_date
            )
            self._mark_synced(reminder, info.entity_id, found.uid)
        else:
            reminder.cal_entity, reminder.cal_uid = info.entity_id, found.uid
            reminder.cal_state = CalendarState.UNCHANGED
            reminder.cal_message = MSG_CANT_CHANGE
            reminder.cal_synced_revision = reminder.revision
            reminder.cal_synced_due = found.start or reminder.cal_synced_due

    def _sync_done(self, reminder: Reminder) -> None:
        outcome = self._remove(
            reminder.cal_entity, reminder.cal_uid, reminder.uid, _lookup_days(reminder)
        )
        if outcome is _Removal.DONE:
            reminder.cal_entity = reminder.cal_uid = None
            reminder.cal_synced_revision = reminder.cal_synced_due = None
            reminder.cal_state, reminder.cal_message = CalendarState.NONE, None
        else:
            reminder.cal_state = CalendarState.UNCHANGED
            reminder.cal_message = MSG_CANT_REMOVE
            reminder.cal_synced_revision = reminder.revision

    def _mark_synced(self, reminder: Reminder, entity: str, uid: str | None) -> None:
        reminder.cal_entity, reminder.cal_uid = entity, uid
        reminder.cal_state, reminder.cal_message = CalendarState.SYNCED, None
        reminder.cal_synced_revision = reminder.revision
        reminder.cal_synced_due = reminder.due_date

    def _record_failure(self, reminder: Reminder, error: HaError, entity: str) -> None:
        logger.warning("Calendar sync of reminder %s failed: %s", reminder.uid, error)
        if isinstance(error, HaUnreachable):
            state, message = CalendarState.PENDING, MSG_UNREACHABLE
        elif isinstance(error, HaForbidden):
            state, message = CalendarState.ERROR, MSG_FORBIDDEN
        elif isinstance(error, HaNotFound):
            message = msg_entity_gone(entity)
            set_setting(self.session, PROBLEM_SETTING, message)
            state = CalendarState.ERROR
        else:
            state = CalendarState.ERROR
            message = f"Home Assistant refused the change: {error}"
        reminder.cal_state, reminder.cal_message = state, message

    # --- Events -----------------------------------------------------------------

    def _vehicle_name(self, reminder: Reminder) -> str:
        vehicle = self.session.get(Vehicle, reminder.vehicle_id)
        return vehicle.name if vehicle else ""

    def _find(
        self, entity: str, marker_uid: str, days: tuple[date, date]
    ) -> CalendarEvent | None:
        marker = f"{reminder_service.MARKER_PREFIX} {marker_uid}"
        for event in self.client.list_events(entity, *days):
            if marker in event.description:
                return event
        return None

    def _remove(
        self, entity: str | None, uid: str | None, marker_uid: str, days: tuple[date, date]
    ) -> _Removal:
        """Remove an event; a calendar or event that is gone counts as removed."""
        if not entity:
            return _Removal.DONE
        try:
            info = self._info(entity)
            if uid is None:
                found = self._find(entity, marker_uid, days)
                if found is None or found.uid is None:
                    return _Removal.DONE
                uid = found.uid
            if not info.can_delete:
                return _Removal.CANNOT
            self.client.delete_event(entity, uid)
        except HaNotFound:
            pass
        return _Removal.DONE

    def _process_removal_notes(self) -> None:
        notes = reminder_service.load_removal_notes(self.session)
        if not notes:
            return
        kept, left_behind = [], {}
        for index, note in enumerate(notes):
            try:
                due = date.fromisoformat(note["due"])
                outcome = self._remove(
                    note["entity"], note.get("uid"), note["marker"], _window(due, due)
                )
            except (HaUnreachable, HaForbidden) as error:
                logger.warning("Calendar event removal postponed: %s", error)
                kept.extend(notes[index:])
                break
            except (HaRefused, KeyError, ValueError) as error:
                logger.warning("Calendar event removal given up: %s", error)
                continue
            if outcome is _Removal.CANNOT:
                left_behind[note["entity"]] = left_behind.get(note["entity"], 0) + 1
        reminder_service.save_removal_notes(self.session, kept)
        if left_behind:
            self._add_left_behind(left_behind)
        self.session.commit()

    def _add_left_behind(self, counts: dict[str, int]) -> None:
        entity, count = max(counts.items(), key=lambda item: item[1])
        raw = get_setting(self.session, LEFT_BEHIND_SETTING)
        previous = json.loads(raw) if raw else {}
        total = int(previous.get("count", 0)) if previous.get("entity") == entity else 0
        set_setting(
            self.session,
            LEFT_BEHIND_SETTING,
            json.dumps({"entity": entity, "count": total + sum(counts.values())}),
        )


def _window(first: date, last: date) -> tuple[date, date]:
    margin = timedelta(days=LOOKUP_MARGIN_DAYS)
    return min(first, last) - margin, max(first, last) + margin


def _lookup_days(reminder: Reminder) -> tuple[date, date]:
    return _window(reminder.due_date, reminder.cal_synced_due or reminder.due_date)
