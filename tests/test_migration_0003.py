"""Migration 0003: preset table and widened columns."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from glovebox.db import MIGRATIONS_DIR, make_engine, run_migrations


def _config(connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


def test_upgrade_creates_table_and_widens_columns() -> None:
    engine = make_engine()
    run_migrations(engine)
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("preset")} == {
        "id", "slug", "name", "body", "locked", "created_at", "updated_at",
    }
    for table, column in (("import_batch", "format"), ("refuel", "source"),
                          ("expense", "source")):
        length = {c["name"]: getattr(c["type"], "length", None) for c in inspector.get_columns(table)}
        assert length[column] == 50
    engine.dispose()


def test_downgrade_truncates_and_drops() -> None:
    engine = make_engine()
    run_migrations(engine)
    long_id = "user-" + "x" * 40
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO import_batch (format, filename, created_at, refuels_imported,"
            " expenses_imported, duplicates_skipped) VALUES (:f, 'a.csv', '2026-01-01', 0, 0, 0)"
        ), {"f": long_id})
        command.downgrade(_config(connection), "0002")
    inspector = inspect(engine)
    assert "preset" not in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT format FROM import_batch")) == long_id[:20]
    assert {c["name"]: getattr(c["type"], "length", None) for c in inspector.get_columns("import_batch")}["format"] == 20
    engine.dispose()
