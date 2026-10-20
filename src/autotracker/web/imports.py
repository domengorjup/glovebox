"""Import pages: upload, preview with vehicle mapping, confirm, batch list, undo."""

from __future__ import annotations

import re
import time as time_module
import uuid
from pathlib import Path
from urllib.parse import urlencode
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from autotracker.importers import pipeline
from autotracker.importers.base import ImportOptions
from autotracker.importers.pipeline import VehicleMapping
from autotracker.services import records
from autotracker.services.records import RecordsError
from autotracker.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/import")

UPLOAD_MAX_AGE_SECONDS = 24 * 3600
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ImportParams(BaseModel):
    """
    State carried between preview and confirm (query on GET, form on POST).

    ``names[i]`` is a vehicle name found in the file and ``maps[i]`` is the
    chosen target: an existing vehicle id, or ``new`` / empty to create it.
    """

    token: str = ""
    filename: str = ""
    format: str = ""
    date_order: str = ""
    units: str = ""
    default_vehicle: str = ""
    names: list[str] = []
    maps: list[str] = []


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


def _mapping(params: ImportParams) -> VehicleMapping:
    """Build the vehicle mapping from the aligned name/target lists."""
    by_name: dict[str, int | None] = {}
    for name, target in zip(params.names, params.maps):
        by_name[name] = int(target) if target.isdigit() else None
    default = int(params.default_vehicle) if params.default_vehicle.isdigit() else None
    return VehicleMapping(by_name=by_name, default_vehicle_id=default)


def _options(params: ImportParams) -> ImportOptions:
    return ImportOptions(
        date_order=params.date_order or None, units=params.units or None
    )


def _format_names() -> list[str]:
    return [adapter.name for adapter in pipeline.available_formats()]


@router.get("")
def import_home(request: Request, session: SessionDep):
    """Upload form and the list of past import batches."""
    return render(
        request,
        "import/index.html",
        formats=_format_names(),
        batches=pipeline.list_batches(session),
        errors=[],
    )


@router.post("/upload")
def import_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    format: Annotated[str, Form()] = "",
):
    """Store the file temporarily and go to its preview (nothing is imported)."""
    directory = _upload_dir(request)
    directory.mkdir(parents=True, exist_ok=True)
    _remove_old_uploads(directory)
    token = uuid.uuid4().hex
    (directory / f"{token}.upload").write_bytes(file.file.read())
    params = ImportParams(token=token, filename=file.filename or "upload", format=format)
    return redirect(request, "/import/preview?" + _query(params))


def _query(params: ImportParams) -> str:
    items = [(k, v) for k, v in params.model_dump().items() if isinstance(v, str) and v]
    items += [("names", n) for n in params.names]
    items += [("maps", m) for m in params.maps]
    return urlencode(items)


def _preview_page(
    request: Request, session: Session, params: ImportParams,
    status: int = 200, errors: list[str] | None = None,
):
    """Render the preview for the stored upload."""
    data = _upload_path(request, params.token).read_bytes()
    preview = pipeline.preview_import(
        session,
        data,
        format=params.format or None,
        options=_options(params),
        mapping=_mapping(params),
    )
    vehicles = records.list_vehicles(session)
    chosen = dict(zip(params.names, params.maps))
    selection = {}
    for name in preview.vehicle_names:
        by_name = next((v for v in vehicles if v.name.lower() == name.lower()), None)
        default = str(by_name.id) if by_name else "new"
        selection[name] = chosen.get(name, default) or "new"
    blocked = bool(preview.errors or preview.header_mismatch or preview.ambiguities)
    return render(
        request,
        "import/preview.html",
        status,
        p=params,
        preview=preview,
        vehicles=vehicles,
        selection=selection,
        formats=_format_names(),
        blocked=blocked,
        ambiguities=[a.value for a in preview.ambiguities],
        errors=errors or [],
    )


@router.get("/preview")
def import_preview(
    request: Request, session: SessionDep, params: Annotated[ImportParams, Query()]
):
    """Preview of the uploaded file; changes no data."""
    return _preview_page(request, session, params)


@router.post("/commit")
def import_commit(
    request: Request, session: SessionDep, params: Annotated[ImportParams, Form()]
):
    """Write the previewed records in one batch."""
    path = _upload_path(request, params.token)
    try:
        pipeline.commit_import(
            session,
            path.read_bytes(),
            params.filename or "upload",
            _mapping(params),
            format=params.format or None,
            options=_options(params),
        )
    except (ValueError, RecordsError) as exc:
        session.rollback()
        return _preview_page(request, session, params, 422, [str(exc)])
    path.unlink(missing_ok=True)
    return redirect(request, "/import")


@router.post("/{batch_id}/undo")
def import_undo(request: Request, batch_id: int, session: SessionDep):
    """Undo one import batch."""
    pipeline.undo_batch(session, batch_id)
    return redirect(request, "/import")
