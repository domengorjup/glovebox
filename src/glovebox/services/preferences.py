"""UI preferences kept in the ``setting`` table, shared by all devices."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from glovebox.models import Setting
from glovebox.services import periods

SELECTED_VEHICLE = "selected_vehicle"
LAST_VEHICLE = "last_vehicle"
SUMMARY_CARDS = "summary_cards"
HIDDEN_SUMMARIES = "hidden_summaries"
PERIOD_PREFIX = "summary_period:"
COMBINED = "combined"

FLASH = "flash"

ALL_VEHICLES = "all"

# Display order of the Timeline summary cards; also the set of valid names.
CARD_KEYS = (
    "cost_month",
    "consumption",
    "last_refuel",
    "cost_km",
    "avg_price",
    "odometer",
)
DEFAULT_CARDS = ("cost_month", "consumption", "last_refuel", "cost_km")


def get_setting(session: Session, key: str) -> str | None:
    """Return the stored text for ``key``, or ``None`` if never set."""
    row = session.get(Setting, key)
    return None if row is None else row.value


def set_setting(session: Session, key: str, value: str) -> None:
    """Store ``value`` under ``key`` (insert or overwrite)."""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def set_flash(session: Session, kind: str, km: float | None = None, **extra) -> None:
    """Remember a one-time notice for the next Timeline page."""
    set_setting(session, FLASH, json.dumps({"kind": kind, "km": km, **extra}))


def pop_flash(session: Session) -> dict | None:
    """Return and clear the one-time notice, or ``None``."""
    row = session.get(Setting, FLASH)
    if row is None:
        return None
    session.delete(row)
    session.flush()
    try:
        notice = json.loads(row.value)
    except ValueError:
        return None
    return notice if isinstance(notice, dict) else None


def get_summary_cards(session: Session) -> list[str]:
    """
    Card names to show on the Timeline, in display order.

    Unknown names are ignored. Without a (readable) stored choice the
    default set is returned; an explicitly empty choice stays empty.
    """
    raw = get_setting(session, SUMMARY_CARDS)
    if raw is None:
        return list(DEFAULT_CARDS)
    try:
        chosen = set(json.loads(raw))
    except (TypeError, ValueError):
        return list(DEFAULT_CARDS)
    return [key for key in CARD_KEYS if key in chosen]


def set_summary_cards(session: Session, names: list[str]) -> list[str]:
    """Store the chosen cards (unknown names dropped); return what was kept."""
    kept = [key for key in CARD_KEYS if key in set(names)]
    set_setting(session, SUMMARY_CARDS, json.dumps(kept))
    return kept


def get_hidden_summaries(session: Session) -> list[str]:
    """
    Summary groups the user switched off in "All vehicles".

    Entries are ``"all"`` (the combined group) or a vehicle id as text. Only
    the hidden ones are stored, so a new vehicle shows up by default.
    """
    raw = get_setting(session, HIDDEN_SUMMARIES)
    if raw is None:
        return []
    try:
        names = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(names, list):
        return []
    return [str(n) for n in names if str(n) == ALL_VEHICLES or str(n).isdigit()]


def update_hidden_summaries(
    session: Session, offered: list[str], shown: list[str]
) -> list[str]:
    """
    Hide the offered groups that are not ticked; leave other stored entries alone.

    ``offered`` are the groups the form listed, ``shown`` the ticked ones.
    Returns the new hidden list.
    """
    others = [n for n in get_hidden_summaries(session) if n not in offered]
    now_hidden = [n for n in offered if n not in shown]
    valid = [n for n in others + now_hidden if n == ALL_VEHICLES or n.isdigit()]
    set_setting(session, HIDDEN_SUMMARIES, json.dumps(valid))
    return valid


@dataclass(frozen=True)
class PeriodChoice:
    """A stored summary period: its name and, for "custom", the two dates."""

    key: str = periods.DEFAULT_PERIOD
    date_from: date | None = None
    date_to: date | None = None


def is_period_owner(owner: str) -> bool:
    """True for ``"combined"`` or a vehicle id (as text)."""
    return owner == COMBINED or owner.isdigit()


def get_period(session: Session, owner: str) -> PeriodChoice:
    """
    The summary period of a vehicle (id as text) or of the combined summary.

    A missing or unreadable value gives the default, "Last 12 months".
    """
    raw = get_setting(session, PERIOD_PREFIX + owner)
    if raw is None:
        return PeriodChoice()
    try:
        data = json.loads(raw)
        key = data["key"]
        if key not in periods.PERIOD_KEYS:
            return PeriodChoice()
        if key != periods.CUSTOM:
            return PeriodChoice(key)
        return PeriodChoice(
            key, date.fromisoformat(data["from"]), date.fromisoformat(data["to"])
        )
    except (TypeError, KeyError, ValueError):
        return PeriodChoice()


def set_period(session: Session, owner: str, choice: PeriodChoice) -> None:
    """
    Store the period for ``owner``.

    Raises
    ------
    ValueError
        If the owner or the period name is unknown, or "custom" lacks dates.
    """
    if not is_period_owner(owner):
        raise ValueError(f"unknown summary '{owner}'")
    if choice.key not in periods.PERIOD_KEYS:
        raise ValueError(f"unknown period '{choice.key}'")
    data: dict[str, str] = {"key": choice.key}
    if choice.key == periods.CUSTOM:
        if choice.date_from is None or choice.date_to is None:
            raise ValueError("a custom range needs both dates")
        data["from"] = choice.date_from.isoformat()
        data["to"] = choice.date_to.isoformat()
    set_setting(session, PERIOD_PREFIX + owner, json.dumps(data))
