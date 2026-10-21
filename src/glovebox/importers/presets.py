"""
Import/export presets (design D4, D10). FROZEN after task group 1.

A preset describes one CSV table: which source column (or constant) feeds
each standard field, plus the value formats. Presets are TOML files; shipped
ones live in ``src/glovebox/presets/*.toml`` (id = file stem), user presets
in the ``preset`` table (id = ``user-<slug>``).

``KEY_TABLE`` is the one list of allowed keys. It drives validation here and
the generated ``docs/user/presets.md``.
"""

from __future__ import annotations

import codecs
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from glovebox import models
from glovebox.services.records import NotFoundError
from glovebox.standard import (
    BOOLEAN,
    ENUM,
    RECORD_FIELDS,
    TRUE_VALUE,
    FALSE_VALUE,
    StandardField,
)

SHIPPED_DIR = Path(__file__).parent.parent / "presets"
USER_PREFIX = "user-"
STANDARD_ID = "glovebox"

AUTO = "auto"
DISTANCE_UNITS = ("km", "mi", "auto", "ask")
VOLUME_UNITS = ("l", "gal_us", "gal_uk", "auto", "ask")
DECIMAL_CHARS = (".", ",", "auto")
GROUP_CHARS = ("", ",", ".", " ", "'")
DELIMITERS = (",", ";", "\t")

TARGET_FIELDS: dict[str, StandardField] = {f.name: f for f in RECORD_FIELDS}


class PresetError(ValueError):
    """A preset is invalid; the message names the key path."""


class PresetNameError(PresetError):
    """The preset name is empty, unusable or already taken."""


@dataclass(frozen=True)
class KeySpec:
    """One allowed preset key, for validation and the generated docs."""

    path: str
    type: str
    description: str
    allowed: str = ""
    default: str = ""


KEY_TABLE: tuple[KeySpec, ...] = (
    KeySpec("name", "string", "Display name; must be unique among all presets."),
    KeySpec("note", "string", "Free text shown in the preview.", default='""'),
    KeySpec(
        "verified", "boolean",
        "True only when the mapping was checked against a real file.",
        default="false",
    ),
    KeySpec("export", "boolean", "Offer the preset on the export page.", default="false"),
    KeySpec(
        "split_by_vehicle", "boolean",
        "Export: one file per vehicle. Import: the file has no vehicle column.",
        default="false",
    ),
    KeySpec(
        "file.encoding", "string",
        "Text encoding. Unset: UTF-8 (BOM accepted), then cp1252.",
        allowed="a Python codec name",
    ),
    KeySpec(
        "file.delimiter", "string", "Field delimiter. Unset: detected.",
        allowed="`,` `;` or a tab (`\\t`)",
    ),
    KeySpec(
        "file.header_row", "integer",
        "Header row, counted over the non-blank rows of the file or section "
        "(1 is the first). Unset: detected.",
        allowed="1 or more",
    ),
    KeySpec(
        "file.section", "string",
        "Read only the lines after `## <section>` (or `# <section>`) up to the next such line.",
    ),
    KeySpec(
        "format.date_format", "string",
        "Date (and time) pattern in strptime syntax, or automatic detection.",
        allowed='`auto` or a pattern containing `%`, e.g. `%d.%m.%Y %H:%M`',
        default='"auto"',
    ),
    KeySpec(
        "format.decimal_char", "string", "Decimal separator.",
        allowed="`.` `,` `auto`", default='"auto"',
    ),
    KeySpec(
        "format.group_char", "string",
        "Thousands separator; empty means none (a number containing one is a row error).",
        allowed='empty, `,` `.` space or `\'`', default='""',
    ),
    KeySpec(
        "format.distance_unit", "string",
        "Unit of distances. `auto` reads it from a parenthesised unit in the header; "
        "`ask` or no unit found: the preview asks.",
        allowed="`km` `mi` `auto` `ask`", default='"auto"',
    ),
    KeySpec(
        "format.volume_unit", "string",
        "Unit of volumes; prices per volume follow it.",
        allowed="`l` `gal_us` `gal_uk` `auto` `ask`", default='"auto"',
    ),
    KeySpec(
        "fields.<field>", "table",
        "Mapping of one standard field. Exactly one of `column` or `value`.",
        allowed="a standard record field name",
    ),
    KeySpec(
        "fields.<field>.column", "string or list of strings",
        "Source header, or candidates tried in order. Case, whitespace and a "
        "trailing `(...)` are ignored when matching.",
    ),
    KeySpec("fields.<field>.value", "string", "Constant used for every row."),
    KeySpec(
        "fields.<field>.map", "table of lists of strings",
        "Target value to list of source values (case- and whitespace-insensitive). "
        "Only for fields with fixed values.",
    ),
    KeySpec(
        "fields.<field>.true_values", "list of strings",
        "Source values meaning true. Only for boolean fields.",
    ),
    KeySpec(
        "fields.<field>.false_values", "list of strings",
        "Source values meaning false. Only for boolean fields.",
    ),
    KeySpec(
        "fields.<field>.missing_values", "list of strings",
        "Source values that count as empty, e.g. `[\"0\"]`.",
    ),
    KeySpec(
        "fields.<field>.default", "string",
        "Used for an empty cell or a value missing from `map` / the boolean lists. "
        "Without it an empty cell takes the field's standard default and an "
        "unlisted value is a row error.",
    ),
    KeySpec(
        "skip_rows[].column", "string",
        "Header of the column checked by one skip rule (`[[skip_rows]]`).",
    ),
    KeySpec(
        "skip_rows[].values", "list of strings",
        "Rows whose cell equals one of these are skipped and counted.",
    ),
)

