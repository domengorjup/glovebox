"""
Import pages: upload, column mapping, preview, confirm, batch list, undo.

The edited mapping travels between the steps as form fields: the preset it
started from (``base_toml``, ``selected_preset``, ``preset_id``) plus the per-field inputs of the
mapping page. Preview and confirm carry only ``base_toml``, which then holds
the edited mapping.
"""

from __future__ import annotations

import csv
import io
import re
import time as time_module
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from glovebox.importers import engine, pipeline
from glovebox.importers.engine import find_column, match_header
from glovebox.importers.base import Answers
from glovebox.importers.pipeline import (
    CHOOSE_VEHICLE_MESSAGE, NEW_VEHICLE_NAME_MESSAGE, NOTHING_NEW_MESSAGE, VehicleMapping,
)
from glovebox.models import ImportBatch
from glovebox.importers.presets import (
    FieldMapping,
    FileSettings,
    FormatSettings,
    Preset,
    PresetError,
    get_preset,
    list_presets,
    load_preset,
    save_user_preset,
    write_preset,
)
from glovebox.services import records
from glovebox.services.records import NotFoundError, RecordsError
from glovebox.web.reminders import sync_after_save
from glovebox.standard import BOOLEAN, ENUM, RECORD_FIELDS, StandardField
from glovebox.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/import")

UPLOAD_MAX_AGE_SECONDS = 24 * 3600
PREVIEW_ERROR_LIMIT = 50
_TOKEN = re.compile(r"^[0-9a-f]{32}$")

CONSTANT = "="  # value of a source select: "use a constant"
KEEP = "keep"  # value of a source select: keep the preset's column that the file lacks
COL = "col:"  # prefix of a source select value: a header of the file

ENCODINGS = (("utf-8", "UTF-8"), ("cp1252", "Windows-1252"))
DELIMITERS = ((",", "Comma"), (";", "Semicolon"), ("\t", "Tab"))
DECIMALS = (("auto", "Detect"), (".", "Dot"), (",", "Comma"))
GROUPS = (("", "None"), (",", "Comma"), (".", "Dot"), (" ", "Space"), ("'", "Apostrophe"))
DISTANCES = (("auto", "From the header"), ("km", "Kilometres"), ("mi", "Miles"),
             ("ask", "Ask in the preview"))
VOLUMES = (("auto", "From the header"), ("l", "Litres"), ("gal_us", "US gallons"),
           ("gal_uk", "UK gallons"), ("ask", "Ask in the preview"))
ANSWER_LABELS = {
    "dmy": "Day first (31/12/2025)", "mdy": "Month first (12/31/2025)",
    "km": "Kilometres", "mi": "Miles",
    "l": "Litres", "gal_us": "US gallons", "gal_uk": "UK gallons",
}
# Human labels of the standard fields for the mapping page; the key follows as small text.
FIELD_LABELS = {
    "type": "Record type", "date": "Date", "time": "Time", "vehicle": "Vehicle",
    "odometer_km": "Odometer", "fuel_l": "Fuel quantity", "price_per_l": "Price per litre",
    "total": "Total price", "full": "Full tank", "missed_previous": "Missed fill-up before",
    "station": "Gas station", "category": "Category", "title": "Title", "notes": "Notes",
    "currency": "Currency", "station_location": "Station location",
    "station_brand": "Station brand", "coverage_start": "Coverage start",
    "coverage_end": "Coverage end", "derived": "Derived figure",
    "odometer_estimated": "Odometer is estimated", "source": "Source",
    "source_ref": "Source reference",
}
ANSWER_KEYS = ("date_order", "distance_unit", "volume_unit")


# --- Stored uploads ----------------------------------------------------------


def _upload_dir(request: Request) -> Path:
    return request.app.state.settings.data_dir / "uploads"


def _upload_path(request: Request, token: str) -> Path:
    """Path of a stored upload; the token must be one we generated."""
    if not _TOKEN.match(token):
        raise HTTPException(404, detail="Unknown upload")
    path = _upload_dir(request) / f"{token}.upload"
    if not path.is_file():
        raise HTTPException(404, detail="Upload expired; please upload the file again")
    return path


def _remove_old_uploads(directory: Path) -> None:
    """Drop abandoned uploads (a preview that was never confirmed)."""
    cutoff = time_module.time() - UPLOAD_MAX_AGE_SECONDS
    for old in directory.glob("*.upload"):
        if old.stat().st_mtime < cutoff:
            old.unlink()


