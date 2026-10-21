"""Export page: preset choice, customised columns and format, full backup."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from glovebox import standard
from glovebox.exporters import backup, csv_export
from glovebox.importers.presets import (
    STANDARD_ID,
    FieldMapping,
    FileSettings,
    FormatSettings,
    Preset,
    PresetError,
    get_preset,
    list_presets,
    save_user_preset,
)
from glovebox.services import records
from glovebox.services.records import NotFoundError
from glovebox.standard import RECORD_FIELDS
from glovebox.web.common import SessionDep, parse_ints, render

router = APIRouter(prefix="/export")

DELIMITERS = ((",", "Comma"), (";", "Semicolon"), ("\t", "Tab"))
DECIMALS = ((".", "Dot"), (",", "Comma"))
DISTANCES = (("km", "Kilometres"), ("mi", "Miles"))
VOLUMES = (("l", "Litres"), ("gal_us", "US gallons"), ("gal_uk", "UK gallons"))


def exportable(preset: Preset) -> bool:
    """A preset the export page offers: marked for export and without skip rules."""
    return preset.export and not preset.skip_rows


def _vehicle_ids(form: FormData) -> list[int] | None:
    """Vehicle ids ticked on the page; none ticked means all."""
    ids = parse_ints([str(v) for v in form.getlist("vehicle")], "vehicle")
    return list(ids) or None


def _preset(session: Session, preset_id: str) -> Preset:
    try:
        preset = get_preset(session, preset_id or STANDARD_ID)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    if not exportable(preset):
        raise HTTPException(422, detail=f"{preset.name}: this preset cannot be used for export")
    return preset


def _unit(value: str, fallback: str) -> str:
    return value if value in {"km", "mi", "l", "gal_us", "gal_uk"} else fallback


def custom_preset(form: FormData, base: Preset) -> Preset:
    """
    The export described by the page: ``base`` with the ticked columns, their
    headers and the format options. Raises ``PresetError`` for a bad entry.
    """
    fields: dict[str, FieldMapping] = {}
    for name, mapping in base.fields.items():
        if mapping.value is not None:  # a constant (e.g. the record type) stays
            fields[name] = mapping
        elif form.get(f"include.{name}"):
            header = str(form.get(f"header.{name}", "")).strip() or mapping.columns[0]
            fields[name] = replace(mapping, columns=(header,))
    for target in RECORD_FIELDS:
        if target.name not in base.fields and form.get(f"include.{target.name}"):
            header = str(form.get(f"header.{target.name}", "")).strip() or target.name
            fields[target.name] = FieldMapping(columns=(header,))
    if not any(m.value is None for m in fields.values()):
        raise PresetError("fields: choose at least one column")
    pattern = str(form.get("date_format", "")).strip()
    return replace(
        base,
        fields=fields,
        file=FileSettings(delimiter=str(form.get("delimiter", "")) or ","),
        format=FormatSettings(
            date_format=pattern or "auto",
            decimal_char="," if form.get("decimal_char") == "," else ".",
            distance_unit=_unit(str(form.get("distance_unit", "")), "km"),
            volume_unit=_unit(str(form.get("volume_unit", "")), "l"),
        ),
    )


def _column_rows(base: Preset) -> list[dict]:
    rows = []
    for target in RECORD_FIELDS:
        mapping = base.fields.get(target.name)
        included = mapping is not None and mapping.value is None
        rows.append({
            "name": target.name,
            "included": included,
            "header": mapping.columns[0] if included else target.name,
            "description": target.description,
        })
    return rows


def _page(
    request: Request, session: Session, base: Preset, ticked: list[int] | None = None,
    status: int = 200, errors: list[str] | None = None, notes: list[str] | None = None,
):
    vehicles = records.list_vehicles(session, include_archived=True)
    renamed = csv_export.renamed_vehicles(session, ticked)
    warnings = [
        f'"{stored}" is exported as "{written}" because another vehicle has the same name.'
        for stored, written in renamed.items()
    ]
    fmt = base.format
    type_filter = base.fields["type"].value if "type" in base.fields else None
    return render(
        request,
        "export.html",
        status,
        vehicles=vehicles,
        ticked=[str(i) for i in ticked or []],
        presets=[p for p in list_presets(session) if exportable(p)],
        base=base,
        columns=_column_rows(base),
        refuels_only=type_filter == standard.REFUEL,
        delimiters=DELIMITERS, decimals=DECIMALS, distances=DISTANCES, volumes=VOLUMES,
        delimiter=base.file.delimiter or ",",
        decimal=fmt.decimal_char if fmt.decimal_char in (".", ",") else ".",
        distance=_unit(fmt.distance_unit, "km"),
        volume=_unit(fmt.volume_unit, "l"),
        date_pattern="" if fmt.date_format == "auto" else fmt.date_format,
        errors=errors or [],
        warnings=warnings,
        notes=notes or [],
    )


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("")
def export_home(request: Request, session: SessionDep):
    """Export page with the standard preset selected."""
    return _page(request, session, _preset(session, request.query_params.get("preset", "")))


@router.post("")
async def export_update(request: Request, session: SessionDep):
    """Show the page for another preset, keeping the ticked vehicles."""
    form = await request.form()
    return _page(request, session, _preset(session, str(form.get("preset", ""))),
                 _vehicle_ids(form))


@router.post("/csv")
async def export_download(request: Request, session: SessionDep) -> Response:
    """Download the chosen preset (with the page's customisations) as CSV or ZIP."""
    form = await request.form()
    base = _preset(session, str(form.get("base_preset", "")))
    try:
        preset = custom_preset(form, base)
        content, media_type = csv_export.export_csv(
            session, request.app.state.settings, preset, _vehicle_ids(form)
        )
    except (PresetError, csv_export.NothingToExport) as exc:
        return _page(request, session, base, _vehicle_ids(form), 422, [str(exc)])
    extension = "zip" if media_type == "application/zip" else "csv"
    return _attachment(content, media_type, f"glovebox-export-{date.today().isoformat()}.{extension}")


@router.post("/preset")
async def export_save_preset(request: Request, session: SessionDep):
    """Store the customised export as an own preset (it can then also import)."""
    form = await request.form()
    base = _preset(session, str(form.get("base_preset", "")))
    ticked = _vehicle_ids(form)
    try:
        preset = custom_preset(form, base)
        saved = save_user_preset(
            session, replace(preset, name=str(form.get("preset_name", "")).strip(), export=True)
        )
        session.commit()
    except PresetError as exc:
        session.rollback()
        return _page(request, session, base, ticked, 422, [str(exc)])
    return _page(request, session, saved, ticked, notes=[f'Saved as preset: {saved.name}.'])


@router.post("/backup")
async def export_backup(request: Request, session: SessionDep) -> Response:
    """Download the full backup (ZIP)."""
    form = await request.form()
    content = backup.export_backup(session, request.app.state.settings, _vehicle_ids(form))
    return _attachment(content, "application/zip", f"glovebox-backup-{date.today().isoformat()}.zip")


@router.get("/format.json")
def export_format() -> Response:
    """The description of the standard format (a Data Package descriptor)."""
    return _attachment(
        json.dumps(standard.datapackage(), indent=2).encode("utf-8") + b"\n",
        "application/json",
        "glovebox-standard-format.datapackage.json",
    )