_TOP_KEYS = {"name", "note", "verified", "export", "split_by_vehicle",
             "file", "format", "fields", "skip_rows"}
_FILE_KEYS = {"encoding", "delimiter", "header_row", "section"}
_FORMAT_KEYS = {"date_format", "decimal_char", "group_char",
                "distance_unit", "volume_unit"}
_FIELD_KEYS = {"column", "value", "map", "true_values", "false_values",
               "missing_values", "default"}


@dataclass(frozen=True)
class FileSettings:
    """``[file]``; ``None`` means detect."""

    encoding: str | None = None
    delimiter: str | None = None
    header_row: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class FormatSettings:
    """``[format]``: value formats of the source file."""

    date_format: str = AUTO
    decimal_char: str = AUTO
    group_char: str = ""
    distance_unit: str = AUTO
    volume_unit: str = AUTO


@dataclass(frozen=True)
class FieldMapping:
    """
    ``[fields.<name>]``. Exactly one of ``columns`` (candidate headers, tried
    in order) and ``value`` (a constant) is set.
    """

    columns: tuple[str, ...] = ()
    value: str | None = None
    map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    true_values: tuple[str, ...] = ()
    false_values: tuple[str, ...] = ()
    missing_values: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True)
class SkipRule:
    """``[[skip_rows]]``."""

    column: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Preset:
    """
    A parsed preset. ``id`` is not part of the TOML text: it is the file stem
    (shipped) or ``user-<slug>`` (user), assigned by the loader.
    ``fields`` keeps the order of the file (the export column order).
    """

    name: str
    id: str = ""
    shipped: bool = False
    note: str = ""
    verified: bool = False
    export: bool = False
    split_by_vehicle: bool = False
    file: FileSettings = field(default_factory=FileSettings)
    format: FormatSettings = field(default_factory=FormatSettings)
    fields: dict[str, FieldMapping] = field(default_factory=dict)
    skip_rows: tuple[SkipRule, ...] = ()


# --- Loading and validation ------------------------------------------------