# --- Reading the mapping from the form ---------------------------------------


def _split_list(text: str) -> tuple[str, ...]:
    """Comma-separated values; quotes keep a comma inside a value."""
    row = next(csv.reader(io.StringIO(text.strip()), skipinitialspace=True), [])
    return tuple(v.strip() for v in row if v.strip())


def _join_list(values: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()


def _map_text(mapping: dict[str, tuple[str, ...]]) -> str:
    return "\n".join(f"{target} = {_join_list(values)}" for target, values in mapping.items())


def _parse_map(text: str, field: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        target, sign, values = line.partition("=")
        if not sign or not target.strip():
            raise PresetError(
                f"fields.{field}.map: expected lines like 'target = value, value', got {line!r}"
            )
        result[target.strip()] = _split_list(values)
    return result


def _field_from_form(
    form: FormData, target: StandardField, base: FieldMapping | None
) -> FieldMapping | None:
    name = target.name
    source = str(form.get(f"src.{name}", ""))
    if not source:
        return None
    options = dict(
        map=_parse_map(str(form.get(f"map.{name}", "")), name) if target.type == ENUM else {},
        true_values=_split_list(str(form.get(f"true.{name}", ""))) if target.type == BOOLEAN else (),
        false_values=_split_list(str(form.get(f"false.{name}", ""))) if target.type == BOOLEAN else (),
        missing_values=_split_list(str(form.get(f"missing.{name}", ""))),
        default=str(form.get(f"default.{name}", "")) or None,
    )
    if source == CONSTANT:
        value = str(form.get(f"val.{name}", ""))
        return FieldMapping(value=value, **options) if value else None
    if source == KEEP and base is not None and base.columns:
        return FieldMapping(columns=base.columns, **options)
    header = source.removeprefix(COL)
    # Keep the preset's alternative headers when the user left its choice alone.
    if base is not None and any(match_header(c, header) for c in base.columns):
        return FieldMapping(columns=base.columns, **options)
    return FieldMapping(columns=(header,), **options)


def _clean(form: FormData, key: str) -> str | None:
    value = str(form.get(key, "")).strip()
    return value or None


def preset_from_form(form: FormData, base: Preset) -> Preset:
    """
    The preset described by the mapping form, validated.

    Name, note, flags and skip rules come from ``base``. Raises ``PresetError``
    (naming the key) for an invalid entry.
    """
    fields: dict[str, FieldMapping] = {}
    order = [*base.fields, *(t.name for t in RECORD_FIELDS if t.name not in base.fields)]
    targets = {t.name: t for t in RECORD_FIELDS}
    for name in order:
        mapping = _field_from_form(form, targets[name], base.fields.get(name))
        if mapping is not None:
            fields[name] = mapping
    header_row = _clean(form, "header_row")
    if header_row is not None and not header_row.isdigit():
        raise PresetError("file.header_row: expected an integer of 1 or more")
    file = FileSettings(
        encoding=_clean(form, "encoding"),
        delimiter=str(form.get("delimiter", "")) or None,
        header_row=int(header_row) if header_row else None,
        section=_clean(form, "section"),
    )
    fmt = FormatSettings(
        date_format=_clean(form, "date_format") or "auto",
        decimal_char=str(form.get("decimal_char", "auto")),
        group_char=str(form.get("group_char", "")),
        distance_unit=str(form.get("distance_unit", "auto")),
        volume_unit=str(form.get("volume_unit", "auto")),
    )
    edited = load_preset(
        write_preset(replace(base, fields=fields, file=file, format=fmt)), id=base.id
    )
    # A changed mapping is no longer the stored preset: the batch says "custom".
    return edited if edited == base else replace(edited, id="")


# --- Submitted state ---------------------------------------------------------

NEW_VEHICLE = "new"  # value of the vehicle select: create a vehicle at commit


@dataclass(frozen=True)
class Carry:
    """What a multi-section import carries from one section to the next."""

    default_vehicle: str = ""  # vehicle id, or NEW_VEHICLE
    new_vehicle: str = ""  # name for NEW_VEHICLE
    seen: tuple[str, ...] = ()  # sections already imported from this upload


def _carry(form: FormData) -> Carry:
    return Carry(
        default_vehicle=str(form.get("default_vehicle", "")),
        new_vehicle=str(form.get("new_vehicle_name", "")),
        seen=tuple(str(v) for v in form.getlist("seen")),
    )


@dataclass
class Submitted:
    """Everything the import steps carry in the form."""

    token: str
    filename: str
    preset: Preset
    answers: Answers
    names: list[str]
    maps: list[str]
    default_vehicle: str
    selected: str = ""  # id of the preset picked in the mapping step
    new_vehicle: str = ""  # name typed for the "New vehicle..." choice
    seen: tuple[str, ...] = ()

    @property
    def carry(self) -> Carry:
        return Carry(self.default_vehicle, self.new_vehicle, self.seen)

    @property
    def mapping(self) -> VehicleMapping:
        by_name: dict[str, int | None] = {}
        for name, target in zip(self.names, self.maps):
            by_name[name] = int(target) if target.isdigit() else None
        default = int(self.default_vehicle) if self.default_vehicle.isdigit() else None
        new_name = self.new_vehicle if self.default_vehicle == NEW_VEHICLE else None
        return VehicleMapping(
            by_name=by_name, default_vehicle_id=default, default_new_name=new_name
        )


def _answers(form: FormData) -> Answers:
    values = {key: str(form.get(f"ans_{key}", "")) or None for key in ANSWER_KEYS}
    return Answers(**values)


def _base_preset(form: FormData) -> Preset:
    text = str(form.get("base_toml", ""))
    if not text:
        raise HTTPException(422, detail="The mapping is missing; please start again")
    try:
        return load_preset(text, id=str(form.get("preset_id", "")))
    except PresetError as exc:
        raise HTTPException(422, detail=f"The mapping is invalid: {exc}") from None


def _submitted(request: Request, form: FormData) -> Submitted:
    """Read the state of a preview, commit or save request."""
    token = str(form.get("token", ""))
    _upload_path(request, token)
    base = _base_preset(form)
    preset = preset_from_form(form, base) if form.get("edited") else base
    carry = _carry(form)
    return Submitted(
        token=token,
        filename=str(form.get("filename", "")) or "upload",
        preset=preset,
        answers=_answers(form),
        names=[str(v) for v in form.getlist("names")],
        maps=[str(v) for v in form.getlist("maps")],
        default_vehicle=str(form.get("default_vehicle", "")),
        selected=str(form.get("selected_preset", "")),
        new_vehicle=carry.new_vehicle,
        seen=carry.seen,
    )


# --- Pages -------------------------------------------------------------------


def _preset_names(session: Session) -> dict[str, str]:
    return {p.id: p.name for p in list_presets(session)}


@router.get("")
def import_home(
    request: Request, session: SessionDep, more: Annotated[list[str], Query()] = [],
    done: int | None = None, token: str = "", filename: str = "upload",
    vehicle: str = "", seen: Annotated[list[str], Query()] = [],
):
    """
    Upload form, the list of past import batches and, after a commit, its result.

    ``more`` lists the sections of the stored upload ``token`` that are still to
    import; the first one is offered as "Import next section".
    """
    sections = [m for m in more if m.strip()]
    next_url = None
    if sections and _TOKEN.match(token) and (_upload_dir(request) / f"{token}.upload").is_file():
        query = [("token", token), ("filename", filename), ("section", sections[0]),
                 ("vehicle", vehicle), *[("seen", s) for s in seen]]
        next_url = f"/import/preview?{urlencode(query)}"
    return render(
        request,
        "import/index.html",
        batches=pipeline.list_batches(session),
        preset_names=_preset_names(session),
        more_sections=sections,
        next_url=next_url,
        done=session.get(ImportBatch, done) if done is not None else None,
        errors=[],
    )


@router.post("/upload")
def import_upload(request: Request, file: Annotated[UploadFile, File()]):
    """Store the file temporarily and go to its review (nothing is imported)."""
    directory = _upload_dir(request)
    directory.mkdir(parents=True, exist_ok=True)
    _remove_old_uploads(directory)
    token = uuid.uuid4().hex
    data = file.file.read()
    (directory / f"{token}.upload").write_bytes(data)
    query = urlencode({"token": token, "filename": file.filename or "upload"})
    # The review page sends the file on to the mapping if no preset fits.
    return redirect(request, f"/import/preview?{query}")


def _detected_preset(session: Session, data: bytes) -> Preset:
    """The best preset for the file, or the standard names that the file has."""
    return pipeline.detect_preset(session, data) or engine.fallback_preset(engine.read_file(data))


def _field_rows(preset: Preset, headers: list[str]) -> list[dict]:
    """One dict per standard field for the mapping template."""
    rows = []
    for target in RECORD_FIELDS:
        mapping = preset.fields.get(target.name)
        source, constant, missing_column = "", "", ""
        if mapping is not None and mapping.value is not None:
            source, constant = CONSTANT, mapping.value
        elif mapping is not None:
            found = find_column(mapping.columns, headers)
            if found is not None:
                source = COL + headers[found]
            else:
                source, missing_column = KEEP, mapping.columns[0]
        rows.append({
            "name": target.name,
            "label": FIELD_LABELS.get(target.name, target.name),
            "shown": bool(source or _required_text(target) or mapping and (
                mapping.map or mapping.true_values or mapping.false_values
                or mapping.missing_values or mapping.default)),
            "description": target.description,
            "type": target.type,
            "enum": target.enum if target.type == ENUM else (),
            "is_boolean": target.type == BOOLEAN,
            "required": _required_text(target),
            "source": source,
            "constant": constant,
            "missing_column": missing_column,
            "map": _map_text(mapping.map) if mapping else "",
            "true_values": _join_list(mapping.true_values) if mapping else "",
            "false_values": _join_list(mapping.false_values) if mapping else "",
            "missing_values": _join_list(mapping.missing_values) if mapping else "",
            "default": (mapping.default or "") if mapping else "",
            "has_options": bool(mapping and (
                mapping.map or mapping.true_values or mapping.false_values
                or mapping.missing_values or mapping.default)),
        })
    return rows


def _required_text(target: StandardField) -> str:
    if target.name in ("type", "date"):
        return "Required"
    if target.name == "odometer_km":
        return "Required for refuels"
    if target.name in ("total", "title"):
        return "Required for expenses"
    return ""


def _unmapped_required(preset: Preset) -> list[str]:
    missing = [n for n in ("type", "date") if n not in preset.fields]
    kind = preset.fields.get("type")
    if kind is not None and kind.value == "refuel" and "odometer_km" not in preset.fields:
        missing.append("odometer_km")
    if kind is not None and kind.value == "expense":
        missing += [n for n in ("total", "title") if n not in preset.fields]
    return missing


def _mapping_page(
    request: Request, session: Session, token: str, filename: str, preset: Preset,
    selected: str, carry: Carry, status: int = 200, errors: list[str] | None = None,
):
    """Render the mapping step for the stored upload."""
    data = _upload_path(request, token).read_bytes()
    source = engine.read_file(data, preset)
    table = source.tables[0] if source.tables else None
    headers = table.headers if table else []
    all_errors = list(errors or [])
    if table is None:
        all_errors.append("The file could not be read as CSV.")
    sections = list(source.sections)
    if preset.file.section and preset.file.section not in sections:
        sections.append(preset.file.section)
    unmapped = _unmapped_required(preset)
    warnings = []
    if table is not None and unmapped:
        warnings.append("Map the required fields before the preview: " + ", ".join(unmapped) + ".")
    if table is not None:
        warnings += _preview_problems(session, data, preset, bool(unmapped))
    if not selected and table is not None:
        warnings.insert(0, "No preset fits this file: map its columns below.")
    rows = _field_rows(preset, headers)
    explicit = any((preset.file.encoding, preset.file.delimiter, preset.file.header_row))
    return render(
        request,
        "import/mapping.html",
        status,
        token=token,
        filename=filename,
        preset=preset,
        selected=selected,
        carry=carry,
        file_summary=_file_summary(table, preset),
        formats_summary=_formats_summary(preset),
        file_open=table is None or explicit or bool(all_errors),
        presets=list_presets(session),
        base_toml=write_preset(preset),
        table=table,
        table_count=len(source.tables),
        headers=headers,
        sections=sections,
        rows=rows,
        encodings=ENCODINGS, delimiters=DELIMITERS, decimals=DECIMALS, groups=GROUPS,
        distances=DISTANCES, volumes=VOLUMES,
        errors=all_errors,
        warnings=warnings,
    )


def _preview_problems(
    session: Session, data: bytes, preset: Preset, skip_errors: bool
) -> list[str]:
    """What is wrong when the file is read with this mapping (for the mapping page)."""
    preview = pipeline.preview_import(session, data, preset=preset)
    own = (CHOOSE_VEHICLE_MESSAGE, NEW_VEHICLE_NAME_MESSAGE)
    problems = [] if skip_errors else [e for e in preview.errors if e not in own]
    if preview.row_errors:
        first = preview.row_errors[0]
        problems.append(
            f"{len(preview.row_errors)} rows have errors with this mapping, e.g. line "
            f"{first.line}: {first.field}: {first.message}"
        )
    return problems


def _file_summary(table, preset: Preset) -> str:
    """One line for the folded File block: what was detected or set."""
    if table is None:
        return "Could not be read"
    delimiter = {"\t": "tab", ",": "comma", ";": "semicolon"}.get(table.delimiter, table.delimiter)
    parts = [table.encoding.upper(), delimiter, f"header row {table.header_row}"]
    if preset.file.section:
        parts.append(f"section {preset.file.section}")
    return " · ".join(parts)


def _formats_summary(preset: Preset) -> str:
    """One line for the folded Value formats block."""
    fmt = preset.format
    decimal = dict(DECIMALS)[fmt.decimal_char].lower() if fmt.decimal_char in dict(DECIMALS) else fmt.decimal_char
    parts = ["dates " + ("auto" if fmt.date_format == "auto" else fmt.date_format),
             f"decimal {decimal}"]
    if fmt.distance_unit == fmt.volume_unit == "auto":
        parts.append("units from header")
    else:
        parts += [dict(DISTANCES)[fmt.distance_unit].lower(), dict(VOLUMES)[fmt.volume_unit].lower()]
    return " · ".join(parts)


@router.get("/mapping")
def mapping_get(
    request: Request, session: SessionDep, token: str, filename: str = "upload",
    preset: str = "", section: str = "", vehicle: str = "",
    seen: Annotated[list[str], Query()] = [],
):
    """
    Mapping step: the detected (or chosen) preset, ready to adjust.

    ``section`` (the "next section" step) detects the preset among those that
    read that section; ``vehicle`` and ``seen`` carry the previous section's
    choices.
    """
    data = _upload_path(request, token).read_bytes()
    try:
        if preset:
            chosen = get_preset(session, preset)
        elif section:
            chosen = _section_preset(session, data, section)
        else:
            chosen = _detected_preset(session, data)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    carry = Carry(default_vehicle=vehicle, seen=tuple(seen))
    return _mapping_page(request, session, token, filename, chosen, chosen.id, carry)


def _section_preset(session: Session, data: bytes, section: str) -> Preset:
    """Best preset for one section of the file, else the file's own names."""
    found = pipeline.detect_preset(session, data, section)
    if found is not None:
        return found
    fallback = engine.fallback_preset(engine.read_file(data))
    return replace(fallback, file=replace(fallback.file, section=section))


@router.post("/mapping")
async def mapping_post(request: Request, session: SessionDep):
    """Re-render the mapping with the edits applied, or with another preset."""
    form = await request.form()
    token = str(form.get("token", ""))
    filename = str(form.get("filename", "")) or "upload"
    _upload_path(request, token)
    base = _base_preset(form)
    carry = _carry(form)
    selected = str(form.get("selected_preset", ""))
    chosen = str(form.get("preset", "")) or selected
    if chosen != selected:
        try:
            preset = get_preset(session, chosen)
        except NotFoundError as exc:
            raise HTTPException(404, detail=str(exc)) from None
        return _mapping_page(request, session, token, filename, preset, chosen, carry)
    if not form.get("edited"):
        return _mapping_page(request, session, token, filename, base, selected, carry)
    try:
        preset = preset_from_form(form, base)
    except PresetError as exc:
        return _mapping_page(request, session, token, filename, base, selected, carry, 422, [str(exc)])
    return _mapping_page(request, session, token, filename, preset, selected, carry)


def _preview_page(
    request: Request, session: Session, sub: Submitted, status: int = 200,
    errors: list[str] | None = None, notes: list[str] | None = None,
):
    """Render the preview for the stored upload."""
    data = _upload_path(request, sub.token).read_bytes()
    preview = pipeline.preview_import(
        session, data, preset=sub.preset, answers=sub.answers, mapping=sub.mapping
    )
    vehicles = records.list_vehicles(session)
    chosen = dict(zip(sub.names, sub.maps))
    selection = {}
    for name in preview.vehicle_names:
        by_name = next((v for v in vehicles if v.name.lower() == name.lower()), None)
        default = str(by_name.id) if by_name else "new"
        selection[name] = chosen.get(name, default) or "new"
    row_errors = list(preview.row_errors)
    questions = list(preview.questions)
    # "Which vehicle?" is a question for the picker, not a failure of the file.
    shown_errors = [
        e for e in [*(errors or []), *preview.errors] if e != CHOOSE_VEHICLE_MESSAGE
    ]
    warnings = list(preview.warnings)
    nothing_new = (
        preview.nothing_new and not shown_errors and not questions
        and not preview.needs_vehicle_choice
    )
    if nothing_new:
        warnings.insert(0, NOTHING_NEW_MESSAGE)
    notes = list(notes or [])
    if preview.preset_note and not preview.is_backup:
        (notes if sub.preset.verified else warnings).insert(0, preview.preset_note)
    answers = {key: getattr(sub.answers, key) or "" for key in ANSWER_KEYS}
    return render(
        request,
        "import/preview.html",
        status,
        sub=sub,
        preset=sub.preset,
        base_toml=write_preset(sub.preset),
        preview=preview,
        vehicles=vehicles,
        presets=list_presets(session),
        selection=selection,
        vehicle_choice=sub.default_vehicle or (NEW_VEHICLE if not vehicles else ""),
        blocked=bool(preview.errors or questions),
        nothing_new=nothing_new,
        questions=_question_rows(questions, answers),
        row_errors=row_errors[:PREVIEW_ERROR_LIMIT],
        row_error_total=len(row_errors),
        skipped=preview.skipped,
        errors=shown_errors,
        warnings=warnings,
        notes=notes,
    )


def _question_rows(questions: list, answers: dict[str, str]) -> list[dict]:
    """Pending questions, then the answered ones (so they can be changed)."""
    rows = []
    pending = set()
    for q in questions:
        kind = q.kind.value
        pending.add(kind)
        rows.append({"kind": kind, "message": q.message, "answer": "",
                     "options": [(o, ANSWER_LABELS.get(o, o)) for o in q.options]})
    for kind in ANSWER_KEYS:
        if kind not in pending and answers.get(kind):
            options = {
                "date_order": ("dmy", "mdy"), "distance_unit": ("km", "mi"),
                "volume_unit": ("l", "gal_us", "gal_uk"),
            }[kind]
            message = {"date_order": "Which order do the dates use?",
                       "distance_unit": "Which unit are distances in?",
                       "volume_unit": "Which unit are volumes in?"}[kind]
            rows.append({"kind": kind, "message": message, "answer": answers[kind],
                         "options": [(o, ANSWER_LABELS[o]) for o in options]})
    return rows


def _preset_failed(preview: pipeline.ImportPreview) -> bool:
    """True if the preset does not read the file well: errors or rows with errors."""
    own = (CHOOSE_VEHICLE_MESSAGE, NEW_VEHICLE_NAME_MESSAGE)
    return bool(preview.row_errors or [e for e in preview.errors if e not in own])


@router.get("/preview")
def import_preview(
    request: Request, session: SessionDep, token: str, filename: str = "upload",
    preset: str = "", section: str = "", vehicle: str = "",
    seen: Annotated[list[str], Query()] = [],
):
    """
    Review of the stored upload with the detected (or chosen) preset: the page
    where the import is confirmed. A file that no preset fits, or that the preset
    reads with errors, goes to the mapping instead.
    """
    data = _upload_path(request, token).read_bytes()
    to_mapping = redirect(request, "/import/mapping?" + urlencode(
        [("token", token), ("filename", filename), ("preset", preset), ("section", section),
         ("vehicle", vehicle), *[("seen", v) for v in seen]]))
    try:
        if preset:
            chosen = get_preset(session, preset)
        else:
            chosen = pipeline.detect_preset(session, data, section or None)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    if chosen is None:
        return to_mapping
    sub = Submitted(token, filename, chosen, Answers(), [], [], vehicle, chosen.id,
                    seen=tuple(seen))
    if not engine.read_file(data).is_backup and _preset_failed(
        pipeline.preview_import(session, data, preset=chosen, mapping=sub.mapping)
    ):
        return to_mapping
    return _preview_page(request, session, sub)


@router.post("/preview")
async def import_preview_post(request: Request, session: SessionDep):
    """Preview of the mapping from the form; changes no data."""
    form = await request.form()
    picked = str(form.get("preset", ""))
    if picked and picked != form.get("selected_preset") and form.get("edited"):
        return await mapping_post(request, session)  # the mapping page's own select
    try:
        sub = _submitted(request, form)
    except PresetError as exc:
        return _mapping_from_error(request, session, form, exc)
    if picked and picked != sub.selected:  # another preset was picked on the review
        try:
            sub.preset = get_preset(session, picked)
        except NotFoundError as exc:
            raise HTTPException(404, detail=str(exc)) from None
        sub.selected = picked
    return _preview_page(request, session, sub)


def _mapping_from_error(request: Request, session: Session, form: FormData, exc: Exception):
    base = _base_preset(form)
    return _mapping_page(
        request, session, str(form.get("token", "")), str(form.get("filename", "")) or "upload",
        base, str(form.get("selected_preset", "")), _carry(form), 422, [str(exc)],
    )


@router.post("/commit")
async def import_commit(request: Request, session: SessionDep):
    """Write the previewed records in one batch."""
    form = await request.form()
    try:
        sub = _submitted(request, form)
    except PresetError as exc:
        return _mapping_from_error(request, session, form, exc)
    path = _upload_path(request, sub.token)
    data = path.read_bytes()
    try:
        batch = pipeline.commit_import(
            session, data, sub.filename, sub.mapping, preset=sub.preset, answers=sub.answers
        )
    except (ValueError, RecordsError) as exc:
        session.rollback()
        return _preview_page(request, session, sub, 422, [str(exc)])
    sync_after_save(request)  # imported open reminders go to the calendar
    seen = (*sub.seen, *([sub.preset.file.section] if sub.preset.file.section else []))
    remaining = _remaining_sections(data, sub.preset, seen)
    query = [("done", batch.id)]
    if remaining:  # keep the upload for "Import next section"
        query += [("token", sub.token), ("filename", sub.filename),
                  ("vehicle", _used_vehicle(session, sub))]
        query += [("seen", s) for s in seen] + [("more", s) for s in remaining]
    else:
        path.unlink(missing_ok=True)
    return redirect(request, f"/import?{urlencode(query)}")


def _remaining_sections(data: bytes, preset: Preset, seen: tuple[str, ...]) -> list[str]:
    """Sections of the file that no import of this upload has read yet."""
    if not preset.file.section:
        return []
    done = {s.casefold() for s in seen}
    return [s for s in engine.read_file(data, preset).sections if s.casefold() not in done]


def _used_vehicle(session: Session, sub: Submitted) -> str:
    """Id of the vehicle chosen for the records without a vehicle name, if any."""
    if sub.default_vehicle.isdigit():
        return sub.default_vehicle
    if sub.default_vehicle == NEW_VEHICLE:
        vehicle = next(
            (v for v in records.list_vehicles(session) if v.name == sub.new_vehicle.strip()),
            None,
        )
        return str(vehicle.id) if vehicle else ""
    return ""


@router.post("/save-preset")
async def import_save_preset(request: Request, session: SessionDep):
    """Store the current mapping as an own preset, then show the preview again."""
    form = await request.form()
    try:
        sub = _submitted(request, form)
    except PresetError as exc:
        return _mapping_from_error(request, session, form, exc)
    name = str(form.get("preset_name", "")).strip()
    try:
        saved = save_user_preset(session, replace(sub.preset, name=name))
        session.commit()
    except PresetError as exc:
        session.rollback()
        return _preview_page(request, session, sub, 422, [str(exc)])
    sub.preset, sub.selected = saved, saved.id
    return _preview_page(request, session, sub, notes=[f'Saved as preset: {saved.name}.'])


@router.post("/{batch_id}/undo")
def import_undo(request: Request, batch_id: int, session: SessionDep):
    """Undo one import batch."""
    try:
        pipeline.undo_batch(session, batch_id)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    sync_after_save(request)  # events of the undone reminders are removed
    return redirect(request, "/import")
