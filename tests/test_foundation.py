"""Tests of the foundation: config, database, migrations, URL helper."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from glovebox.config import Mode, load_settings
from glovebox.db import make_engine, run_migrations
from glovebox.models import Base, Expense, ExpenseCategory, Vehicle
from glovebox.services import records, stats


def test_settings_defaults(tmp_path: Path) -> None:
    s = load_settings({}, tmp_path / "none.json")
    assert s.mode is Mode.STANDALONE
    assert s.currency == "EUR"
    assert s.base_path == ""
    assert s.password is None


def test_settings_env_overrides_options(tmp_path: Path) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"currency": "CHF", "password": "x"}))
    env = {"GLOVEBOX_MODE": "addon", "CURRENCY": "USD", "BASE_PATH": "foo/"}
    s = load_settings(env, options)
    assert (s.mode, s.currency, s.password) == (Mode.ADDON, "USD", "x")
    assert s.base_path == "/foo"
    assert s.data_dir == Path("/data")


def test_settings_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        load_settings({"GLOVEBOX_MODE": "bogus"})


def test_migrations_match_models(engine) -> None:
    assert set(inspect(engine).get_table_names()) >= set(Base.metadata.tables)


def test_file_database_uses_wal(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    run_migrations(engine)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    engine.dispose()


def test_active_vehicle_name_unique_archived_allowed(session: Session) -> None:
    session.add(Vehicle(name="Golf", archived=True))
    session.add(Vehicle(name="Golf"))
    session.flush()
    session.add(Vehicle(name="Golf"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_vehicle_cascades_to_expenses(session: Session) -> None:
    vehicle = Vehicle(name="Golf")
    session.add(vehicle)
    session.flush()
    session.add(
        Expense(
            vehicle_id=vehicle.id,
            date=date(2026, 1, 1),
            category=ExpenseCategory.INSURANCE,
            amount_cents=36500,
        )
    )
    session.flush()
    session.delete(vehicle)
    session.flush()
    assert session.execute(text("SELECT count(*) FROM expense")).scalar() == 0


def test_index_renders_with_root_urls(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/"' in response.text


def test_index_honours_ingress_header(client: TestClient) -> None:
    response = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert 'href="/api/hassio_ingress/abc/"' in response.text


def test_unsafe_ingress_header_ignored(client: TestClient) -> None:
    response = client.get("/", headers={"X-Ingress-Path": '/"><script>'})
    assert "<script>" not in response.text
    assert 'href="/"' in response.text


def test_settings_table_exists_after_migration(engine) -> None:
    from sqlalchemy import inspect

    inspector = inspect(engine)
    assert "setting" in inspector.get_table_names()
    columns = {c["name"]: c for c in inspector.get_columns("setting")}
    assert set(columns) == {"key", "value"}
    assert inspector.get_pk_constraint("setting")["constrained_columns"] == ["key"]


def test_sigterm_ends_the_server_with_status_0(tmp_path: Path) -> None:
    """The Supervisor stops the add-on with SIGTERM; a clean stop is not a failure."""
    import os
    import signal
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, DATA_DIR=str(tmp_path), GLOVEBOX_HOST="127.0.0.1",
               GLOVEBOX_PORT=str(port), GLOVEBOX_MODE="standalone")
    proc = subprocess.Popen(
        [sys.executable, "-c", "from glovebox.app import main; main()"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                assert proc.poll() is None and time.monotonic() < deadline
                time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
