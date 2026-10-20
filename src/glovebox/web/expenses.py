"""Expense pages: filtered list with total, entry/edit form, delete."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from glovebox.models import Expense, ExpenseCategory
from glovebox.services import records
from glovebox.services.records import ExpenseInput, ValidationError
from glovebox.web.common import (
    SessionDep,
    effective_filter,
    filter_choices,
    parse_filters,
    redirect,
    render,
)
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


@router.get("")
def expense_list(request: Request, session: SessionDep):
    """Expenses newest first, with the total of the filtered rows."""
    view = parse_filters(request)
    rows = records.list_expenses(session, effective_filter(session, view.stats))
    choices = filter_choices(session)
    return render(
        request,
        "expenses/list.html",
        rows=rows,
        total_cents=sum(r.amount_cents for r in rows),
        vehicle_names={v.id: v.name for v in choices["all_vehicles"]},
        f=view.stats,
        choices=choices,
    )


def _form_from_expense(expense: Expense) -> dict[str, str]:
    """Fill form fields from a stored expense."""
    return ExpenseForm(
        vehicle_id=str(expense.vehicle_id),
        date=expense.date.isoformat(),
        category=expense.category.value,
        title=expense.title,
        amount=f"{expense.amount_cents / 100:.2f}",
        odometer_km=(
            "" if expense.odometer_km is None else f"{expense.odometer_km:g}"
        ),
        coverage_start=expense.coverage_start.isoformat() if expense.coverage_start else "",
        coverage_end=expense.coverage_end.isoformat() if expense.coverage_end else "",
        notes=expense.notes or "",
    ).model_dump()


def _form_page(request: Request, session: Session, entered: dict[str, str],
               expense_id: int | None = None, status: int = 200,
               errors: list[str] | None = None):
    """Render the expense form."""
    vehicles = records.list_vehicles(session)
    selected = entered.get("vehicle_id", "")
    if selected and not any(str(v.id) == selected for v in vehicles):
        vehicles.append(records.get_vehicle(session, int(selected)))
    return render(
        request,
        "expenses/form.html",
        status,
        f=entered,
        expense_id=expense_id,
        vehicles=vehicles,
        categories=list(ExpenseCategory),
        errors=errors or [],
    )


@router.get("/new")
def expense_new(request: Request, session: SessionDep, vehicle: str = ""):
    """Empty form; ``?vehicle=`` preselects a vehicle."""
    entered = ExpenseForm(
        vehicle_id=vehicle, date=date.today().isoformat(), category="maintenance"
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
        if expense_id is None:
            records.create_expense(session, data)
        else:
            records.update_expense(session, expense_id, data)
    except (ValueError, ValidationError) as exc:
        session.rollback()
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _form_page(request, session, form.model_dump(), expense_id, 422, messages)
    return redirect(request, "/expenses")


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
    return redirect(request, "/expenses")
