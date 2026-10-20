"""Shared fixtures: in-memory migrated database, session, app and client."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from glovebox.app import create_app
from glovebox.config import Settings
from glovebox.db import make_engine, make_session_factory, run_migrations

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Directory of anonymised sample files."""
    return FIXTURES_DIR


@pytest.fixture
def engine() -> Iterator[Engine]:
    """In-memory SQLite engine with all migrations applied."""
    engine = make_engine()
    run_migrations(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Database session; changes are rolled back at the end of the test."""
    with make_session_factory(engine)() as session:
        yield session
        session.rollback()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Default standalone settings pointing at a temporary data dir."""
    return Settings(data_dir=tmp_path)


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """Test client for the app (startup runs, sharing the in-memory engine)."""
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client