def load_preset(text: str, *, id: str = "", shipped: bool = False) -> Preset:
    """
    Parse and validate preset TOML.

    Raises
    ------
    PresetError
        Invalid TOML, unknown key, unknown target field or invalid value; the
        message names the key path, e.g. ``fields.litres: not a standard field``.
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise PresetError(f"invalid TOML: {error}") from None
    _check_keys(raw, _TOP_KEYS, "")
    name = _string(raw, "name", "name", required=True).strip()
    if not name:
        raise PresetError("name: must not be empty")
    file_raw = _table(raw, "file")
    _check_keys(file_raw, _FILE_KEYS, "file.")
    format_raw = _table(raw, "format")
    _check_keys(format_raw, _FORMAT_KEYS, "format.")
    fields_raw = _table(raw, "fields")
    skip_raw = raw.get("skip_rows", [])
    if not isinstance(skip_raw, list) or not all(isinstance(r, dict) for r in skip_raw):
        raise PresetError("skip_rows: expected a list of tables ([[skip_rows]])")
    return Preset(
        name=name,
        id=id,
        shipped=shipped,
        note=_string(raw, "note", "note", default=""),
        verified=_bool(raw, "verified", "verified"),
        export=_bool(raw, "export", "export"),
        split_by_vehicle=_bool(raw, "split_by_vehicle", "split_by_vehicle"),
        file=_file_settings(file_raw),
        format=_format_settings(format_raw),
        fields={key: _field_mapping(key, value) for key, value in fields_raw.items()},
        skip_rows=tuple(_skip_rule(i, rule) for i, rule in enumerate(skip_raw)),
    )


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise PresetError(f"{key}: expected a table")
    return value


def _check_keys(raw: dict[str, Any], allowed: set[str], prefix: str) -> None:
    for key in raw:
        if key not in allowed:
            raise PresetError(f"{prefix}{key}: unknown key")


def _string(raw, key, path, *, required=False, default=None, allowed=None):
    if key not in raw:
        if required:
            raise PresetError(f"{path}: required")
        return default
    value = raw[key]
    if not isinstance(value, str):
        raise PresetError(f"{path}: expected a string")
    if allowed is not None and value not in allowed:
        options = ", ".join(repr(a) for a in allowed)
        raise PresetError(f"{path}: expected one of {options}")
    return value


def _bool(raw: dict[str, Any], key: str, path: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise PresetError(f"{path}: expected true or false")
    return value


def _strings(raw: dict[str, Any], key: str, path: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PresetError(f"{path}: expected a list of strings")
    return tuple(value)


def _file_settings(raw: dict[str, Any]) -> FileSettings:
    encoding = _string(raw, "encoding", "file.encoding")
    if encoding is not None:
        try:
            codecs.lookup(encoding)
        except LookupError:
            raise PresetError(f"file.encoding: unknown encoding {encoding!r}") from None
    delimiter = _string(raw, "delimiter", "file.delimiter", allowed=DELIMITERS)
    header_row = raw.get("header_row")
    if header_row is not None and (
        isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1
    ):
        raise PresetError("file.header_row: expected an integer of 1 or more")
    section = _string(raw, "section", "file.section")
    if section is not None and not section.strip():
        raise PresetError("file.section: must not be empty")
    return FileSettings(encoding, delimiter, header_row, section)


def _format_settings(raw: dict[str, Any]) -> FormatSettings:
    date_format = _string(raw, "date_format", "format.date_format", default=AUTO)
    if date_format != AUTO and "%" not in date_format:
        raise PresetError(
            "format.date_format: expected 'auto' or a strptime pattern with '%'"
        )
    return FormatSettings(
        date_format=date_format,
        decimal_char=_string(raw, "decimal_char", "format.decimal_char",
                             default=AUTO, allowed=DECIMAL_CHARS),
        group_char=_string(raw, "group_char", "format.group_char",
                           default="", allowed=GROUP_CHARS),
        distance_unit=_string(raw, "distance_unit", "format.distance_unit",
                              default=AUTO, allowed=DISTANCE_UNITS),
        volume_unit=_string(raw, "volume_unit", "format.volume_unit",
                            default=AUTO, allowed=VOLUME_UNITS),
    )


def _field_mapping(name: str, raw: Any) -> FieldMapping:
    path = f"fields.{name}"
    target = TARGET_FIELDS.get(name)
    if target is None:
        raise PresetError(f"{path}: not a standard field")
    if not isinstance(raw, dict):
        raise PresetError(f"{path}: expected a table")
    _check_keys(raw, _FIELD_KEYS, f"{path}.")
    if ("column" in raw) == ("value" in raw):
        raise PresetError(f"{path}: set exactly one of 'column' or 'value'")
    columns: tuple[str, ...] = ()
    if "column" in raw:
        column = raw["column"]
        columns = (column,) if isinstance(column, str) else tuple(column) if (
            isinstance(column, list)
            and column
            and all(isinstance(c, str) for c in column)
        ) else ()
        if not columns or not all(c.strip() for c in columns):
            raise PresetError(
                f"{path}.column: expected a non-empty string or list of strings"
            )
    value = _string(raw, "value", f"{path}.value")
    default = _string(raw, "default", f"{path}.default")
    true_values = _strings(raw, "true_values", f"{path}.true_values")
    false_values = _strings(raw, "false_values", f"{path}.false_values")
    missing_values = _strings(raw, "missing_values", f"{path}.missing_values")
    mapping = _map(raw, path, target)
    if (true_values or false_values) and target.type != BOOLEAN:
        raise PresetError(f"{path}: true_values/false_values need a boolean field")
    allowed = _allowed_values(target)
    if allowed is not None:
        for key, given in (("value", value), ("default", default)):
            if given is not None and given not in allowed:
                options = ", ".join(repr(a) for a in allowed)
                raise PresetError(f"{path}.{key}: expected one of {options}")
    return FieldMapping(columns, value, mapping, true_values, false_values,
                        missing_values, default)


def _allowed_values(target: StandardField) -> tuple[str, ...] | None:
    if target.type == ENUM:
        return target.enum
    if target.type == BOOLEAN:
        return (TRUE_VALUE, FALSE_VALUE)
    return None


def _map(raw: dict[str, Any], path: str, target: StandardField) -> dict[str, tuple[str, ...]]:
    value = raw.get("map", {})
    if not isinstance(value, dict):
        raise PresetError(f"{path}.map: expected a table of lists of strings")
    if value and target.type != ENUM:
        raise PresetError(f"{path}.map: only fields with fixed values can be mapped")
    result = {}
    for key, sources in value.items():
        if key not in target.enum:
            options = ", ".join(repr(a) for a in target.enum)
            raise PresetError(f"{path}.map.{key}: expected one of {options}")
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            raise PresetError(f"{path}.map.{key}: expected a list of strings")
        result[key] = tuple(sources)
    return result


def _skip_rule(index: int, raw: dict[str, Any]) -> SkipRule:
    path = f"skip_rows[{index}]"
    _check_keys(raw, {"column", "values"}, f"{path}.")
    column = _string(raw, "column", f"{path}.column", required=True)
    if not column.strip():
        raise PresetError(f"{path}.column: must not be empty")
    if "values" not in raw:
        raise PresetError(f"{path}.values: required")
    values = _strings(raw, "values", f"{path}.values")
    if not values:
        raise PresetError(f"{path}.values: expected a non-empty list of strings")
    return SkipRule(column, values)


# --- Writing ---------------------------------------------------------------

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r",
            "\b": "\\b", "\f": "\\f"}


def _q(text: str) -> str:
    """A TOML basic string."""
    out = []
    for char in text:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_q(v) for v in values) + "]"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def write_preset(preset: Preset) -> str:
    """Render ``preset`` as TOML; ``load_preset(write_preset(p))`` equals ``p``."""
    lines = [
        f"name = {_q(preset.name)}",
        f"note = {_q(preset.note)}",
        f"verified = {_bool_text(preset.verified)}",
        f"export = {_bool_text(preset.export)}",
        f"split_by_vehicle = {_bool_text(preset.split_by_vehicle)}",
    ]
    f = preset.file
    file_lines = [
        f"{key} = {_q(value) if isinstance(value, str) else value}"
        for key, value in (("encoding", f.encoding), ("delimiter", f.delimiter),
                           ("header_row", f.header_row), ("section", f.section))
        if value is not None
    ]
    if file_lines:
        lines += ["", "[file]", *file_lines]
    fmt = preset.format
    lines += [
        "", "[format]",
        f"date_format = {_q(fmt.date_format)}",
        f"decimal_char = {_q(fmt.decimal_char)}",
        f"group_char = {_q(fmt.group_char)}",
        f"distance_unit = {_q(fmt.distance_unit)}",
        f"volume_unit = {_q(fmt.volume_unit)}",
        "", "[fields]",
    ]
    for name, mapping in preset.fields.items():
        lines.append(f"{name} = {_field_text(mapping)}")
    for rule in preset.skip_rows:
        lines += ["", "[[skip_rows]]", f"column = {_q(rule.column)}",
                  f"values = {_list(rule.values)}"]
    return "\n".join(lines) + "\n"


def _field_text(mapping: FieldMapping) -> str:
    parts = []
    if mapping.value is not None:
        parts.append(f"value = {_q(mapping.value)}")
    else:
        column = (_q(mapping.columns[0]) if len(mapping.columns) == 1
                  else _list(mapping.columns))
        parts.append(f"column = {column}")
    if mapping.map:
        entries = ", ".join(f"{_q(k)} = {_list(v)}" for k, v in mapping.map.items())
        parts.append(f"map = {{ {entries} }}")
    for key in ("true_values", "false_values", "missing_values"):
        if getattr(mapping, key):
            parts.append(f"{key} = {_list(getattr(mapping, key))}")
    if mapping.default is not None:
        parts.append(f"default = {_q(mapping.default)}")
    return "{ " + ", ".join(parts) + " }"


# --- Shipped and user presets ----------------------------------------------


def shipped_presets() -> list[Preset]:
    """
    Presets from ``src/glovebox/presets/*.toml``: ``glovebox`` first, then by id.

    Raises ``PresetError`` (naming the file) if a shipped file is invalid.
    """
    if not SHIPPED_DIR.is_dir():
        return []
    presets = []
    for path in SHIPPED_DIR.glob("*.toml"):
        try:
            presets.append(load_preset(path.read_text(encoding="utf-8"),
                                       id=path.stem, shipped=True))
        except PresetError as error:
            raise PresetError(f"{path.name}: {error}") from None
    return sorted(presets, key=lambda p: (p.id != STANDARD_ID, p.id))


def slugify(name: str) -> str:
    """Lower-case letters and digits joined by single hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:90]


def _user_preset(row: models.Preset) -> Preset:
    preset = load_preset(row.body, id=USER_PREFIX + row.slug)
    return preset


def list_presets(session: Session) -> list[Preset]:
    """User presets (by name) first, then the shipped ones."""
    rows = session.scalars(select(models.Preset)).all()
    users = sorted((_user_preset(r) for r in rows), key=lambda p: p.name.casefold())
    return [*users, *shipped_presets()]


def get_preset(session: Session, preset_id: str) -> Preset:
    """The preset with this id; ``NotFoundError`` if there is none."""
    if preset_id.startswith(USER_PREFIX):
        row = session.scalar(
            select(models.Preset).where(models.Preset.slug == preset_id[len(USER_PREFIX):])
        )
        if row is not None:
            return _user_preset(row)
    else:
        for preset in shipped_presets():
            if preset.id == preset_id:
                return preset
    raise NotFoundError(f"Preset {preset_id!r} not found")


def save_user_preset(
    session: Session, preset: Preset, *, replace_id: str | None = None
) -> Preset:
    """
    Store ``preset`` as a user preset and return it with its id.

    Without ``replace_id`` a new preset is created with id ``user-<slug of
    name>``. With the id of an existing user preset, that preset is updated
    in place (its id never changes, even if the name does).

    Raises
    ------
    PresetNameError
        Name empty or without letters/digits, or equal (ignoring case) to
        another preset's name, or its slug already taken.
    PresetError
        ``replace_id`` names a shipped preset (shipped presets are not
        writable; save a copy instead).
    NotFoundError
        ``replace_id`` names no user preset.

    The caller commits.
    """
    name = preset.name.strip()
    slug = slugify(name)
    if not slug:
        raise PresetNameError("name: must contain letters or digits")
    if len(name) > 100:
        raise PresetNameError("name: at most 100 characters")
    row = None
    if replace_id is not None:
        if not replace_id.startswith(USER_PREFIX):
            raise PresetError(f"Shipped preset {replace_id!r} cannot be changed")
        row = session.scalar(
            select(models.Preset).where(models.Preset.slug == replace_id[len(USER_PREFIX):])
        )
        if row is None:
            raise NotFoundError(f"Preset {replace_id!r} not found")
    own_id = USER_PREFIX + row.slug if row else None
    for other in list_presets(session):
        if other.id == own_id:
            continue
        if other.name.casefold() == name.casefold() or (
            row is None and other.id == USER_PREFIX + slug
        ):
            raise PresetNameError(f"name: a preset named {other.name!r} already exists")
    stored_slug = row.slug if row else slug
    saved = replace(preset, name=name, id=USER_PREFIX + stored_slug, shipped=False)
    body = write_preset(saved)
    if row is None:
        session.add(models.Preset(slug=stored_slug, name=name, body=body))
    else:
        row.name, row.body = name, body
    session.flush()
    return saved


def delete_user_preset(session: Session, preset_id: str) -> None:
    """
    Delete a user preset. ``PresetError`` for a shipped one, ``NotFoundError``
    if it does not exist. The caller commits.
    """
    if not preset_id.startswith(USER_PREFIX):
        raise PresetError(f"Shipped preset {preset_id!r} cannot be deleted")
    row = session.scalar(
        select(models.Preset).where(models.Preset.slug == preset_id[len(USER_PREFIX):])
    )
    if row is None:
        raise NotFoundError(f"Preset {preset_id!r} not found")
    session.delete(row)
    session.flush()
