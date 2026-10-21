"""SQLite engine, session factory and migration runner."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DB_FILENAME = "glovebox.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def make_engine(data_dir: Path | None = None) -> Engine:
    """
    Create the SQLite engine.

    Parameters
    ----------
    data_dir : Path | None, optional
        Directory for ``glovebox.db`` (created if missing). ``None`` gives
        a private in-memory database, used by tests.

    Returns
    -------
    Engine
        Engine with WAL mode (file databases) and foreign keys enabled.
    """
    if data_dir is None:
        # One shared connection, otherwise every connection sees its own empty DB.
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{data_dir / DB_FILENAME}")
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
    """Enable foreign keys and WAL on every new connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # no-op for in-memory databases
    cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine`` (no expire-on-commit)."""
    return sessionmaker(engine, expire_on_commit=False)


def run_migrations(engine: Engine) -> None:
    """Apply all Alembic migrations (``upgrade head``) to ``engine``."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def get_session(request: Request) -> Iterator[Session]:
    """
    FastAPI dependency yielding a session; commits on success.

    Rolls back and re-raises on any exception.
    """
    with request.app.state.session_factory() as session:
        # Pages read UI preferences and vehicles through this same session.
        request.state.session = session
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
