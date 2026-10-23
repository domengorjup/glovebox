"""reminders.csv: standard format, full backup, restore, old backups, undo."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from glovebox import standard
from glovebox.config import Settings
from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.exporters.backup import export_backup
from glovebox.importers import engine, pipeline
from glovebox.importers.pipeline import VehicleMapping
from glovebox.models import CalendarState, Reminder, ReminderStatus
from glovebox.services import reminder_sync, records, reminders
from glovebox.services.records import VehicleInput
from glovebox.services.reminders import ReminderInput

HEADER = ",".join(f.name for f in standard.REMINDER_FIELDS)


@pytest.fixture
def other_session() -> Iterator[Session]:
    """A second, empty database to restore into."""
    engine = make_engine()
    run_migrations(engine)
    with make_session_factory(engine)() as session:
        yield session
    engine.dispose()


def _populate(session: Session) -> None:
    golf = records.create_vehicle(session, VehicleInput(name="Golf"))
    polo = records.create_vehicle(session, VehicleInput(name="Polo"))
    reminders.create_reminder(session, ReminderInput(
        golf.id, "Registration", "registration", date(2027, 3, 1), 14,
        notes='Bring "papers", ok', vehicle_field="registration_valid_until"))
    done = reminders.create_reminder(session, ReminderInput(
        golf.id, "Oil", "maintenance", date(2026, 5, 1), 30))
    reminders.mark_done(session, done.id)
    done.done_at = datetime(2026, 4, 20, 12, 0)
    reminders.create_reminder(session, ReminderInput(
        polo.id, "Policy", "insurance", date(2027, 6, 30), 0))
    session.commit()


def _zip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n).decode("utf-8") for n in archive.namelist()}


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _restore(session: Session, data: bytes):
    return pipeline.commit_import(session, data, "backup.zip", VehicleMapping())


def test_columns_are_the_documented_ones() -> None:
    assert HEADER == "uid,vehicle,title,category,due_date,lead_days,status,done_date,vehicle_field,notes"
    assert list(standard.TABLES) == ["records", "vehicles", "stations", "reminders"]
    resource = {r["name"]: r for r in standard.datapackage()["resources"]}["reminders"]
    assert [f["name"] for f in resource["schema"]["fields"]] == HEADER.split(",")
    required = [f["name"] for f in resource["schema"]["fields"]
                if f.get("constraints", {}).get("required")]
    assert required == ["vehicle", "title", "due_date"]


def test_backup_writes_every_reminder_once(session: Session) -> None:
    _populate(session)
    files = _zip(export_backup(session, Settings()))
    rows = _rows(files["reminders.csv"])
    assert files["reminders.csv"].splitlines()[0] == HEADER
    assert [r["title"] for r in rows] == ["Registration", "Oil", "Policy"]
    first, done, third = rows
    assert first["vehicle"] == "Golf" and first["due_date"] == "2027-03-01"
    assert first["lead_days"] == "14" and first["status"] == "open"
    assert first["done_date"] == "" and first["vehicle_field"] == "registration_valid_until"
    assert first["notes"] == 'Bring "papers", ok'
    assert (done["status"], done["done_date"]) == ("done", "2026-04-20")
    assert third["lead_days"] == "0"
    assert len({r["uid"] for r in rows}) == 3
    assert [r["name"] for r in json.loads(files["datapackage.json"])["resources"]][-1] == "reminders"


def test_backup_without_reminders_has_only_the_header(session: Session) -> None:
    files = _zip(export_backup(session, Settings()))
    assert files["reminders.csv"] == HEADER + "\r\n"


def test_backup_respects_the_vehicle_selection(session: Session) -> None:
    _populate(session)
    polo = next(v for v in records.list_vehicles(session) if v.name == "Polo")
    rows = _rows(_zip(export_backup(session, Settings(), [polo.id]))["reminders.csv"])
    assert [r["title"] for r in rows] == ["Policy"]


def test_round_trip_gives_identical_reminders_csv(session: Session, other_session: Session) -> None:
    _populate(session)
    first = export_backup(session, Settings())
    preview = pipeline.preview_import(other_session, first)
    assert (preview.new_reminders, preview.duplicate_reminders) == (3, 0)
    _restore(other_session, first)
    second = export_backup(other_session, Settings())
    assert _zip(second)["reminders.csv"] == _zip(first)["reminders.csv"]
    restored = {r.title: r for r in other_session.scalars(select(Reminder))}
    assert restored["Oil"].status is ReminderStatus.DONE
    assert restored["Registration"].vehicle_field == "registration_valid_until"
    assert restored["Registration"].expense_id is None
    assert restored["Registration"].cal_state is CalendarState.NONE


def test_restoring_twice_lists_duplicates(session: Session, other_session: Session) -> None:
    _populate(session)
    data = export_backup(session, Settings())
    _restore(other_session, data)
    preview = pipeline.preview_import(other_session, data)
    assert (preview.new_reminders, preview.duplicate_reminders) == (0, 3)
    assert preview.nothing_new
    assert len(other_session.scalars(select(Reminder)).all()) == 3


def test_old_backup_without_reminders_csv_still_restores(
    session: Session, other_session: Session
) -> None:
    _populate(session)
    files = _zip(export_backup(session, Settings()))
    del files["reminders.csv"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    preview = pipeline.preview_import(other_session, buffer.getvalue())
    assert preview.errors == [] and preview.new_reminders == 0
    pipeline.commit_import(other_session, buffer.getvalue(), "old.zip", VehicleMapping())
    assert [v.name for v in records.list_vehicles(other_session)] == ["Golf", "Polo"]
    assert other_session.scalars(select(Reminder)).all() == []


def test_reminders_alone_in_a_zip(other_session: Session) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "reminders.csv",
            f"{HEADER}\r\n,Golf,Registration,registration,2027-03-01,,,,,\r\n",
        )
    data = buffer.getvalue()
    preview = pipeline.preview_import(other_session, data, engine.standard_preset())
    assert preview.new_reminders == 1 and "Golf" in preview.vehicle_names
    pipeline.commit_import(
        other_session, data, "r.zip", VehicleMapping(), engine.standard_preset()
    )
    [reminder] = other_session.scalars(select(Reminder)).all()
    assert (reminder.lead_days, reminder.status, reminder.uid) == (30, ReminderStatus.OPEN, reminder.uid)
    assert len(reminder.uid) == 36 and reminder.vehicle_id


def test_the_vehicle_mapping_applies_to_reminders(session: Session, other_session: Session) -> None:
    _populate(session)
    data = export_backup(session, Settings())
    target = records.create_vehicle(other_session, VehicleInput(name="Company car"))
    mapping = VehicleMapping(by_name={"Golf": target.id})
    pipeline.commit_import(other_session, data, "b.zip", mapping)
    golf_titles = {r.title for r in other_session.scalars(
        select(Reminder).where(Reminder.vehicle_id == target.id))}
    assert golf_titles == {"Registration", "Oil"}


@pytest.mark.parametrize(
    "row",
    [
        ",Golf,,other,2027-03-01,30,open,,,",  # no title
        ",Golf,T,other,,30,open,,,",  # no due date
        ",Golf,T,other,01.03.2027,30,open,,,",  # bad date
        ",Golf,T,bogus,2027-03-01,30,open,,,",  # unknown category
        ",Golf,T,other,2027-03-01,30,pending,,,",  # unknown status
        ",Golf,T,other,2027-03-01,-1,open,,,",  # negative lead days
        ",Golf,T,other,2027-03-01,366,open,,,",
        ",Golf,T,other,2027-03-01,x,open,,,",
        ",,T,other,2027-03-01,30,open,,,",  # no vehicle
        ",Golf,T,other,2027-03-01,30,open,,bogus,",  # unknown vehicle_field
    ],
)
def test_bad_rows_are_listed_as_errors_and_not_imported(other_session: Session, row: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("reminders.csv", f"{HEADER}\r\n{row}\r\n"
                         ",Golf,Good,other,2027-03-01,30,open,,,\r\n")
    preview = pipeline.preview_import(
        other_session, buffer.getvalue(), engine.standard_preset()
    )
    assert len(preview.row_errors) == 1 and preview.row_errors[0].message.startswith("reminders.csv")
    assert preview.new_reminders == 1 and preview.errors == []


def test_undo_removes_the_imported_reminders_and_notes_their_events(
    session: Session, other_session: Session
) -> None:
    _populate(session)
    data = export_backup(session, Settings())
    batch = _restore(other_session, data)
    assert batch.reminders_imported == 3
    for reminder in other_session.scalars(select(Reminder)):
        reminder.cal_entity, reminder.cal_uid = "calendar.glovebox", "ev"
    other_session.commit()
    pipeline.undo_batch(other_session, batch.id)
    assert other_session.scalars(select(Reminder)).all() == []
    assert len(reminders.load_removal_notes(other_session)) == 3


def test_with_a_calendar_chosen_imported_open_reminders_are_pending(
    session: Session, other_session: Session
) -> None:
    _populate(session)
    reminder_sync.set_calendar(other_session, "calendar.glovebox")
    other_session.commit()
    _restore(other_session, export_backup(session, Settings()))
    states = {r.title: r.cal_state for r in other_session.scalars(select(Reminder))}
    assert states == {
        "Registration": CalendarState.PENDING, "Oil": CalendarState.NONE,
        "Policy": CalendarState.PENDING,
    }
