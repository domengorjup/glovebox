"""
Preset-driven CSV import engine (design D6). Pure: no database access.

``read_file`` splits an upload into tables, ``score`` rates a preset against
them, ``apply`` turns the rows into canonical records in storage units.
"""

from __future__ import annotations

import copy
import csv
import functools
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from glovebox.importers.base import (
    KM_PER_MILE,
    LITRES_PER_UK_GALLON,
    LITRES_PER_US_GALLON,
    Answers,
    CanonicalExpense,
    CanonicalRefuel,
    CanonicalVehicleRef,
    ImportResult,
    Question,
    QuestionKind,
    RowError,
    detect_decimal_separator,
    normalize_header,
    parse_date_value,
    scale_to_int,
    sniff_delimiter,
)
from glovebox.importers.presets import (
    SHIPPED_DIR,
    STANDARD_ID,
    FieldMapping,
    FormatSettings,
    Preset,
    load_preset,
)
from glovebox.models import DerivedField, ExpenseCategory
from glovebox.standard import (
    EXPENSE,
    FALSE_VALUE,
    RECORD_FIELDS,
    REFUEL,
    TRUE_VALUE,
    StandardField,
)

HEADER_SCAN_ROWS = 20
_DETECT_LINES = 80
_MAX_UNCOMPRESSED = 200 * 1024 * 1024
_DELIMITERS = (",", ";", "\t")
_ORDERS = ("ymd", "dmy", "mdy")
_SECTION_RE = re.compile(
    r'^\s*"?\s*##\s*(?P<name>[^",;\t]*?)\s*"?\s*[,;\t]*\s*$'
)
_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_UNIT_RE = re.compile(r"\(([^()]*)\)\s*$")
_TRUE_WORDS = {"true", "1", "yes", "y", "t"}
_FALSE_WORDS = {"false", "0", "no", "n", "f"}
_FIELDS: dict[str, StandardField] = {f.name: f for f in RECORD_FIELDS}
_DERIVED = {
    "fuel_l": DerivedField.LITRES,
    "price_per_l": DerivedField.PRICE_PER_LITRE,
    "total": DerivedField.TOTAL,
}
_DISTANCE_WORDS = {
    "km": "km", "kms": "km", "kilometer": "km", "kilometers": "km",
    "kilometre": "km", "kilometres": "km",
    "mi": "mi", "mile": "mi", "miles": "mi",
}  # fmt: skip
_VOLUME_WORDS = {
    "l": "l", "lt": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "gal": "gal_us", "gallon": "gal_us", "gallons": "gal_us", "us gal": "gal_us",
    "us gallon": "gal_us", "us gallons": "gal_us", "gal us": "gal_us",
    "uk gal": "gal_uk", "uk gallon": "gal_uk", "uk gallons": "gal_uk",
    "imp gal": "gal_uk", "imperial gallon": "gal_uk", "imperial gallons": "gal_uk",
    "gal uk": "gal_uk",
}  # fmt: skip
_LITRES_PER = {
    "l": Decimal(1),
    "gal_us": LITRES_PER_US_GALLON,
    "gal_uk": LITRES_PER_UK_GALLON,
}
_KM_PER = {"km": Decimal(1), "mi": KM_PER_MILE}


@dataclass
class SourceTable:
    """
    One CSV table of an upload (a file, one ZIP member, or one section).

    Attributes
    ----------
    name : str
        File stem (ZIP member) or upload name; the default vehicle name when
        the preset has no ``vehicle`` field. Empty for a plain CSV.
    headers : list[str]
        The header row as found.
    rows : list[tuple[int, list[str]]]
        Data rows with their 1-based line number in the file.
    encoding, delimiter : str
        What was used to read the table.
    header_row : int
        Header position over the non-blank rows (1 = first).
    """

    name: str
    headers: list[str]
    rows: list[tuple[int, list[str]]]
    encoding: str = "utf-8"
    delimiter: str = ","
    header_row: int = 1


