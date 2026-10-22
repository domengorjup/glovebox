"""Periods for the Timeline summary cards (pure date maths, no database)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MONTH = "month"
DAYS_30 = "30d"
YEAR = "year"
MONTHS_12 = "12m"
ALL_TIME = "all"
CUSTOM = "custom"

# Display order; also the set of valid period names.
PERIODS = (
    (MONTH, "This month"),
    (DAYS_30, "Last 30 days"),
    (YEAR, "This year"),
    (MONTHS_12, "Last 12 months"),
    (ALL_TIME, "All time"),
    (CUSTOM, "Custom range"),
)
PERIOD_KEYS = tuple(key for key, _ in PERIODS)
DEFAULT_PERIOD = MONTHS_12

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)


@dataclass(frozen=True)
class Period:
    """
    A resolved summary period.

    Attributes
    ----------
    key : str
        One of ``PERIOD_KEYS``.
    start, end : date
        Inclusive range the cards cover.
    previous : tuple[date, date] | None
        Inclusive range the cost is compared with; ``None`` for "All time".
    previous_text : str
        How the comparison is named in the hint, e.g. ``"September"``.
    """

    key: str
    start: date
    end: date
    previous: tuple[date, date] | None
    previous_text: str = ""


def years_before(day: date) -> date:
    """Same day one year earlier (29 February becomes 28 February)."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _preceding(start: date, end: date) -> tuple[date, date]:
    """The range of equal length that ends the day before ``start``."""
    days = (end - start).days + 1
    last = start - timedelta(days=1)
    return last - timedelta(days=days - 1), last


def resolve(
    key: str,
    today: date,
    first_record: date | None = None,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> Period:
    """
    Turn a period name into dates, with the range its cost is compared with.

    "This month" and "This year" run from their first day to ``today`` and are
    compared with the same days of the previous month or year (clamped at the
    end of a shorter month). The other periods are compared with the range of
    equal length just before them.

    Parameters
    ----------
    key : str
        One of ``PERIOD_KEYS``; anything else is treated as "Last 12 months".
    today : date
        The current day.
    first_record : date | None
        Date of the earliest record, the start of "All time".
    custom_from, custom_to : date | None
        Bounds of "Custom range" (swapped if reversed). Without both,
        the range falls back to the last 30 days.
    """
    if key == MONTH:
        start = today.replace(day=1)
        last_month = start - timedelta(days=1)
        stop = min(today.day, last_month.day)
        previous = (last_month.replace(day=1), last_month.replace(day=stop))
        return Period(key, start, today, previous, _MONTH_NAMES[last_month.month - 1])
    if key == YEAR:
        start = date(today.year, 1, 1)
        previous = (date(today.year - 1, 1, 1), years_before(today))
        return Period(key, start, today, previous, f"same days in {today.year - 1}")
    if key == ALL_TIME:
        return Period(key, first_record or today, today, None)
    if key == CUSTOM and custom_from and custom_to:
        start, end = sorted((custom_from, custom_to))
        days = (end - start).days + 1
        return Period(key, start, end, _preceding(start, end), f"previous {days} days")
    if key == DAYS_30 or key == CUSTOM:
        # A custom range without dates falls back to the last 30 days.
        start = today - timedelta(days=29)
        return Period(DAYS_30, start, today, _preceding(start, today), "previous 30 days")
    start = years_before(today) + timedelta(days=1)
    return Period(MONTHS_12, start, today, _preceding(start, today), "previous 12 months")
