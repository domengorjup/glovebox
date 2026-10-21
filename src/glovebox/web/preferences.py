"""Routes that store UI preferences: app-bar vehicle and Timeline summary cards."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request

from glovebox.services import preferences, records
from glovebox.web.common import SessionDep, redirect, remember_vehicle, safe_next

router = APIRouter(prefix="/preferences")


@router.post("/vehicle")
def select_vehicle(
    request: Request,
    session: SessionDep,
    vehicle: Annotated[str, Form()] = preferences.ALL_VEHICLES,
    next: Annotated[str, Form()] = "/",
):
    """Remember the vehicle chosen in the app bar, then return to the page."""
    if vehicle != preferences.ALL_VEHICLES and not vehicle.isdigit():
        raise HTTPException(422, detail="vehicle: expected a vehicle id or 'all'")
    try:
        remember_vehicle(session, vehicle)
    except records.NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    return redirect(request, safe_next(next))


@router.post("/cards")
def set_cards(
    request: Request,
    session: SessionDep,
    card: Annotated[list[str] | None, Form()] = None,
    offered: Annotated[list[str] | None, Form()] = None,
    summary: Annotated[list[str] | None, Form()] = None,
    next: Annotated[str, Form()] = "/",
):
    """
    Store which summary cards the Timeline shows (unknown names are dropped).

    When the form also listed summary groups (``offered``, "All vehicles"
    only), the unticked ones are stored as hidden.
    """
    preferences.set_summary_cards(session, card or [])
    if offered:
        preferences.update_hidden_summaries(session, offered, summary or [])
    return redirect(request, safe_next(next))
