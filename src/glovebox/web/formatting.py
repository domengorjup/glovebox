"""Pure helpers to show and parse numbers in storage units (cents, milli-units)."""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

# Numbers and their units must never wrap onto two lines.
NBSP = "\u00a0"

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)  # fmt: skip


CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3"}


def currency_symbol(code: str) -> str:
    """Symbol for the common currency codes, else the code itself (CHF stays CHF)."""
    return CURRENCY_SYMBOLS.get(code, code)


def money(cents: int | None, currency: str) -> str:
    """Return cents as ``"123.45 EUR"`` (non-breaking space), or ``"n/a"``."""
    if cents is None:
        return "n/a"
    return f"{format_cents(cents)}{NBSP}{currency_symbol(currency)}"


def with_unit(text: str, unit: str) -> str:
    """Join a number and its unit with a non-breaking space."""
    return f"{text}{NBSP}{unit}"


def short_date(day: date) -> str:
    """Return ``5 May`` (English month names regardless of the server locale)."""
    return f"{day.day}{NBSP}{MONTH_NAMES[day.month - 1][:3]}"


def full_date(day: date) -> str:
    """Return ``5 May 2026`` (English month names, no line break inside)."""
    return f"{short_date(day)}{NBSP}{day.year}"


def month_label(year: int, month: int) -> str:
    """Return ``May 2026``."""
    return f"{MONTH_NAMES[month - 1]} {year}"


def format_cents(cents: int) -> str:
    """Return ``12345`` as ``"123.45"``."""
    return f"{Decimal(cents) / 100:.2f}"


def format_milli(milli: int, places: int = 2) -> str:
    """Return thousandths as a decimal string with ``places`` decimals."""
    return f"{Decimal(milli) / 1000:.{places}f}"


def format_km(value: float, grouped: bool = False) -> str:
    """Return an odometer or distance value without a needless ``.0``.

    ``grouped`` adds a comma between thousands (``104,163``), for sentences.
    """
    comma = "," if grouped else ""
    return f"{value:{comma}.0f}" if float(value).is_integer() else f"{value:{comma}.1f}"


def format_consumption(value: float | None) -> str:
    """Return L/100 km with two decimals, or ``"n/a"``."""
    return "n/a" if value is None else f"{value:.2f}"


def parse_decimal(text: str | None, field_name: str) -> Decimal | None:
    """
    Parse a user-typed decimal; blank gives ``None``, comma is accepted.

    Raises
    ------
    ValueError
        With a user-presentable message if the text is not a number.
    """
    cleaned = (text or "").strip().replace(",", ".")
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{field_name}: '{text}' is not a number") from None
    if not value.is_finite():
        raise ValueError(f"{field_name}: '{text}' is not a number")
    return value


_NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+")
_MAX_EXPRESSION_LENGTH = 200  # also keeps the recursion shallow
MALFORMED = "Not a valid calculation."
DIVIDE_BY_ZERO = "Can't divide by zero."


class _Calculator:
    """Recursive-descent evaluator for ``+ - * /``, unary minus and parentheses."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def evaluate(self) -> Fraction:
        """Return the exact value of the whole text."""
        value = self._sum()
        if self._pos != len(self._text):
            raise ValueError(MALFORMED)
        return value

    def _peek(self) -> str:
        return self._text[self._pos : self._pos + 1]

    def _sum(self) -> Fraction:
        value = self._product()
        while self._peek() in ("+", "-"):
            sign = self._text[self._pos]
            self._pos += 1
            term = self._product()
            value = value + term if sign == "+" else value - term
        return value

    def _product(self) -> Fraction:
        value = self._unary()
        while self._peek() in ("*", "/"):
            sign = self._text[self._pos]
            self._pos += 1
            factor = self._unary()
            if sign == "*":
                value *= factor
            elif factor == 0:
                raise ValueError(DIVIDE_BY_ZERO)
            else:
                value /= factor
        return value

    def _unary(self) -> Fraction:
        if self._peek() == "-":
            self._pos += 1
            return -self._unary()
        return self._atom()

    def _atom(self) -> Fraction:
        if self._peek() == "(":
            self._pos += 1
            value = self._sum()
            if self._peek() != ")":
                raise ValueError(MALFORMED)
            self._pos += 1
            return value
        match = _NUMBER.match(self._text, self._pos)
        if match is None:
            raise ValueError(MALFORMED)
        self._pos = match.end()
        return Fraction(match.group().replace(",", "."))


def evaluate_expression(text: str) -> Fraction:
    """
    Evaluate ``12.50+3*(2-1)`` exactly.

    Numbers with a decimal comma or point, ``+ - * /``, unary minus,
    parentheses; an optional leading ``=`` and spaces are ignored; at most 200
    characters. No ``eval``.

    Raises
    ------
    ValueError
        ``"Not a valid calculation."`` or ``"Can't divide by zero."``.
    """
    body = text.strip()
    if body.startswith("="):
        body = body[1:]
    body = "".join(body.split())
    if not body or len(body) > _MAX_EXPRESSION_LENGTH:
        raise ValueError(MALFORMED)
    return _Calculator(body).evaluate()


def parse_money(text: str | None, field_name: str) -> Decimal | None:
    """
    Like :func:`parse_decimal`, but also accepts a calculation such as ``=12.50+3``.

    A plain number is read exactly as :func:`parse_decimal` reads it. A
    calculation is evaluated exactly; the caller rounds it like a typed value.
    """
    try:
        return parse_decimal(text, field_name)
    except ValueError:
        pass
    try:
        value = evaluate_expression(text or "")
    except ValueError as error:
        raise ValueError(f"{field_name}: {error}") from None
    return Decimal(value.numerator) / Decimal(value.denominator)


def to_scaled_int(value: Decimal | None, scale: int) -> int | None:
    """Multiply by ``scale`` (100 for cents, 1000 for milli) and round half up."""
    if value is None:
        return None
    return int((value * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))