@dataclass
class SourceFile:
    """
    A read upload: its record tables, the optional ``vehicles`` and ``stations``
    tables of a ZIP (members ``vehicles.csv`` / ``stations.csv``, recognised by
    name and by a ``name`` column without a ``date`` column), and whether it is
    a full backup (a ZIP that also holds ``datapackage.json``).
    """

    tables: list[SourceTable] = field(default_factory=list)
    vehicles: SourceTable | None = None
    stations: SourceTable | None = None
    is_backup: bool = False
    sections: list[str] = field(default_factory=list)  # ``## name`` lines found


# --- Standard preset --------------------------------------------------------


def standard_preset() -> Preset:
    """
    The standard preset: the shipped ``glovebox`` preset (every record field
    read from the column of the same name, with the standard's fixed formats).
    This is the single source for import detection, backup restore and export.
    """
    return copy.deepcopy(_standard_preset())


@functools.cache
def _standard_preset() -> Preset:
    path = SHIPPED_DIR / f"{STANDARD_ID}.toml"
    return load_preset(path.read_text(encoding="utf-8"), id=STANDARD_ID, shipped=True)


def fallback_preset(source: SourceFile) -> Preset:
    """
    Start of the mapping when no preset fits: the standard preset with only the
    fields whose column name equals the standard field name, and automatic
    date and number formats (the units are the standard's km and litres).
    The result has no id and is not shipped.
    """
    headers: set[str] = set()
    for table in source.tables:
        headers.update(normalize_header(h) for h in table.headers)
    fields = {
        f.name: FieldMapping(columns=(f.name,))
        for f in RECORD_FIELDS
        if normalize_header(f.name) in headers
    }
    return Preset(
        name="Custom mapping",
        format=FormatSettings(distance_unit="km", volume_unit="l"),
        fields=fields,
    )


# --- Header matching --------------------------------------------------------


def match_header(candidate: str, header: str) -> bool:
    """
    Case- and whitespace-insensitive header comparison (design D4). A trailing
    ``(...)`` of the header is ignored unless the candidate has one itself.
    """
    wanted = normalize_header(candidate)
    found = normalize_header(header)
    if "(" in wanted:
        return wanted == found
    return wanted == _PAREN_RE.sub("", found).strip()


def find_column(candidates: tuple[str, ...] | list[str], headers: list[str]) -> int | None:
    """Index of the first header matched by the first matching candidate."""
    for candidate in candidates:
        for position, header in enumerate(headers):
            if match_header(candidate, header):
                return position
    return None


# --- Reading ----------------------------------------------------------------


def read_file(
    data: bytes, preset: Preset | None = None, answers: Answers | None = None
) -> SourceFile:
    """
    Decode and split an upload (CSV, or ZIP of CSVs) into tables.

    Encoding, delimiter, section and header row come from ``answers`` first,
    then the preset's ``file`` settings, then detection (the header row is the
    one among the first 20 non-blank rows that contains most of the preset's
    candidate headers). Never raises on bad content; an unreadable file gives
    no tables.
    """
    answers = answers or Answers()
    if data[:4] == b"PK\x03\x04":
        return _read_zip(data, preset, answers)
    return _read_text_file(data, "", preset, answers)


def _read_zip(data: bytes, preset: Preset | None, answers: Answers) -> SourceFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > _MAX_UNCOMPRESSED:
            return SourceFile()
        result = SourceFile()
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.name.startswith(".") or "__MACOSX" in path.parts:
                continue
            if path.name.lower() == "datapackage.json":
                result.is_backup = True
            elif path.suffix.lower() == ".csv":
                content = archive.read(info)
                if _read_companion(result, content, path.stem):
                    continue
                member = _read_text_file(content, path.stem, preset, answers)
                result.tables.extend(member.tables)
                for name in member.sections:
                    if name not in result.sections:
                        result.sections.append(name)
        if result.vehicles or result.stations or result.is_backup:
            for table in result.tables:  # "records" is not a vehicle name
                if table.name.casefold() == "records":
                    table.name = ""
        return result
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        return SourceFile()


