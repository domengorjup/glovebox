"""Pure helpers to show and parse numbers in storage units (cents, milli-units)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def format_cents(cents: int) -> str:
    """Return ``12345`` as ``"123.45"``."""
    return f"{Decimal(cents) / 100:.2f}"


def format_milli(milli: int, places: int = 2) -> str:
    """Return thousandths as a decimal string with ``places`` decimals."""
    return f"{Decimal(milli) / 1000:.{places}f}"


def format_km(value: float) -> str:
    """Return an odometer or distance value without a needless ``.0``."""
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


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
