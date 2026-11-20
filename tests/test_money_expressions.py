"""Cost fields accept sums such as =12.50+3 (parser and real forms)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from glovebox.models import Expense, Refuel
from glovebox.web.formatting import evaluate_expression, parse_money, to_scaled_int


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.50+3", "15.50"),
        ("=12,50+3", "15.50"),
        ("2+3*4", "14"),
        ("10-4/2", "8"),
        ("  = 1 + 2 * 3 - 4 ", "3"),
        ("-5+2", "-3"),
        ("1+-2", "-1"),
        ("=(1+2)*3", "9"),
        ("-(2+3)", "-5"),
        ("1,299*0,75", "0.97425"),
        ("10/4", "2.5"),
        ("=7", "7"),
    ],
)
def test_expression_values(text: str, expected: str) -> None:
    assert parse_money(text, "Total") == Decimal(expected)


def test_plain_number_unchanged() -> None:
    assert parse_money("12,5", "Total") == Decimal("12.5")
    assert parse_money(" ", "Total") is None
    assert parse_money(None, "Total") is None


@pytest.mark.parametrize("text", ["=", "1+", "*2", "2**3", "(1+2", "1+2)", "abc", "1+a", "=1e3+1", "()", "+" * 201])
def test_bad_expressions(text: str) -> None:
    with pytest.raises(ValueError, match="^Total: Not a valid calculation\\.$"):
        parse_money(text, "Total")


@pytest.mark.parametrize("text", ["1/0", "=5/(2-2)"])
def test_division_by_zero(text: str) -> None:
    with pytest.raises(ValueError, match="^Total: Can't divide by zero\\.$"):
        parse_money(text, "Total")


def test_calculation_rounds_half_up_to_cents() -> None:
    assert to_scaled_int(parse_money("1,299*0,75", "Total"), 100) == 97
    assert to_scaled_int(parse_money("=0.005*1", "Total"), 100) == 1


def test_evaluate_rejects_empty() -> None:
    with pytest.raises(ValueError):
        evaluate_expression("")


def _vehicle(client: TestClient) -> str:
    client.post("/vehicles/new", data={"name": "Golf"}, follow_redirects=False)
    return str(client.get("/api/v1/vehicles").json()[0]["id"])


def test_refuel_total_as_expression(client: TestClient, engine: Engine) -> None:
    vid = _vehicle(client)
    response = client.post(
        "/refuels/new",
        data={"vehicle_id": vid, "date": date.today().isoformat(), "odometer_km": "1000",
              "litres": "40", "total": "=30.5+30.5*2", "is_full": "1"},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code == 303
    with Session(engine) as session:
        refuel = session.scalars(select(Refuel)).one()
    assert refuel.total_cents == 9150
    assert refuel.price_per_litre_milli == 2288  # 91.50 / 40, rounded to thousandths


def test_price_as_expression_on_quick_page(client: TestClient, engine: Engine) -> None:
    vid = _vehicle(client)
    response = client.post(
        "/quick",
        data={"vehicle_id": vid, "date": date.today().isoformat(), "odometer_km": "1500",
              "litres": "40", "price_per_litre": "1,5+0.05", "is_full": "1",
              "station_choice": "other", "station_id": ""},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code == 303
    with Session(engine) as session:
        refuel = session.scalars(select(Refuel)).one()
    assert refuel.price_per_litre_milli == 1550
    assert refuel.total_cents == 6200


def test_expense_amount_as_expression(client: TestClient, engine: Engine) -> None:
    vid = _vehicle(client)
    response = client.post(
        "/expenses/new",
        data={"vehicle_id": vid, "date": date.today().isoformat(), "category": "maintenance",
              "title": "Service", "amount": "=(100+20)*2 + 45,50 - 10"},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code == 303
    with Session(engine) as session:
        assert session.scalars(select(Expense)).one().amount_cents == 27550


def test_bad_expression_shows_field_error(client: TestClient, engine: Engine) -> None:
    vid = _vehicle(client)
    response = client.post(
        "/expenses/new",
        data={"vehicle_id": vid, "date": date.today().isoformat(), "category": "maintenance",
              "title": "Service", "amount": "=5/0"},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code != 303
    assert "Amount: Can&#39;t divide by zero." in response.text
    with Session(engine) as session:
        assert session.scalars(select(Expense)).first() is None