def _read_companion(result: SourceFile, content: bytes, stem: str) -> bool:
    """
    Take a ZIP member as the vehicles or stations table if it is one. These
    tables have a fixed layout, so they are read without the preset.
    """
    kind = stem.casefold()
    if kind not in ("vehicles", "stations"):
        return False
    tables = _read_text_file(content, stem, None, Answers()).tables
    if not tables:
        return False
    table = tables[0]
    if find_column(["name"], table.headers) is None:
        return False
    if find_column(["date"], table.headers) is not None:
        return False
    setattr(result, kind, table)
    return True


def _decode(data: bytes, encoding: str | None) -> tuple[str, str] | None:
    """Decoded text and the encoding used; ``None`` for an unknown codec."""
    if encoding:
        try:
            text = data.decode(encoding, errors="replace")
        except LookupError:
            return None
        return text.lstrip("\ufeff"), encoding
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def _split_blocks(lines: list[str]) -> list[tuple[str | None, int, list[str]]]:
    """Blocks as (section name, line offset, lines); ``None`` = before any marker."""
    markers = [
        (i, m.group("name")) for i, line in enumerate(lines)
        if (m := _SECTION_RE.match(line))
    ]  # fmt: skip
    if not markers:
        return [(None, 0, lines)]
    blocks = [(None, 0, lines[: markers[0][0]])]
    for n, (index, name) in enumerate(markers):
        end = markers[n + 1][0] if n + 1 < len(markers) else len(lines)
        blocks.append((name, index + 1, lines[index + 1 : end]))
    return blocks


def _read_text_file(
    data: bytes, name: str, preset: Preset | None, answers: Answers
) -> SourceFile:
    settings = preset.file if preset else None
    decoded = _decode(data, answers.encoding or (settings.encoding if settings else None))
    if decoded is None:
        return SourceFile()
    text, encoding = decoded
    lines = text.split("\n")
    blocks = _split_blocks(lines)
    sections = [b[0] for b in blocks if b[0] is not None]
    wanted = settings.section if settings else None
    if wanted:
        chosen = next(
            (b for b in blocks if b[0] and b[0].casefold() == wanted.casefold()), None
        )
    else:
        chosen = next((b for b in blocks if any(x.strip() for x in b[2])), None)
    if chosen is None:
        return SourceFile(sections=sections)
    _, offset, block_lines = chosen
    candidates = _candidates(preset)
    delimiter = answers.delimiter or (settings.delimiter if settings else None)
    forced_header = answers.header_row or (settings.header_row if settings else None)
    head = "\n".join(block_lines[:_DETECT_LINES])
    if delimiter is None:
        delimiter = _pick_delimiter(head, candidates)
    header_index = _pick_header(_parse(head, delimiter)[0], candidates, forced_header)
    rows, _ = _parse("\n".join(block_lines), delimiter, offset)
    if header_index is None or header_index >= len(rows):
        return SourceFile(sections=sections)
    table = SourceTable(
        name=name,
        headers=rows[header_index][1],
        rows=rows[header_index + 1 :],
        encoding=encoding,
        delimiter=delimiter,
        header_row=header_index + 1,
    )
    return SourceFile(tables=[table], sections=sections)


def _candidates(preset: Preset | None) -> list[tuple[str, ...]]:
    if preset is None:
        return []
    return [m.columns for m in preset.fields.values() if m.columns]


