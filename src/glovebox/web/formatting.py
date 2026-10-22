"""Pure helpers to show and parse numbers in storage units (cents, milli-units)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

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


def to_scaled_int(value: Decimal | None, scale: int) -> int | None:
    """Multiply by ``scale`` (100 for cents, 1000 for milli) and round half up."""
    if value is None:
        return None
    return int((value * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))
