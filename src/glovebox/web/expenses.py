"""Service and expense pages: entry/edit form (a dialog), delete."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.models import Expense, ExpenseCategory
from glovebox.services import preferences, records
from glovebox.services.records import ExpenseInput, ValidationError
from glovebox.web.common import SessionDep, load_chrome, redirect, render
from glovebox.web.formatting import parse_decimal, to_scaled_int

router = APIRouter(prefix="/expenses")


class ExpenseForm(BaseModel):
    """Raw (string) form fields."""

    vehicle_id: str = ""
    date: str = ""
    category: str = ""
    title: str = ""
    amount: str = ""
    odometer_km: str = ""
    coverage_start: str = ""
    coverage_end: str = ""
    notes: str = ""


def _form_from_expense(expense: Expense) -> dict[str, str]:
    """Fill form fields from a stored expense."""
    return ExpenseForm(
        vehicle_id=str(expense.vehicle_id),
        date=expense.date.isoformat(),
        category=expense.category.value,
        title=expense.title,
        amount=f"{expense.amount_cents / 100:.2f}",
        # An estimated value is not shown as typed; saving it empty re-estimates.
        odometer_km=(
            ""
            if expense.odometer_km is None or expense.odometer_estimated
            else f"{expense.odometer_km:g}"
        ),
        coverage_start=expense.coverage_start.isoformat() if expense.coverage_start else "",
        coverage_end=expense.coverage_end.isoformat() if expense.coverage_end else "",
        notes=expense.notes or "",
    ).model_dump()


def _form_page(request: Request, session: Session, entered: dict[str, str],
               expense_id: int | None = None, status: int = 200,
               errors: list[str] | None = None):
    """Render the service form (category maintenance) or the expense form."""
    chrome = load_chrome(session)
    vehicles = list(chrome.vehicles)
    selected = entered.get("vehicle_id", "")
    if selected and not any(str(v.id) == selected for v in vehicles):
        vehicles.append(records.get_vehicle(session, int(selected)))
    last = None
    if selected:
        try:
            on_day = date.fromisoformat(entered.get("date", ""))
        except ValueError:
            on_day = date.today()
        last = records.last_known_odometer(session, int(selected), on_day, expense_id)
    estimated = None
    if expense_id is not None:
        stored = records.get_expense(session, expense_id)
        if stored.odometer_estimated:
            estimated = stored.odometer_km
    return render(
        request,
        "expenses/form.html",
        status,
        chrome=chrome,
        section="timeline",
        is_service=entered.get("category") == ExpenseCategory.MAINTENANCE.value,
        f=entered,
        expense_id=expense_id,
        vehicles=vehicles,
        categories=[c for c in ExpenseCategory if c is not ExpenseCategory.MAINTENANCE],
        errors=errors or [],
        last_odometer=last,
        odometer_steps=json.dumps({
            str(vid): [[d.isoformat() if d else "", km] for d, km in points]
            for vid, points in records.odometer_steps(
                session, [v.id for v in vehicles], expense_id
            ).items()
        }),
        estimated_km=estimated,
    )


@router.get("/new")
def expense_new(
    request: Request, session: SessionDep, vehicle: str = "", kind: str = "expense"
):
    """
    Empty form. ``?kind=service`` gives the service form (category
    maintenance), anything else the expense form (insurance by default).
    The vehicle defaults to the app-bar choice (``?vehicle=`` wins).
    """
    category = "maintenance" if kind == "service" else "insurance"
    entered = ExpenseForm(
        vehicle_id=vehicle or load_chrome(session).form_vehicle,
        date=date.today().isoformat(),
        category=category,
    ).model_dump()
    return _form_page(request, session, entered)


@router.get("/{expense_id}/edit")
def expense_edit(request: Request, expense_id: int, session: SessionDep):
    """Form filled from a stored expense."""
    expense = records.get_expense(session, expense_id)
    return _form_page(request, session, _form_from_expense(expense), expense_id)


def _optional_date(text: str, name: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name}: enter a valid date") from None


def _parse_form(form: ExpenseForm) -> ExpenseInput:
    """
    Convert raw form text to a service input.

    Raises
    ------
    ValueError
        With a user-presentable message for missing or malformed fields.
    """
    if not form.vehicle_id:
        raise ValueError("Choose a vehicle")
    day = _optional_date(form.date, "Date")
    if day is None:
        raise ValueError("Date is required")
    try:
        category = ExpenseCategory(form.category)
    except ValueError:
        raise ValueError(f"Unknown category '{form.category}'") from None
    amount = to_scaled_int(parse_decimal(form.amount, "Amount"), 100)
    if amount is None:
        raise ValueError("Amount is required")
    odometer = parse_decimal(form.odometer_km, "Odometer")
    return ExpenseInput(
        vehicle_id=int(form.vehicle_id),
        date=day,
        category=category,
        amount_cents=amount,
        title=form.title.strip(),
        odometer_km=None if odometer is None else float(odometer),
        coverage_start=_optional_date(form.coverage_start, "Coverage start"),
        coverage_end=_optional_date(form.coverage_end, "Coverage end"),
        notes=form.notes.strip() or None,
    )


def _save(request: Request, session: Session, form: ExpenseForm, expense_id: int | None):
    """Validate and save; on problems show the form again with messages."""
    try:
        data = _parse_form(form)
        notice = None
        if data.odometer_km is None:
            last = records.last_known_odometer(
                session, data.vehicle_id, data.date, expense_id
            )
            if last is None:
                notice = ("missing", None)
            else:
                data = replace(data, odometer_km=last.km, odometer_estimated=True)
                notice = ("estimated", last.km)
        if expense_id is None:
            records.create_expense(session, data)
        else:
            records.update_expense(session, expense_id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _form_page(request, session, form.model_dump(), expense_id, 422, messages)
    if notice is not None:
        preferences.set_flash(session, *notice)
    return redirect(request, "/")


@router.post("/new")
def expense_create(request: Request, session: SessionDep,
                   form: Annotated[ExpenseForm, Form()]):
    """Create an expense."""
    return _save(request, session, form, None)


@router.post("/{expense_id}/edit")
def expense_update(request: Request, expense_id: int, session: SessionDep,
                   form: Annotated[ExpenseForm, Form()]):
    """Update an expense."""
    return _save(request, session, form, expense_id)


@router.post("/{expense_id}/delete")
def expense_delete(request: Request, expense_id: int, session: SessionDep):
    """Delete an expense."""
    records.delete_expense(session, expense_id)
    return redirect(request, "/")
