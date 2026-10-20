"""
Drivvo adapter (design D7), built on the shared importer machinery.

The English header mapping in ``aliases/drivvo.toml`` is PROVISIONAL: it is a
best guess, not taken from a real Drivvo export. A file holds one table of
refuelling, service or expense rows; the headers tell which.
"""

from __future__ import annotations

from autotracker.importers.base import (
    Ambiguity,
    AliasTable,
    CanonicalExpense,
    CanonicalRefuel,
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
from autotracker.models import ExpenseCategory

# Required canonical fields per table kind, in classification order.
_REQUIRED = {
    "refuel": ["date", "odometer", "litres"],
    "service": ["date", "title", "amount"],
    "expense": ["date", "title", "amount"],
}


class DrivvoAdapter:
    """Adapter for Drivvo CSV exports (provisional English mapping)."""

    name = "drivvo"

    def __init__(self) -> None:
        self._aliases: AliasTable = load_aliases("drivvo")

    def detect(self, head: bytes) -> float:
        """Return 0.6 if the headers fit a refuel, service or expense table."""
        if leading_zip_member(head):
            return 0.0
        rows = read_rows(decode_text(head)[:4096])
        if not rows:
            return 0.0
        headers = {normalize_header(h) for h in rows[0]}
        if "fuelup_date" in headers or "fuelup date" in headers:
            return 0.0
        return 0.6 if self._classify(rows[0]) else 0.0

    def parse(self, data: bytes, options: ImportOptions) -> ImportResult:
        """Parse the file; unknown headers are reported, not guessed."""
        result = ImportResult()
        rows = read_rows(decode_text(data))
        headers = rows[0] if rows else []
        kind = self._classify(headers)
        if kind is None:
            result.header_mismatch = self._mismatch(headers)
            result.errors.append("The Drivvo headers were not recognised.")
            return result
        columns = self._aliases.match(kind, headers)
        body = rows[1:]
        detection = resolve_date_order(
            [cell(r, columns["date"]) for r in body], options.date_order
        )
        if detection.ambiguous:
            result.ambiguities.append(Ambiguity.DATE_ORDER)
            return result
        if detection.order is None:
            result.errors.append("Dates are not recognised.")
            return result
        if self._aliases.provisional:
            result.warnings.append(
                "The Drivvo header mapping is provisional (not checked against "
                "a real export)."
            )
        self._read_rows(kind, columns, body, detection.order, result)
        return result

    def _classify(self, headers: list[str]) -> str | None:
        for kind, required in _REQUIRED.items():
            columns = self._aliases.match(kind, headers)
            if all(name in columns for name in required):
                return kind
        return None

    def _mismatch(self, headers: list[str]) -> HeaderMismatch:
        expected = [
            f"{kind}: " + ", ".join(self._aliases.expected(kind, required))
            for kind, required in _REQUIRED.items()
        ]
        return HeaderMismatch(found=headers, expected=expected)

    def _read_rows(
        self,
        kind: str,
        columns: dict[str, int],
        body: list[list[str]],
        order: str,
        result: ImportResult,
    ) -> None:
        numeric = ("odometer", "litres", "price_per_litre", "total", "amount")
        decimals = {
            key: detect_decimal_separator([cell(r, columns[key]) for r in body])
            for key in numeric
            if key in columns
        }
        for number, row in enumerate(body, start=1):
            try:
                parsed = parse_date_value(cell(row, columns["date"]), order)
                if parsed is None:
                    raise ValueError(f"bad date {cell(row, columns['date'])!r}")
                if kind == "refuel":
                    record = self._refuel(row, columns, decimals, parsed)
                    result.refuels.append(record)
                else:
                    expense = self._expense(kind, row, columns, decimals, parsed)
                    result.expenses.append(expense)
            except ValueError as error:
                result.warnings.append(f"Row {number} skipped: {error}")

    def _refuel(self, row, columns, decimals, parsed) -> CanonicalRefuel:
        odometer = _number(row, columns, decimals, "odometer")
        litres = _number(row, columns, decimals, "litres")
        if odometer is None or litres is None or litres <= 0:
            raise ValueError("odometer or fuel quantity missing")
        price = _number(row, columns, decimals, "price_per_litre")
        total = _number(row, columns, decimals, "total")
        full_text = cell(row, columns.get("full"))
        return CanonicalRefuel(
            vehicle_name=None,
            date=parsed[0],
            time=parsed[1],
            odometer_km=float(round(odometer, 3)),
            litres_milli=scale_to_int(litres, 1000),
            price_per_litre_milli=scale_to_int(price, 1000) if price else None,
            total_cents=scale_to_int(total, 100) if total else None,
            station_name=cell(row, columns.get("station")) or None,
            is_full=parse_flag(full_text) if full_text else True,
            missed_previous=parse_flag(cell(row, columns.get("missed"))),
            notes=cell(row, columns.get("notes")) or None,
        )

    def _expense(self, kind, row, columns, decimals, parsed) -> CanonicalExpense:
        amount = _number(row, columns, decimals, "amount")
        if amount is None or amount <= 0:
            raise ValueError("amount missing or not positive")
        title = cell(row, columns["title"])
        default = "maintenance" if kind == "service" else "other"
        category = self._aliases.lookup("categories", title) or default
        odometer = _number(row, columns, decimals, "odometer")
        return CanonicalExpense(
            vehicle_name=None,
            date=parsed[0],
            category=ExpenseCategory(category),
            amount_cents=scale_to_int(amount, 100),
            title=title,
            odometer_km=float(odometer) if odometer and odometer > 0 else None,
            notes=cell(row, columns.get("notes")) or None,
        )


def _number(row, columns, decimals, key):
    if key not in columns:
        return None
    return parse_number(cell(row, columns[key]), decimals[key])
