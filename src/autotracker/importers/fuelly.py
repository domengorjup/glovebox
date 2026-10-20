"""
Fuelly adapter (design D7): the fuelly.com import format and export format.

Both formats are UNVERIFIED against real files. The format is told apart by
its headers (``fuelup_date`` versus ``Fuelup Date``).
"""

from __future__ import annotations

from decimal import Decimal

from autotracker.importers.base import (
    KM_PER_MILE,
    LITRES_PER_US_GALLON,
    Ambiguity,
    AliasTable,
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
    parse_date_value,
    parse_flag,
    parse_number,
    read_rows,
    resolve_date_order,
    scale_to_int,
)

_EXPECTED_HEADERS = ["fuelup_date", "odometer", "litres or gallons", "price"]


class FuellyAdapter:
    """Adapter for Fuelly CSV files (import and export format)."""

    name = "fuelly"

    def __init__(self) -> None:
        self._aliases: AliasTable = load_aliases("fuelly")

    def detect(self, head: bytes) -> float:
        """Return 0.95 for the import format, 0.9 for the export format."""
        if leading_zip_member(head):
            return 0.0
        rows = read_rows(decode_text(head)[:4096])
        headers = {normalize_header(h) for h in rows[0]} if rows else set()
        if "fuelup_date" in headers:
            return 0.95
        return 0.9 if "fuelup date" in headers else 0.0

    def parse(self, data: bytes, options: ImportOptions) -> ImportResult:
        """Parse the file; never raises on bad content."""
        result = ImportResult()
        rows = read_rows(decode_text(data))
        headers = rows[0] if rows else []
        section = _format_of(headers)
        columns = self._aliases.match(section, headers) if section else {}
        fuel_key = "litres" if "litres" in columns else "gallons"
        if section is None or "date" not in columns or fuel_key not in columns:
            return _mismatch(result, headers)
        if "odometer" not in columns:
            return _mismatch(result, headers)
        imperial = _imperial(section, fuel_key, options)
        if imperial is None:
            result.ambiguities.append(Ambiguity.UNITS)
            return result
        body = rows[1:]
        order = resolve_date_order(
            [cell(r, columns["date"]) for r in body], options.date_order
        )
        if order.ambiguous:
            result.ambiguities.append(Ambiguity.DATE_ORDER)
            return result
        if order.order is None:
            result.errors.append("Dates are not recognised.")
            return result
        miles = _miles(section, headers[columns["odometer"]], imperial)
        reader = _RowReader(columns, fuel_key, body, imperial, miles, order.order)
        if section == "export":
            result.warnings.append(
                "The Fuelly export format has no partial or missed flags; "
                "all fill-ups are treated as full."
            )
        for number, row in enumerate(body, start=1):
            try:
                refuel = reader.refuel(row)
            except ValueError as error:
                result.warnings.append(f"Row {number} skipped: {error}")
                continue
            result.refuels.append(refuel)
            _note_vehicle(result, refuel.vehicle_name)
        return result


class _RowReader:
    """Converts rows of one Fuelly file to canonical refuels."""

    def __init__(
        self,
        columns: dict[str, int],
        fuel_key: str,
        body: list[list[str]],
        imperial: bool,
        miles: bool,
        order: str,
    ) -> None:
        self.columns = columns
        self.fuel_key = fuel_key
        self.imperial = imperial
        self.miles = miles
        self.order = order
        self.decimals = {
            key: detect_decimal_separator([cell(r, columns[key]) for r in body])
            for key in ("odometer", fuel_key, "price")
            if key in columns
        }

    def refuel(self, row: list[str]) -> CanonicalRefuel:
        """Convert one row; raises ``ValueError`` if it cannot be used."""
        columns = self.columns
        parsed = parse_date_value(cell(row, columns["date"]), self.order)
        if parsed is None:
            raise ValueError(f"bad date {cell(row, columns['date'])!r}")
        odometer = self._number(row, "odometer")
        quantity = self._number(row, self.fuel_key)
        if odometer is None or quantity is None or quantity <= 0:
            raise ValueError("odometer or fuel quantity missing")
        price = self._number(row, "price")
        if self.miles:
            odometer *= KM_PER_MILE
        if self.imperial:
            quantity *= LITRES_PER_US_GALLON
            price = price / LITRES_PER_US_GALLON if price else price
        return CanonicalRefuel(
            vehicle_name=cell(row, columns.get("vehicle")) or None,
            date=parsed[0],
            time=parsed[1],
            odometer_km=float(round(odometer, 3)),
            litres_milli=scale_to_int(quantity, 1000),
            price_per_litre_milli=scale_to_int(price, 1000) if price else None,
            is_full=not parse_flag(cell(row, columns.get("partial"))),
            missed_previous=parse_flag(cell(row, columns.get("missed"))),
            notes=cell(row, columns.get("notes")) or None,
        )

    def _number(self, row: list[str], key: str) -> Decimal | None:
        if key not in self.columns:
            return None
        return parse_number(cell(row, self.columns[key]), self.decimals[key])


def _format_of(headers: list[str]) -> str | None:
    normalized = {normalize_header(h) for h in headers}
    if "fuelup_date" in normalized:
        return "import"
    return "export" if "fuelup date" in normalized else None


def _imperial(section: str, fuel_key: str, options: ImportOptions) -> bool | None:
    """True for gallons, False for litres, ``None`` if the user must say."""
    if fuel_key == "litres":
        return False
    if section == "import":
        return True
    if options.units in ("metric", "imperial"):
        return options.units == "imperial"
    return None


def _miles(section: str, odometer_header: str, imperial: bool) -> bool:
    if section == "import" and normalize_header(odometer_header) in ("km", "miles"):
        return normalize_header(odometer_header) == "miles"
    return imperial


def _mismatch(result: ImportResult, headers: list[str]) -> ImportResult:
    result.header_mismatch = HeaderMismatch(found=headers, expected=_EXPECTED_HEADERS)
    result.errors.append("Required Fuelly headers are missing.")
    return result


def _note_vehicle(result: ImportResult, name: str | None) -> None:
    if name and all(v.name != name for v in result.vehicles):
        result.vehicles.append(CanonicalVehicleRef(name))