def _parse(
    text: str, delimiter: str, offset: int = 0
) -> tuple[list[tuple[int, list[str]]], bool]:
    """Non-blank rows with their file line numbers; ``False`` if the CSV broke."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows: list[tuple[int, list[str]]] = []
    previous = 0
    try:
        for row in reader:
            line = previous + 1 + offset
            previous = reader.line_num
            cells = [c.strip() for c in row]
            if any(cells):
                rows.append((line, cells))
    except csv.Error:
        return rows, False
    return rows, True


def _matches(row: list[str], candidates: list[tuple[str, ...]]) -> int:
    return sum(1 for group in candidates if find_column(group, row) is not None)


def _pick_delimiter(head: str, candidates: list[tuple[str, ...]]) -> str:
    sniffed = sniff_delimiter(head)
    if not candidates:
        return sniffed
    best, best_count = sniffed, -1
    for delimiter in (sniffed, *(d for d in _DELIMITERS if d != sniffed)):
        rows, _ = _parse(head, delimiter)
        count = max((_matches(r, candidates) for _, r in rows[:HEADER_SCAN_ROWS]), default=0)
        if count > best_count:
            best, best_count = delimiter, count
    return best


def _pick_header(
    rows: list[tuple[int, list[str]]],
    candidates: list[tuple[str, ...]],
    forced: int | None,
) -> int | None:
    if not rows:
        return None
    if forced:
        return forced - 1
    best, best_count = 0, 0
    for index, (_, row) in enumerate(rows[:HEADER_SCAN_ROWS]):
        count = _matches(row, candidates)
        if count > best_count:
            best, best_count = index, count
    return best


# --- Scoring ----------------------------------------------------------------


def score(preset: Preset, source: SourceFile) -> float:
    """
    Fraction (0.0-1.0) of the preset's ``column`` fields whose header is found
    in the source; 0.0 if its ``date`` column or its ``section`` is missing.

    The standard preset (id ``glovebox``) is scored by the share of the file's
    headers that are standard field names instead, so that a hand-made file
    with only some of the columns is still recognised.
    """
    wanted = preset.file.section
    if wanted and not any(s.casefold() == wanted.casefold() for s in source.sections):
        return 0.0
    date_mapping = preset.fields.get("date")
    column_fields = {n: m for n, m in preset.fields.items() if m.columns}
    best = 0.0
    for table in source.tables:
        if date_mapping is None:
            continue
        if date_mapping.columns and find_column(date_mapping.columns, table.headers) is None:
            continue
        if preset.id == STANDARD_ID:
            headers = [h for h in table.headers if h.strip()]
            known = sum(1 for h in headers if any(
                match_header(name, h) for name in _FIELDS
            ))  # fmt: skip
            value = known / len(headers) if headers else 0.0
        elif column_fields:
            found = sum(
                1 for m in column_fields.values()
                if find_column(m.columns, table.headers) is not None
            )  # fmt: skip
            value = found / len(column_fields)
        else:
            value = 0.0
        best = max(best, value)
    return best


# --- Applying ---------------------------------------------------------------


class _Bad(Exception):
    """A row fault: target field, raw value and message."""

    def __init__(self, field_name: str, value: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.value = value
        self.message = message


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def apply(
    preset: Preset, source: SourceFile, answers: Answers | None = None
) -> ImportResult:
    """
    Turn the source tables into canonical records with the preset's mapping
    and value formats. Row faults go to ``ImportResult.row_errors``; unmapped
    required fields and unanswered questions block (``errors`` / ``questions``).
    """
    answers = answers or Answers()
    result = ImportResult()
    if not source.tables:
        wanted = preset.file.section
        if wanted:
            result.errors.append(f'The file has no section "## {wanted}".')
        else:
            result.errors.append("The file could not be read as a table.")
        return result
    questions: dict[QuestionKind, Question] = {}
    prefix = len(source.tables) > 1
    for table in source.tables:
        label = f"{table.name}: " if prefix and table.name else ""
        _apply_table(preset, table, answers, result, questions, label)
    result.questions = list(questions.values())
    names: list[str] = []
    for record in [*result.refuels, *result.expenses]:
        if record.vehicle_name and record.vehicle_name not in names:
            names.append(record.vehicle_name)
    result.vehicles = [CanonicalVehicleRef(n) for n in names]
    return result


def _possible_types(mapping: FieldMapping | None) -> set[str] | None:
    """Record types a preset can produce, or ``None`` if only the rows tell."""
    if mapping is None:
        return set()
    if mapping.value is not None:
        return {mapping.value}
    if mapping.map:
        types = set(mapping.map)
        if mapping.default:
            types.add(mapping.default)
        return types
    return None


def _apply_table(
    preset: Preset,
    table: SourceTable,
    answers: Answers,
    result: ImportResult,
    questions: dict[QuestionKind, Question],
    label: str,
) -> None:
    columns = {
        name: find_column(mapping.columns, table.headers)
        for name, mapping in preset.fields.items()
        if mapping.columns
    }

    def mapped(name: str) -> bool:
        mapping = preset.fields.get(name)
        return mapping is not None and (
            mapping.value is not None or columns.get(name) is not None
        )

    problems = _unmapped_required(preset, columns, mapped)
    if problems:
        result.errors.extend(label + p for p in problems)
        return

    skip_columns = [
        (find_column([rule.column], table.headers), {_norm(v) for v in rule.values})
        for rule in preset.skip_rows
    ]
    skip_columns = [(i, v) for i, v in skip_columns if i is not None]

    def column_values(name: str) -> list[str]:
        index = columns.get(name)
        mapping = preset.fields.get(name)
        if index is None or mapping is None:
            return []
        missing = {_norm(v) for v in mapping.missing_values}
        values = []
        for _, row in table.rows:
            if any(_norm(_cell(row, i)) in v for i, v in skip_columns):
                continue
            cell = _cell(row, index)
            if cell and _norm(cell) not in missing:
                values.append(cell)
        return values

    formats = preset.format
    pending = False

    # Units.
    distance = volume = None
    if columns.get("odometer_km") is not None:
        distance, ask = _unit(
            "distance", formats.distance_unit, answers.distance_unit,
            _header(table, columns, "odometer_km"),
        )
        if ask:
            questions.setdefault(
                QuestionKind.DISTANCE_UNIT,
                Question(
                    QuestionKind.DISTANCE_UNIT,
                    "Which unit are the distances in this file?",
                    ("km", "mi"),
                ),
            )
            pending = True
    if columns.get("fuel_l") is not None or columns.get("price_per_l") is not None:
        volume, ask = _unit(
            "volume", formats.volume_unit, answers.volume_unit,
            _header(table, columns, "fuel_l") or _price_header_unit(table, columns),
        )
        if ask:
            questions.setdefault(
                QuestionKind.VOLUME_UNIT,
                Question(
                    QuestionKind.VOLUME_UNIT,
                    "Which unit are the fuel quantities in this file?",
                    ("l", "gal_us", "gal_uk"),
                ),
            )
            pending = True

    # Date order.
    order = None
    if formats.date_format == "auto":
        values = []
        for name in ("date", "coverage_start", "coverage_end"):
            values.extend(column_values(name))
        order, ambiguous = _detect_order(values, answers.date_order)
        if ambiguous:
            questions.setdefault(
                QuestionKind.DATE_ORDER,
                Question(
                    QuestionKind.DATE_ORDER,
                    "Are the dates day first (31/12/2024) or month first (12/31/2024)?",
                    ("dmy", "mdy"),
                ),
            )
            pending = True
    if pending:
        return

    decimals = {
        name: _decimal_char(formats, column_values(name))
        for name in ("odometer_km", "fuel_l", "price_per_l", "total")
        if name in preset.fields
    }
    reader = _RowReader(
        preset=preset,
        columns=columns,
        decimals=decimals,
        order=order,
        distance=distance,
        volume=volume,
        default_vehicle=None if "vehicle" in preset.fields else (table.name or None),
    )
    for line, row in table.rows:
        if any(_norm(_cell(row, i)) in v for i, v in skip_columns):
            result.skipped += 1
            continue
        try:
            record = reader.read(row)
        except _Bad as bad:
            result.row_errors.append(RowError(line, bad.field, bad.value, bad.message))
            continue
        if isinstance(record, CanonicalRefuel):
            result.refuels.append(record)
        else:
            result.expenses.append(record)


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _header(table: SourceTable, columns: dict[str, int | None], name: str) -> str:
    index = columns.get(name)
    return table.headers[index] if index is not None else ""


def _price_header_unit(table: SourceTable, columns: dict[str, int | None]) -> str:
    """A volume unit from the part of a price header after ``/``."""
    header = _header(table, columns, "price_per_l")
    match = _UNIT_RE.search(header)
    if match and "/" in match.group(1):
        return f"({match.group(1).rsplit('/', 1)[1]})"
    return ""


def _unmapped_required(preset: Preset, columns: dict, mapped) -> list[str]:
    def why(name: str) -> str:
        mapping = preset.fields.get(name)
        if mapping is not None and mapping.columns:
            wanted = ", ".join(f"'{c}'" for c in mapping.columns)
            return f"Required field '{name}' is not mapped: no column {wanted} in the file."
        return f"Required field '{name}' is not mapped."

    problems = []
    for name in ("type", "date"):
        if not mapped(name):
            problems.append(why(name))
    if problems:
        return problems
    types = _possible_types(preset.fields.get("type"))
    if types is None:
        return problems  # the rows decide; faults are reported per row
    if REFUEL in types:
        if not mapped("odometer_km"):
            problems.append(why("odometer_km"))
    if EXPENSE in types:
        problems.extend(why(n) for n in ("total", "title") if not mapped(n))
    return problems


def _unit(
    kind: str, setting: str, answer: str | None, header: str
) -> tuple[str | None, bool]:
    """Unit to convert from and whether the preview has to ask."""
    allowed = _KM_PER if kind == "distance" else _LITRES_PER
    if answer in allowed:
        return answer, False
    if setting in allowed:
        return setting, False
    if setting == "auto":
        match = _UNIT_RE.search(header)
        words = _DISTANCE_WORDS if kind == "distance" else _VOLUME_WORDS
        if match and (unit := words.get(_norm(match.group(1)))):
            return unit, False
    return None, True


def _detect_order(values: list[str], requested: str | None) -> tuple[str | None, bool]:
    """
    Date order of a column: ``(order, False)``, or ``(None, True)`` when
    day-first and month-first both fit and the user has not chosen. Values no
    order can read are left out (they become row errors).
    """
    values = [v for v in values if v]
    parseable = [v for v in values if any(parse_date_value(v, o) for o in _ORDERS)]
    if not parseable:
        return None, False
    cover = [o for o in _ORDERS if all(parse_date_value(v, o) for v in parseable)]
    if len(cover) == 1:
        return cover[0], False
    if "ymd" not in cover and len(cover) == 2:
        if requested in cover:
            return requested, False
        return None, True
    if cover:
        return cover[0], False
    fits = {o: sum(1 for v in parseable if parse_date_value(v, o)) for o in _ORDERS}
    return max(_ORDERS, key=fits.__getitem__), False


def _decimal_char(formats: FormatSettings, values: list[str]) -> str:
    if formats.decimal_char in (".", ","):
        return formats.decimal_char
    if formats.group_char == ",":
        return "."
    if formats.group_char == ".":
        return ","
    return detect_decimal_separator(values) if values else "."


def _parse_number(text: str, decimal: str, group: str) -> Decimal:
    """Strict number parsing; raises ``ValueError`` with a user-facing message."""
    cleaned = text.strip()
    if group:
        if group == " ":
            cleaned = re.sub(r"[ \u00a0\u202f]", "", cleaned)
        else:
            cleaned = cleaned.replace(group, "")
    pattern = rf"^[+-]?(\d+({re.escape(decimal)}\d*)?|{re.escape(decimal)}\d+)$"
    if not re.match(pattern, cleaned):
        other = "," if decimal == "." else "."
        hint = ""
        if other in cleaned:
            hint = f" The decimal separator is set to '{decimal}' and no thousands separator is set."
        raise ValueError(f"'{text}' is not a number.{hint}")
    try:
        return Decimal(cleaned.replace(decimal, "."))
    except InvalidOperation:
        raise ValueError(f"'{text}' is not a number.") from None


class _RowReader:
    """Converts the cells of one row into a canonical record."""

    def __init__(
        self,
        *,
        preset: Preset,
        columns: dict[str, int | None],
        decimals: dict[str, str],
        order: str | None,
        distance: str | None,
        volume: str | None,
        default_vehicle: str | None,
    ) -> None:
        self.preset = preset
        self.columns = columns
        self.decimals = decimals
        self.order = order
        self.distance = distance
        self.volume = volume
        self.default_vehicle = default_vehicle
        self.row: list[str] = []

    # -- raw values --

    def _raw(self, name: str) -> str | None:
        """Cell text after missing values; ``None`` if the field is unmapped."""
        mapping = self.preset.fields.get(name)
        if mapping is None:
            return None
        if mapping.value is not None:
            return mapping.value
        cell = _cell(self.row, self.columns.get(name))
        if cell and _norm(cell) in {_norm(v) for v in mapping.missing_values}:
            return ""
        return cell

    def text(self, name: str) -> str | None:
        raw = self._raw(name)
        if raw is None:
            return None
        if raw == "":
            default = self.preset.fields[name].default
            return default or None
        return raw

    def enum(self, name: str) -> str | None:
        mapping = self.preset.fields.get(name)
        raw = self._raw(name)
        if mapping is None or raw is None:
            return _FIELDS[name].default
        if mapping.value is not None:
            return mapping.value
        if raw == "":
            return mapping.default if mapping.default is not None else _FIELDS[name].default
        wanted = _norm(raw)
        if mapping.map:
            for target, sources in mapping.map.items():
                if wanted in {_norm(s) for s in sources}:
                    return target
        else:
            for allowed in _FIELDS[name].enum:
                if _norm(allowed) == wanted:
                    return allowed
        if mapping.default is not None:
            return mapping.default
        options = ", ".join(f"'{o}'" for o in _FIELDS[name].enum)
        raise _Bad(name, raw, f"'{raw}' is not a known value; expected one of {options}.")

    def boolean(self, name: str) -> bool:
        mapping = self.preset.fields.get(name)
        raw = self._raw(name)
        default = _FIELDS[name].default == TRUE_VALUE
        if mapping is None or raw is None:
            return default
        if mapping.value is not None:
            return _norm(raw) in _TRUE_WORDS
        if raw == "":
            if mapping.default is not None:
                return _norm(mapping.default) in _TRUE_WORDS
            return default
        wanted = _norm(raw)
        if mapping.true_values or mapping.false_values:
            if wanted in {_norm(v) for v in mapping.true_values}:
                return True
            if wanted in {_norm(v) for v in mapping.false_values}:
                return False
        elif wanted in _TRUE_WORDS:
            return True
        elif wanted in _FALSE_WORDS:
            return False
        if mapping.default is not None:
            return _norm(mapping.default) in _TRUE_WORDS
        raise _Bad(name, raw, f"'{raw}' is neither a true nor a false value.")

    def number(self, name: str) -> Decimal | None:
        raw = self.text(name)
        if raw is None:
            return None
        format_ = self.preset.format
        try:
            return _parse_number(raw, self.decimals.get(name, "."), format_.group_char)
        except ValueError as error:
            raise _Bad(name, raw, str(error)) from None

    def _datetime(self, name: str, raw: str) -> tuple[date, time | None]:
        pattern = self.preset.format.date_format
        if pattern != "auto":
            try:
                parsed = datetime.strptime(raw, pattern)
            except ValueError:
                raise _Bad(name, raw, f"'{raw}' does not match the date format {pattern}.") from None
            has_time = any(d in pattern for d in ("%H", "%I", "%M", "%T", "%X", "%c"))
            return parsed.date(), (parsed.time() if has_time else None)
        for candidate in ([self.order] if self.order else _ORDERS):
            if (parsed := parse_date_value(raw, candidate)) is not None:
                return parsed
        raise _Bad(name, raw, f"'{raw}' is not a valid date.")

    def date(self, name: str) -> tuple[date, time | None] | None:
        raw = self.text(name)
        if raw is None:
            return None
        return self._datetime(name, raw)

    def time(self) -> time | None:
        raw = self.text("time")
        if raw is None:
            return None
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(raw, pattern).time()
            except ValueError:
                continue
        raise _Bad("time", raw, f"'{raw}' is not a time (HH:MM).")

    # -- records --

    def read(self, row: list[str]) -> CanonicalRefuel | CanonicalExpense:
        self.row = row
        record_type = self.enum("type")
        if record_type not in (REFUEL, EXPENSE):
            raise _Bad("type", self._raw("type") or "", "The record type is missing.")
        parsed = self.date("date")
        if parsed is None:
            raise _Bad("date", "", "The date is missing.")
        day, day_time = parsed
        vehicle = self.text("vehicle") or self.default_vehicle
        notes = self.text("notes")
        source = self.text("source")
        source_ref = self.text("source_ref")
        odometer = self._odometer()
        if record_type == REFUEL:
            return self._refuel(vehicle, day, day_time, odometer, notes, source, source_ref)
        return self._expense(vehicle, day, odometer, notes, source, source_ref)

    def _odometer(self) -> float | None:
        value = self.number("odometer_km")
        if value is None:
            return None
        if value < 0:
            raise _Bad("odometer_km", str(value), "The odometer must not be negative.")
        return float(value * _KM_PER.get(self.distance or "km", Decimal(1)))

    def _refuel(self, vehicle, day, day_time, odometer, notes, source, source_ref):
        if odometer is None:
            raise _Bad("odometer_km", "", "The odometer reading is missing.")
        litres = self.number("fuel_l")
        price = self.number("price_per_l")
        total = self.number("total")
        per_litre = _LITRES_PER.get(self.volume or "l", Decimal(1))
        litres_milli = scale_to_int(litres * per_litre, 1000) if litres is not None else None
        price_milli = scale_to_int(price / per_litre, 1000) if price is not None else None
        total_cents = scale_to_int(total, 100) if total is not None else None
        derived = self.enum("derived")
        return CanonicalRefuel(
            vehicle_name=vehicle,
            date=day,
            odometer_km=odometer,
            litres_milli=litres_milli,
            price_per_litre_milli=price_milli,
            total_cents=total_cents,
            time=self.time() or day_time,
            station_name=self.text("station"),
            station_brand=self.text("station_brand"),
            is_full=self.boolean("full"),
            missed_previous=self.boolean("missed_previous"),
            notes=notes,
            source_ref=source_ref,
            station_location=self.text("station_location"),
            derived=_DERIVED[derived] if derived else None,
            source=source,
        )

    def _expense(self, vehicle, day, odometer, notes, source, source_ref):
        total = self.number("total")
        if total is None:
            raise _Bad("total", "", "The amount is missing.")
        if total <= 0:
            raise _Bad("total", str(total), "The amount must be greater than 0.")
        title = self.text("title")
        if not title:
            raise _Bad("title", "", "The title is missing.")
        start = self.date("coverage_start")
        end = self.date("coverage_end")
        if (start is None) != (end is None):
            missing = "coverage_end" if end is None else "coverage_start"
            raise _Bad(missing, "", "Set both coverage dates or neither.")
        if start and end and end[0] < start[0]:
            raise _Bad("coverage_end", str(end[0]), "The coverage ends before it starts.")
        category = self.enum("category") or "other"
        return CanonicalExpense(
            vehicle_name=vehicle,
            date=day,
            category=ExpenseCategory(category),
            amount_cents=scale_to_int(total, 100),
            title=title,
            odometer_km=odometer,
            coverage_start=start[0] if start else None,
            coverage_end=end[0] if end else None,
            notes=notes,
            source_ref=source_ref,
            source=source,
        )


__all__ = [
    "SourceFile",
    "SourceTable",
    "apply",
    "fallback_preset",
    "find_column",
    "match_header",
    "read_file",
    "score",
    "standard_preset",
]
