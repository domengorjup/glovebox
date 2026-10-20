"""
Fuelio backup adapter (design D7).

Reads a single CSV or a ZIP with one CSV per vehicle. Each CSV consists of
sections introduced by a ``## Name`` line (``## Vehicle``, ``## Log``,
``## CostCategories``, ``## Costs``, ``## FavStations``). The format is
reverse-engineered, not taken from Fuelio's own documentation.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace
from decimal import Decimal
from pathlib import PurePosixPath

from autotracker.importers.base import (
    KM_PER_MILE,
    LITRES_PER_UK_GALLON,
    LITRES_PER_US_GALLON,
    Ambiguity,
    AliasTable,
    CanonicalExpense,
    CanonicalRefuel,
    CanonicalVehicleRef,
    HeaderMismatch,
    ImportOptions,
    ImportResult,
    cell,
    decode_text,
    detect_decimal_separator,
    leading_zip_member,
    load_aliases,
    normalize_header,
    parse_flag,
    parse_number,
    read_rows,
    resolve_date_order,
    parse_date_value,
    scale_to_int,
)
from autotracker.models import ExpenseCategory

_SECTION_RE = re.compile(r'^\s*"?##\s*([^",;\t\r\n]+)')
_LOG_MARKER_RE = re.compile(r'(?m)^\s*"?##\s*Log\b')
_ODO_RE = re.compile(r"^odo\s*(\(|$)", re.IGNORECASE)
_FUEL_RE = re.compile(r"^fuel\s*(\(|$)", re.IGNORECASE)
_UNIT_RE = re.compile(r"\(([^)]*)\)")


class FuelioAdapter:
    """Adapter for Fuelio CSV backups (single CSV or ZIP of CSVs)."""

    name = "fuelio"

    def __init__(self) -> None:
        self._aliases: AliasTable = load_aliases("fuelio")

    def detect(self, head: bytes) -> float:
        """Return 0.95 if the content has a ``## Log`` line, else 0."""
        member = leading_zip_member(head)
        text = decode_text(member[1]) if member else decode_text(head)
        return 0.95 if _LOG_MARKER_RE.search(text) else 0.0

    def parse(self, data: bytes, options: ImportOptions) -> ImportResult:
        """Parse all vehicles of the backup; never raises on bad content."""
        result = ImportResult()
        try:
            files = _read_container(data)
        except zipfile.BadZipFile:
            result.errors.append("The ZIP file is damaged.")
            return result
        for file_name, text, from_zip in files:
            sections = _split_sections(text)
            if "Log" not in sections and "Costs" not in sections:
                result.errors.append(f"{file_name}: no '## Log' section found.")
                continue
            fallback = PurePosixPath(file_name).stem if from_zip else None
            self._parse_file(sections, fallback, options, result)
        if not result.refuels and not result.expenses and not result.errors:
            if not result.ambiguities and result.header_mismatch is None:
                result.warnings.append("The file contains no fuel log or cost rows.")
        return result

    def _parse_file(
        self,
        sections: dict[str, str],
        fallback_name: str | None,
        options: ImportOptions,
        result: ImportResult,
    ) -> None:
        vehicle = self._vehicle_name(sections, fallback_name)
        if vehicle and all(v.name != vehicle for v in result.vehicles):
            result.vehicles.append(CanonicalVehicleRef(vehicle))
        if "Log" in sections:
            self._parse_log(sections, vehicle, options, result)
        if "Costs" in sections:
            self._parse_costs(sections, vehicle, options, result)

    def _vehicle_name(
        self, sections: dict[str, str], fallback: str | None
    ) -> str | None:
        headers, rows = _table(sections.get("Vehicle", ""))
        columns = self._aliases.match("vehicle", headers)
        if rows and "name" in columns and (name := cell(rows[0], columns["name"])):
            return name
        return fallback

    # --- ## Log ------------------------------------------------------------

    def _parse_log(
        self,
        sections: dict[str, str],
        vehicle: str | None,
        options: ImportOptions,
        result: ImportResult,
    ) -> None:
        headers, rows = _table(sections["Log"])
        columns = self._aliases.match("log", headers)
        columns["odometer"] = _find(headers, _ODO_RE)
        columns["fuel"] = _find(headers, _FUEL_RE)
        missing = [k for k in ("date", "odometer", "fuel") if columns.get(k) is None]
        if missing:
            result.header_mismatch = HeaderMismatch(
                found=headers, expected=["Data", "Odo (km)", "Fuel (litres)"]
            )
            result.errors.append("The '## Log' section lacks required headers.")
            return
        context = _LogContext(self._aliases, sections, headers, rows, columns)
        detection = resolve_date_order(
            [cell(r, columns["date"]) for r in rows], options.date_order
        )
        if detection.ambiguous:
            _ask(result, Ambiguity.DATE_ORDER)
            return
        if detection.order is None:
            result.errors.append("Dates in the '## Log' section are not recognised.")
            return
        for number, row in enumerate(rows, start=1):
            try:
                refuel = context.refuel(row, vehicle, detection.order)
            except ValueError as error:
                result.warnings.append(f"Log row {number} skipped: {error}")
                continue
            result.refuels.append(refuel)

    # --- ## Costs ----------------------------------------------------------

    def _parse_costs(
        self,
        sections: dict[str, str],
        vehicle: str | None,
        options: ImportOptions,
        result: ImportResult,
    ) -> None:
        headers, rows = _table(sections["Costs"])
        columns = self._aliases.match("costs", headers)
        if not rows:
            return
        if "date" not in columns or "cost" not in columns:
            result.warnings.append("The '## Costs' section lacks Date/Cost headers.")
            return
        names = self._category_names(sections)
        detection = resolve_date_order(
            [cell(r, columns["date"]) for r in rows], options.date_order
        )
        if detection.ambiguous:
            _ask(result, Ambiguity.DATE_ORDER)
            return
        if detection.order is None:
            result.errors.append("Dates in the '## Costs' section are not recognised.")
            return
        decimal = detect_decimal_separator([cell(r, columns["cost"]) for r in rows])
        for number, row in enumerate(rows, start=1):
            try:
                expense = self._expense(row, columns, names, decimal, detection.order)
            except ValueError as error:
                result.warnings.append(f"Cost row {number} skipped: {error}")
                continue
            if expense is not None:
                result.expenses.append(_with_vehicle(expense, vehicle))

    def _category_names(self, sections: dict[str, str]) -> dict[str, str]:
        headers, rows = _table(sections.get("CostCategories", ""))
        columns = self._aliases.match("cost_categories", headers)
        if "type_id" not in columns or "name" not in columns:
            return {}
        return {cell(r, columns["type_id"]): cell(r, columns["name"]) for r in rows}

    def _expense(
        self,
        row: list[str],
        columns: dict[str, int],
        names: dict[str, str],
        decimal: str,
        order: str,
    ) -> CanonicalExpense | None:
        if parse_flag(cell(row, columns.get("is_template"))):
            return None
        if parse_flag(cell(row, columns.get("is_income"))):
            return None
        cost = parse_number(cell(row, columns["cost"]), decimal)
        if cost is None or cost <= 0:
            return None
        parsed = parse_date_value(cell(row, columns["date"]), order)
        if parsed is None:
            raise ValueError(f"bad date {cell(row, columns['date'])!r}")
        category_name = names.get(cell(row, columns.get("type_id")), "")
        category = self._aliases.lookup("categories", category_name)
        item_title = cell(row, columns.get("title"))
        notes = "; ".join(
            part
            for part in (item_title, cell(row, columns.get("notes")))
            if part and part != category_name
        )
        odometer = parse_number(cell(row, columns.get("odometer")), decimal)
        return CanonicalExpense(
            vehicle_name=None,
            date=parsed[0],
            category=ExpenseCategory(category or "other"),
            amount_cents=scale_to_int(cost, 100),
            title=category_name or item_title,
            odometer_km=float(odometer) if odometer and odometer > 0 else None,
            notes=notes or None,
        )


