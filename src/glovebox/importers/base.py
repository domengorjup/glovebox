"""
Importer interface (design D6). FROZEN; adapters implement ``ImporterAdapter``.

Adapters are pure: they turn bytes into canonical records in storage units and
never touch the database. Group 3 adds the shared locale helpers (encoding,
delimiter, decimal, date detection, alias loader) to this module; they must not
change the names below.
"""

from __future__ import annotations

import csv
import io
import re
import struct
import tomllib
import zlib
from dataclasses import dataclass, field
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from glovebox.models import ExpenseCategory


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


# --- Shared locale helpers (task 3.1) --------------------------------------

ALIASES_DIR = Path(__file__).parent / "aliases"
KM_PER_MILE = Decimal("1.609344")
LITRES_PER_US_GALLON = Decimal("3.785411784")
LITRES_PER_UK_GALLON = Decimal("4.54609")

_DELIMITERS = (",", ";", "\t")
_TRUE_WORDS = {"true", "yes", "y", "x", "t", "full"}
_DATE_RE = re.compile(
    r"^\s*(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})\.?"
    r"(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*$"
)


def decode_text(data: bytes) -> str:
    """Decode UTF-8 (with or without BOM), falling back to cp1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def sniff_delimiter(text: str) -> str:
    """
    Pick the delimiter (``,`` ``;`` or tab) that splits the first line best.

    Only the first line is used because data lines may contain decimal
    commas that would mislead the count.
    """
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    best, best_count = ",", 1
    for candidate in _DELIMITERS:
        count = len(next(csv.reader([first_line], delimiter=candidate), []))
        if count > best_count:
            best, best_count = candidate, count
    return best


def read_rows(text: str, delimiter: str | None = None) -> list[list[str]]:
    """Split CSV text into stripped rows, dropping fully blank rows."""
    delimiter = delimiter or sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader]
    return [row for row in rows if any(row)]


def read_csv_bytes(data: bytes) -> list[list[str]]:
    """Decode, sniff the delimiter and split bytes into rows."""
    return read_rows(decode_text(data))


def cell(row: list[str], index: int | None) -> str:
    """Return the stripped cell at ``index``, or ``""`` if absent."""
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def leading_zip_member(head: bytes) -> tuple[str, bytes] | None:
    """
    Name and (possibly truncated) content of the first member of a ZIP.

    Works on the first bytes of a ZIP only, so format detection does not
    need the whole file.
    """
    if head[:4] != b"PK\x03\x04" or len(head) < 30:
        return None
    method = struct.unpack_from("<H", head, 8)[0]
    name_len, extra_len = struct.unpack_from("<HH", head, 26)
    name = head[30 : 30 + name_len].decode("utf-8", errors="replace")
    body = head[30 + name_len + extra_len :]
    if method == 0:
        return name, body
    if method == 8:
        try:
            return name, zlib.decompressobj(-15).decompress(body)
        except zlib.error:
            return None
    return None


def detect_decimal_separator(values: list[str]) -> str:
    """
    Decide per column whether the decimal separator is ``.`` or ``,``.

    Strong evidence (both marks present, repeated marks, or a number of
    decimals other than three) wins. A lone mark followed by exactly three
    digits is ambiguous: ``,`` is chosen only if no other evidence exists.
    """
    comma_votes = dot_votes = 0
    weak_comma = False
    for raw in values:
        value = re.sub(r"[^\d.,]", "", raw)
        has_comma, has_dot = "," in value, "." in value
        if has_comma and has_dot:
            if value.rfind(",") > value.rfind("."):
                comma_votes += 1
            else:
                dot_votes += 1
        elif has_comma:
            decimals = len(value.rsplit(",", 1)[1])
            if value.count(",") > 1:
                dot_votes += 1
            elif decimals != 3:
                comma_votes += 1
            else:
                weak_comma = True
        elif has_dot:
            decimals = len(value.rsplit(".", 1)[1])
            if value.count(".") > 1:
                comma_votes += 1
            elif decimals != 3:
                dot_votes += 1
    if comma_votes != dot_votes:
        return "," if comma_votes > dot_votes else "."
    return "," if weak_comma else "."


def parse_number(text: str, decimal: str = ".") -> Decimal | None:
    """
    Parse a number with the given decimal separator.

    Returns ``None`` for empty text; raises ``ValueError`` for garbage.
    Thousands separators and currency symbols are ignored.
    """
    if not text.strip():
        return None
    cleaned = re.sub(r"[^\d.,+\-]", "", text)
    thousands = "," if decimal == "." else "."
    cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None


def parse_flag(text: str) -> bool:
    """Interpret ``1``, ``yes``, ``true`` (and any non-zero number) as true."""
    value = text.strip().casefold()
    if value in _TRUE_WORDS:
        return True
    try:
        return Decimal(value) != 0
    except InvalidOperation:
        return False


def scale_to_int(value: Decimal, factor: int) -> int:
    """Multiply by ``factor`` and round half up (e.g. litres to milli-litres)."""
    return int((value * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class DateDetection:
    """
    Result of ``detect_date_order``.

    ``order`` is ``"ymd"``, ``"dmy"`` or ``"mdy"``; ``None`` with
    ``ambiguous`` true means day-first and month-first both fit every value.
    """

    order: str | None
    ambiguous: bool = False


def parse_date_value(text: str, order: str) -> tuple[date, time | None] | None:
    """Parse one date (with optional time) in the given order, or ``None``."""
    match = _DATE_RE.match(text)
    if match is None:
        return None
    first, _, second, third, hour, minute, sec = match.groups()
    try:
        if order == "ymd":
            if len(first) != 4:
                return None
            year, month, day = int(first), int(second), int(third)
        else:
            if len(first) > 2 or len(third) not in (2, 4):
                return None
            year = int(third) + (0 if len(third) == 4 else _century(int(third)))
            a, b = int(first), int(second)
            day, month = (a, b) if order == "dmy" else (b, a)
        parsed_time = time(int(hour), int(minute), int(sec or 0)) if hour else None
        return date(year, month, day), parsed_time
    except ValueError:
        return None


def _century(two_digit_year: int) -> int:
    return 2000 if two_digit_year < 70 else 1900


def detect_date_order(values: list[str]) -> DateDetection:
    """Find the one date order that parses every non-empty value."""
    values = [v for v in values if v.strip()]
    if not values:
        return DateDetection(None)
    possible = [
        order
        for order in ("ymd", "dmy", "mdy")
        if all(parse_date_value(v, order) for v in values)
    ]
    if len(possible) == 1:
        return DateDetection(possible[0])
    if len(possible) == 2 and "ymd" not in possible:
        return DateDetection(None, ambiguous=True)
    return DateDetection(possible[0]) if possible else DateDetection(None)


def resolve_date_order(values: list[str], requested: str | None) -> DateDetection:
    """``detect_date_order`` with the user's answer applied if still ambiguous."""
    detection = detect_date_order(values)
    if detection.ambiguous and requested in ("dmy", "mdy"):
        if all(parse_date_value(v, requested) for v in values if v.strip()):
            return DateDetection(requested)
    return detection


