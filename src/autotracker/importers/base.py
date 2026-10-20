"""
Importer interface (design D6). FROZEN; adapters implement ``ImporterAdapter``.

Adapters are pure: they turn bytes into canonical records in storage units and
never touch the database. Group 3 adds the shared locale helpers (encoding,
delimiter, decimal, date detection, alias loader) to this module; they must not
change the names below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from enum import StrEnum
from typing import Protocol, runtime_checkable

from autotracker.models import ExpenseCategory


@dataclass(frozen=True)
class CanonicalVehicleRef:
    """A vehicle name found in the file (``None``-name files have no refs)."""

    name: str


@dataclass(frozen=True)
class CanonicalRefuel:
    """
    One refuel in storage units (km, thousandths of litres, cents,
    milli-units per litre). Figures the file does not provide are ``None``;
    the pipeline derives them with ``records.derive_price_figures``.
    """

    vehicle_name: str | None
    date: date
    odometer_km: float
    litres_milli: int | None
    price_per_litre_milli: int | None = None
    total_cents: int | None = None
    time: time | None = None
    station_name: str | None = None
    station_brand: str | None = None  # only if the source provides it
    is_full: bool = True
    missed_previous: bool = False
    notes: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class CanonicalExpense:
    """One expense in storage units; ``title`` keeps the original label."""

    vehicle_name: str | None
    date: date
    category: ExpenseCategory
    amount_cents: int
    title: str = ""
    odometer_km: float | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    notes: str | None = None
    source_ref: str | None = None


class Ambiguity(StrEnum):
    """Questions the preview must ask the user."""

    DATE_ORDER = "date_order"  # day-first vs month-first
    UNITS = "units"  # metric vs imperial


@dataclass(frozen=True)
class ImportOptions:
    """
    User answers passed to ``parse``. ``None`` means "not answered / auto".

    Attributes
    ----------
    date_order : str | None
        ``"dmy"`` or ``"mdy"``.
    units : str | None
        ``"metric"`` or ``"imperial"`` (miles and gallons).
    """

    date_order: str | None = None
    units: str | None = None


@dataclass(frozen=True)
class HeaderMismatch:
    """Reported when required headers are missing; nothing is imported."""

    found: list[str]
    expected: list[str]


@dataclass
class ImportResult:
    """
    Output of ``ImporterAdapter.parse``.

    ``ambiguities`` lists unanswered questions; the pipeline re-parses with
    ``ImportOptions`` once the user answers. ``errors`` non-empty means the
    file cannot be imported.
    """

    refuels: list[CanonicalRefuel] = field(default_factory=list)
    expenses: list[CanonicalExpense] = field(default_factory=list)
    vehicles: list[CanonicalVehicleRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)
    header_mismatch: HeaderMismatch | None = None


@runtime_checkable
class ImporterAdapter(Protocol):
    """
    One file format. Register instances in ``importers.pipeline``.

    Attributes
    ----------
    name : str
        Format id stored in ``import_batch.format`` and ``source``:
        ``"drivvo"``, ``"fuelio"``, ``"fuelly"`` or ``"native"``.
    """

    name: str

    def detect(self, head: bytes) -> float:
        """Return confidence 0.0-1.0 that the file (first bytes) is this format."""
        ...

    def parse(self, data: bytes, options: ImportOptions) -> ImportResult:
        """Parse the whole file. Must not raise on bad content; report in
        ``errors`` / ``header_mismatch`` instead."""
        ...
