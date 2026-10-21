"""Helpers shared by the route modules: page context, redirects, preferences."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from glovebox.db import get_session
from glovebox.models import Vehicle
from glovebox.services import preferences, records
from glovebox.services.stats import StatsFilter
from glovebox.urls import url
from glovebox.web import formatting
from glovebox.web.templating import templates

SessionDep = Annotated[Session, Depends(get_session)]

# Sent by the page script when it wants only the dialog markup of a page.
DIALOG_HEADER = "X-Glovebox-Dialog"


@dataclass(frozen=True)
class Chrome:
    """
    What the app bar and the add/edit forms need to know.

    Attributes
    ----------
    vehicles : list[Vehicle]
        Non-archived vehicles.
    archived : list[Vehicle]
        Archived vehicles (hidden from the app bar and the forms).
    selected : str
        ``"all"`` or the id of the selected vehicle, as text.
    last_vehicle : str
        Id (text) of the last specifically selected vehicle, or ``""``.
    form_vehicle : str
        Default vehicle of the add forms: the selected vehicle, else the last
        specific one, else the only vehicle there is, else ``""``.
    """

    vehicles: list[Vehicle]
    archived: list[Vehicle]
    selected: str
    last_vehicle: str
    form_vehicle: str

    @property
    def selected_ids(self) -> tuple[int, ...]:
        """Vehicle ids the pages show; empty for "All vehicles"."""
        return () if self.selected == preferences.ALL_VEHICLES else (int(self.selected),)


def load_chrome(session: Session) -> Chrome:
    """Resolve the remembered vehicle choices against the existing vehicles."""
    every = records.list_vehicles(session, include_archived=True)
    # Archived vehicles are not offered in the app bar or the forms.
    active = {str(v.id) for v in every if not v.archived}
    known = active

    stored = preferences.get_setting(session, preferences.SELECTED_VEHICLE)
    selected = stored if stored in known else preferences.ALL_VEHICLES
    last = preferences.get_setting(session, preferences.LAST_VEHICLE)
    last = last if last in known else ""

    if selected != preferences.ALL_VEHICLES:
        form_vehicle = selected
    elif last in active:
        form_vehicle = last
    else:
        form_vehicle = next(iter(active)) if len(active) == 1 else ""
    return Chrome(
        vehicles=[v for v in every if not v.archived],
        archived=[v for v in every if v.archived],
        selected=selected,
        last_vehicle=last,
        form_vehicle=form_vehicle,
    )


def remember_vehicle(session: Session, value: str) -> None:
    """Store the app-bar choice; a specific vehicle also becomes the last one."""
    if value == preferences.ALL_VEHICLES:
        preferences.set_setting(session, preferences.SELECTED_VEHICLE, value)
        return
    vehicle = records.get_vehicle(session, int(value))
    preferences.set_setting(session, preferences.SELECTED_VEHICLE, str(vehicle.id))
    preferences.set_setting(session, preferences.LAST_VEHICLE, str(vehicle.id))


def safe_next(target: str) -> str:
    """Accept only in-app paths as a redirect target (no scheme, no host)."""
    ok = target.startswith("/") and not target.startswith("//") and "\\" not in target
    return target if ok else "/"


def current_location(request: Request) -> str:
    """Path and query of this request without the Ingress prefix."""
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def render(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    """
    Render template ``name`` with ``context``.

    Adds ``request``, the app-bar data (``chrome``) and the layout: the full
    page, or just the content block when the page script asks for a dialog.
    """
    context.setdefault("section", "manage")
    context.setdefault(
        "currency", formatting.currency_symbol(request.app.state.settings.currency)
    )
    if "chrome" not in context:
        context["chrome"] = load_chrome(request.state.session)
    context["location"] = current_location(request)
    partial = request.headers.get(DIALOG_HEADER) == "1"
    context["layout"] = "partial.html" if partial else "base.html"
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(request: Request, path: str) -> RedirectResponse:
    """Redirect after a POST (303), keeping the Ingress prefix."""
    return RedirectResponse(url(request, path), status_code=303)


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def parse_date(text: str | None, name: str) -> date | None:
    """Parse ``YYYY-MM-DD`` (blank gives ``None``); 422 for anything else."""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad_request(f"{name}: '{text}' is not a date (YYYY-MM-DD)") from None


def parse_ints(values: list[str], name: str) -> tuple[int, ...]:
    """Parse repeated whole-number query values; blanks are skipped."""
    try:
        return tuple(int(v) for v in values if v != "")
    except ValueError:
        raise _bad_request(f"{name}: expected whole numbers") from None


def view_filter(chrome: Chrome) -> StatsFilter:
    """
    Records of the vehicle selected in the app bar.

    "All vehicles" has no vehicle restriction, so it also covers the history
    of archived vehicles (they are only hidden from the menu and the forms).
    """
    return StatsFilter(vehicles=chrome.selected_ids)
