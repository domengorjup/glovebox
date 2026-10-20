"""FastAPI application factory and command-line entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from autotracker import __version__
from autotracker.api import v1
from autotracker.config import Settings, load_settings
from autotracker.db import make_engine, make_session_factory, run_migrations
from autotracker.web import router as web_router
from autotracker.web.templating import STATIC_DIR


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """
    Build the application.

    Parameters
    ----------
    settings : Settings | None, optional
        Default is ``load_settings()``.
    engine : Engine | None, optional
        Default is a file database under ``settings.data_dir``. Tests pass an
        in-memory engine. Migrations run to ``head`` at startup either way.

    Returns
    -------
    FastAPI
        App with ``state.settings``, ``state.engine`` and
        ``state.session_factory`` set.
    """
    settings = settings or load_settings()
    engine = engine or make_engine(settings.data_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(engine)
        yield

    app = FastAPI(title="Autotracker", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web_router)
    app.include_router(v1.router)
    return app


def main() -> None:
    """Run the app with uvicorn on ``Settings.host`` / ``Settings.port``."""
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