def normalize_header(header: str) -> str:
    """Case- and whitespace-insensitive form of a header or alias."""
    return " ".join(header.replace("\ufeff", "").split()).casefold()


@dataclass(frozen=True)
class AliasTable:
    """
    Alias data of one format: ``section -> canonical name -> [aliases]``.

    ``provisional`` mirrors ``[meta] provisional`` in the TOML file.
    """

    provisional: bool
    sections: dict[str, dict[str, list[str]]]

    def match(self, section: str, headers: list[str]) -> dict[str, int]:
        """Map canonical names to column indexes for the headers found."""
        index = {}
        for position, header in enumerate(headers):
            index.setdefault(normalize_header(header), position)
        found = {}
        for canonical, aliases in self.sections[section].items():
            for alias in aliases:
                if (position := index.get(normalize_header(alias))) is not None:
                    found[canonical] = position
                    break
        return found

    def expected(self, section: str, required: list[str]) -> list[str]:
        """The primary alias of each required canonical name."""
        return [self.sections[section][name][0] for name in required]

    def lookup(self, section: str, value: str) -> str | None:
        """Reverse lookup: the canonical name whose aliases contain ``value``."""
        wanted = normalize_header(value)
        for canonical, aliases in self.sections[section].items():
            if wanted in {normalize_header(a) for a in aliases}:
                return canonical
        return None


def load_aliases(name: str, directory: Path = ALIASES_DIR) -> AliasTable:
    """Load ``aliases/<name>.toml``."""
    with (directory / f"{name}.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    meta = raw.pop("meta", {})
    return AliasTable(provisional=bool(meta.get("provisional", False)), sections=raw)