class _LogContext:
    """Per-section state for turning ``## Log`` rows into refuels."""

    def __init__(
        self,
        aliases: AliasTable,
        sections: dict[str, str],
        headers: list[str],
        rows: list[list[str]],
        columns: dict[str, int],
    ) -> None:
        self.columns = columns
        self.miles = _unit_of(headers[columns["odometer"]]) in ("mi", "mile", "miles")
        self.gallon_factor = _gallon_factor(_unit_of(headers[columns["fuel"]]))
        self.decimals = {
            key: detect_decimal_separator([cell(r, columns[key]) for r in rows])
            for key in ("odometer", "fuel", "total", "price_per_litre")
            if key in columns
        }
        self.stations = _favourite_stations(aliases, sections)

    def refuel(
        self, row: list[str], vehicle: str | None, order: str
    ) -> CanonicalRefuel:
        """Convert one row; raises ``ValueError`` if it cannot be used."""
        columns = self.columns
        parsed = parse_date_value(cell(row, columns["date"]), order)
        if parsed is None:
            raise ValueError(f"bad date {cell(row, columns['date'])!r}")
        odometer = self._number(row, "odometer")
        fuel = self._number(row, "fuel")
        if odometer is None or fuel is None or fuel <= 0:
            raise ValueError("odometer or fuel quantity missing")
        total = self._number(row, "total")
        unit_price = self._number(row, "price_per_litre")
        if self.miles:
            odometer *= KM_PER_MILE
        if self.gallon_factor:
            fuel *= self.gallon_factor
            if unit_price:
                unit_price /= self.gallon_factor
        return CanonicalRefuel(
            vehicle_name=vehicle,
            date=parsed[0],
            time=parsed[1],
            odometer_km=float(round(odometer, 3)),
            litres_milli=scale_to_int(fuel, 1000),
            price_per_litre_milli=_positive(unit_price, 1000),
            total_cents=_positive(total, 100),
            station_name=self._station(row),
            is_full=cell(row, columns.get("full")) != "0",
            missed_previous=parse_flag(cell(row, columns.get("missed"))),
            notes=cell(row, columns.get("notes")) or None,
            source_ref=cell(row, columns.get("unique_id")) or None,
        )

    def _number(self, row: list[str], key: str) -> Decimal | None:
        if key not in self.columns:
            return None
        return parse_number(cell(row, self.columns[key]), self.decimals[key])

    def _station(self, row: list[str]) -> str | None:
        station_id = cell(row, self.columns.get("station_id"))
        favourite = self.stations.get(station_id)
        return favourite or cell(row, self.columns.get("city")) or None


