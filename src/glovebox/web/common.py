"""Helpers shared by the route modules: sessions, redirects, filters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from glovebox.db import get_session
from glovebox.models import ExpenseCategory
from glovebox.services import records
from glovebox.services.stats import Allocation, StatsFilter
from glovebox.urls import url
from glovebox.web.templating import templates

SessionDep = Annotated[Session, Depends(get_session)]


def render(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    """Render template ``name`` with ``context`` (``request`` is added)."""
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(request: Request, path: str) -> RedirectResponse:
    """Redirect after a POST (303), keeping the Ingress prefix."""
    return RedirectResponse(url(request, path), status_code=303)


@dataclass(frozen=True)
class ViewFilters:
    """
    Filters and view settings read from the URL query.

    ``stats`` holds exactly what the user chose; use ``effective_filter`` to
    apply the default "hide archived vehicles".
    """

    stats: StatsFilter
    allocation: Allocation


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _parse_date(text: str | None, name: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad_request(f"{name}: '{text}' is not a date (YYYY-MM-DD)") from None


def parse_ints(values: list[str], name: str) -> tuple[int, ...]:
    try:
        return tuple(int(v) for v in values if v != "")
    except ValueError:
        raise _bad_request(f"{name}: expected whole numbers") from None


def parse_filters(request: Request) -> ViewFilters:
    """
    Read the common filters from the query string.

    Parameters are ``vehicle`` / ``station`` / ``category`` / ``brand``
    (repeatable), ``date_from``, ``date_to`` and ``allocation``. Empty values
    (as sent by an unfilled GET form) mean "no restriction".

    Raises
    ------
    HTTPException
        422 for an invalid date, number, category or allocation.
    """
    query = request.query_params
    try:
        categories = tuple(ExpenseCategory(c) for c in query.getlist("category") if c)
        allocation = Allocation(query.get("allocation") or Allocation.SPREAD)
    except ValueError as exc:
        raise _bad_request(str(exc)) from None
    flt = StatsFilter(
        vehicles=parse_ints(query.getlist("vehicle"), "vehicle"),
        date_from=_parse_date(query.get("date_from"), "date_from"),
        date_to=_parse_date(query.get("date_to"), "date_to"),
        categories=categories,
        stations=parse_ints(query.getlist("station"), "station"),
        brands=tuple(b for b in query.getlist("brand") if b),
    )
    return ViewFilters(stats=flt, allocation=allocation)


def effective_filter(session: Session, flt: StatsFilter) -> StatsFilter:
    """Without an explicit vehicle, restrict to non-archived vehicles."""
    if flt.vehicles:
        return flt
    active = tuple(v.id for v in records.list_vehicles(session))
    return replace(flt, vehicles=active)


def filter_choices(session: Session) -> dict[str, Any]:
    """Options for the filter form: all vehicles, stations and brands."""
    stations = records.list_stations(session)
    return {
        "all_vehicles": records.list_vehicles(session, include_archived=True),
        "all_stations": stations,
        "all_brands": sorted({s.brand for s in stations if s.brand}),
        "all_categories": list(ExpenseCategory),
    }
