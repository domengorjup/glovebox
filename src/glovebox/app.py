"""FastAPI application factory and command-line entry point."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from glovebox import __version__
from glovebox.api import v1
from glovebox.auth import install_api_auth, install_auth
from glovebox.config import Mode, Settings, load_settings
from glovebox.db import make_engine, make_session_factory, run_migrations
from glovebox.services.reminder_sync import ReminderSync, client_for
from glovebox.web import router as web_router
from glovebox.web.templating import STATIC_DIR

logger = logging.getLogger(__name__)


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
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(engine)
        sync: ReminderSync = app.state.reminder_sync
        retry = asyncio.create_task(sync.retry_forever()) if sync.available else None
        try:
            yield
        finally:
            if retry is not None:
                retry.cancel()

    app = FastAPI(title="Glovebox", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.reminder_sync = ReminderSync(
        app.state.session_factory, client_for(settings)
    )
    install_auth(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web_router)
    app.include_router(v1.router)
    return app


def create_api_app(main_app: FastAPI) -> FastAPI:
    """
    Build the add-on API listener app (design D9a).

    It serves only ``/api/v1`` and requires the Bearer token. It shares the
    settings, engine and session factory of ``main_app``; migrations are run
    by ``main_app``'s startup, not here.
    """
    app = FastAPI(
        title="Glovebox API", version=__version__,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    for name in ("settings", "engine", "session_factory"):
        setattr(app.state, name, getattr(main_app.state, name))
    install_api_auth(app)
    app.include_router(v1.router)
    return app


def api_listener_enabled(settings: Settings) -> bool:
    """Return True if the add-on API listener should start; warn if not."""
    if settings.mode is not Mode.ADDON or settings.api_port is None:
        return False
    if settings.api_token:
        return True
    logger.warning(
        "API listener on port %d not started: no api_token is set. To use the "
        "stats API outside Ingress, set api_token (16+ characters) in the "
        "add-on options and map the port in the add-on network settings.",
        settings.api_port,
    )
    return False


class _SecondaryServer(uvicorn.Server):
    """Server that leaves signal handling to the main server."""

    # uvicorn >= 0.29 installs handlers in ``capture_signals``; the main
    # server's handler stops this server too (see ``_serve``).
    @contextmanager
    def capture_signals(self) -> Iterator[None]:  # noqa: D102
        yield


async def _serve(settings: Settings) -> None:
    """Run the main listener, plus the API listener when enabled."""
    app = create_app(settings)
    main_server = uvicorn.Server(
        uvicorn.Config(app, host=settings.host, port=settings.port)
    )
    if not api_listener_enabled(settings):
        await main_server.serve()
        return
    api_server = _SecondaryServer(
        uvicorn.Config(create_api_app(app), host=settings.host, port=settings.api_port)
    )
    task = asyncio.create_task(api_server.serve())
    try:
        await main_server.serve()
    finally:
        api_server.should_exit = True
        await task


def main() -> None:
    """
    Run the app with uvicorn on ``Settings.host`` / ``Settings.port``.

    In add-on mode with an ``api_token`` it also serves ``/api/v1`` on
    ``Settings.api_port``. Invalid settings end the process with a message.
    """
    try:
        settings = load_settings()
    except ValueError as exc:
        raise SystemExit(f"glovebox: {exc}") from exc
    signal.signal(signal.SIGTERM, _exit_after_shutdown)
    asyncio.run(_serve(settings))


def _exit_after_shutdown(_signum: int, _frame: object) -> None:
    """
    End with status 0 on SIGTERM.

    uvicorn shuts down gracefully and then raises the signal again; with the
    default handler the process would die by the signal (status 143), and the
    Supervisor would show a stopped add-on as failed.
    """
    raise SystemExit(0)