def _positive(value: Decimal | None, factor: int) -> int | None:
    """Fuelio writes 0 for "not given"; treat that as missing."""
    if value is None or value <= 0:
        return None
    return scale_to_int(value, factor)


def _with_vehicle(expense: CanonicalExpense, vehicle: str | None) -> CanonicalExpense:
    return replace(expense, vehicle_name=vehicle)


def _favourite_stations(aliases: AliasTable, sections: dict[str, str]) -> dict[str, str]:
    headers, rows = _table(sections.get("FavStations", ""))
    columns = aliases.match("fav_stations", headers)
    if "station_id" not in columns or "name_brand" not in columns:
        return {}
    pairs = ((cell(r, columns["station_id"]), cell(r, columns["name_brand"])) for r in rows)
    return {key: name for key, name in pairs if key and name}


def _unit_of(header: str) -> str:
    match = _UNIT_RE.search(header)
    return normalize_header(match.group(1)) if match else ""


def _gallon_factor(unit: str) -> Decimal | None:
    if unit.startswith(("imp", "uk")):
        return LITRES_PER_UK_GALLON
    return LITRES_PER_US_GALLON if "gal" in unit else None


def _find(headers: list[str], pattern: re.Pattern[str]) -> int | None:
    for position, header in enumerate(headers):
        if pattern.match(header.strip()):
            return position
    return None


def _ask(result: ImportResult, question: Ambiguity) -> None:
    if question not in result.ambiguities:
        result.ambiguities.append(question)


def _table(text: str) -> tuple[list[str], list[list[str]]]:
    rows = read_rows(text)
    return (rows[0], rows[1:]) if rows else ([], [])


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines(keepends=True):
        if match := _SECTION_RE.match(line):
            current = sections.setdefault(match.group(1).strip(), [])
        elif current is not None:
            current.append(line)
    return {name: "".join(lines) for name, lines in sections.items()}


def _read_container(data: bytes) -> list[tuple[str, str, bool]]:
    """Return ``(name, text, from_zip)`` for each CSV in the upload."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return [("file", decode_text(data), False)]
    files = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            files.append((info.filename, decode_text(archive.read(info)), True))
    return files
