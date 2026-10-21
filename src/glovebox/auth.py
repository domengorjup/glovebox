"""
Access control (design D9).

Add-on mode: no login; only the Supervisor ingress proxy may connect.
Standalone mode: optional single-password login with a signed session cookie,
and an optional Bearer token for ``/api/v1``.

Sources for the add-on rule (checked 2026-10-20), HA developer docs, "Ingress"
(https://contributors.home-assistant.io/apps/guides/ingress/, formerly
developers.home-assistant.io/docs/add-ons/presentation/): "Your web server only
ever sees requests from the Supervisor, at `172.30.32.2`." and "Only accept
connections from `172.30.32.2`. Deny everything else." The Supervisor adds
`X-Ingress-Path` to every request.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from html import escape

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from glovebox.config import Mode, Settings
from glovebox.urls import url

logger = logging.getLogger(__name__)

INGRESS_PROXY_ADDRESS = "172.30.32.2"
SESSION_COOKIE = "glovebox_session"
SESSION_MAX_AGE = 30 * 24 * 3600
_SALT = "glovebox-session"
_PUBLIC_PREFIXES = ("/static/", "/login", "/logout")

router = APIRouter()


def session_secret(settings: Settings) -> str:
    """
    Return the key that signs session cookies.

    ``GLOVEBOX_SECRET`` is used when set. Otherwise a key is derived from
    the password, so sessions survive restarts and a password change logs
    everyone out. Without both, there are no sessions to sign.

    Raises
    ------
    ValueError
        If neither a secret nor a password is configured.
    """
    if settings.secret:
        return settings.secret
    if settings.password:
        return hashlib.sha256(f"{_SALT}:{settings.password}".encode()).hexdigest()
    raise ValueError("A session secret or password is required")


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(settings), salt=_SALT)


def has_valid_session(request: Request) -> bool:
    """Return True if the request carries a valid, unexpired session cookie."""
    settings: Settings = request.app.state.settings
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie or not settings.password:
        return False
    try:
        _serializer(settings).loads(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return False
    return True


def has_valid_token(request: Request) -> bool:
    """Return True if ``Authorization: Bearer`` matches the configured token."""
    token = request.app.state.settings.api_token
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if not token or scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.strip().encode(), token.encode())


def _is_api(path: str) -> bool:
    return path == "/api/v1" or path.startswith("/api/v1/")


def _is_public(path: str) -> bool:
    return path.startswith(_PUBLIC_PREFIXES)


def _check_standalone(request: Request) -> Response | None:
    """Return a denial response for an unauthenticated request, else None."""
    settings: Settings = request.app.state.settings
    path = request.url.path
    if _is_api(path):
        # The API is locked when either credential type is configured.
        if not (settings.api_token or settings.password):
            return None
        if has_valid_token(request) or has_valid_session(request):
            return None
        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not settings.password or _is_public(path) or has_valid_session(request):
        return None
    return RedirectResponse(url(request, "/login"), status_code=303)


def _check_addon(request: Request) -> Response | None:
    """Return 403 unless the request comes from the ingress proxy."""
    client = request.client.host if request.client else None
    if client == INGRESS_PROXY_ADDRESS:
        return None
    return JSONResponse({"detail": "Forbidden"}, status_code=403)


def install_api_auth(app: FastAPI) -> None:
    """
    Install the middleware of the add-on API listener on ``app``.

    Non-API paths get 404 before any token check, so nothing is revealed to
    callers without the token. API paths need a valid Bearer token (401).
    """

    @app.middleware("http")
    async def api_only(request: Request, call_next):  # noqa: ANN001, ANN202
        if not _is_api(request.url.path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if not has_valid_token(request):
            return JSONResponse(
                {"detail": "Not authenticated"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def install_auth(app: FastAPI) -> None:
    """
    Install the access-control middleware and login routes on ``app``.

    Reads ``app.state.settings``, so call it after the settings are set.
    Logs a warning in standalone mode when no password is configured.
    """
    settings: Settings = app.state.settings
    if settings.mode is Mode.STANDALONE:
        app.include_router(router)
        if not settings.password:
            logger.warning(
                "No GLOVEBOX_PASSWORD set: the app is open to anyone who can "
                "reach it. Put it behind a reverse proxy or set a password."
            )

    @app.middleware("http")
    async def access_control(request: Request, call_next):  # noqa: ANN001, ANN202
        check = _check_addon if settings.mode is Mode.ADDON else _check_standalone
        denied = check(request)
        return denied if denied is not None else await call_next(request)


def _login_page(request: Request, error: str = "", status_code: int = 200) -> HTMLResponse:
    css = escape(url(request, "/static/app.css"))
    theme = escape(url(request, "/static/theme.js"))
    action = escape(url(request, "/login"))
    message = f"<p class='alert error' role='alert'>{escape(error)}</p>" if error else ""
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Glovebox login</title><script src='{theme}'></script>"
        f"<link rel='stylesheet' href='{css}'></head><body>"
        "<main class='login'><h1>Glovebox</h1>"
        f"<form class='card card-pad stack' method='post' action='{action}'>{message}"
        "<div class='field'><label for='i-password'>Password</label>"
        "<input id='i-password' type='password' name='password' required autofocus></div>"
        "<div><button type='submit' class='btn primary'>Log in</button></div>"
        "</form></main></body></html>"
    )
    return HTMLResponse(html, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    """Show the login page (redirect home when no password is configured)."""
    if not request.app.state.settings.password:
        return RedirectResponse(url(request, "/"), status_code=303)
    return _login_page(request)


@router.post("/login")
def login(request: Request, password: str = Form("")) -> Response:
    """Check the password; on success set the signed session cookie."""
    settings: Settings = request.app.state.settings
    if not settings.password:
        return RedirectResponse(url(request, "/"), status_code=303)
    if not hmac.compare_digest(password.encode(), settings.password.encode()):
        return _login_page(request, "Wrong password.", status_code=401)
    response = RedirectResponse(url(request, "/"), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        _serializer(settings).dumps({"ok": True}),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    """Clear the session cookie."""
    response = RedirectResponse(url(request, "/login"), status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
