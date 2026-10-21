"""Presets page: list shipped and own presets; download, upload, delete."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from glovebox.importers import presets as preset_store
from glovebox.importers.presets import (
    Preset,
    PresetError,
    delete_user_preset,
    get_preset,
    list_presets,
    load_preset,
    save_user_preset,
    write_preset,
)
from glovebox.services.records import NotFoundError
from glovebox.web.common import SessionDep, redirect, render

router = APIRouter(prefix="/presets")

MAX_UPLOAD_BYTES = 256 * 1024


def _page(request: Request, session: Session, status: int = 200, errors: list[str] | None = None):
    presets = list_presets(session)
    return render(
        request,
        "presets/index.html",
        status,
        own=[p for p in presets if not p.shipped],
        shipped=[p for p in presets if p.shipped],
        errors=errors or [],
    )


def preset_text(preset: Preset) -> str:
    """TOML to download: the original file for a shipped preset (it has comments)."""
    if preset.shipped:
        return (preset_store.SHIPPED_DIR / f"{preset.id}.toml").read_text(encoding="utf-8")
    return write_preset(preset)


@router.get("")
def presets_home(request: Request, session: SessionDep):
    """List of presets with download, delete and the upload form."""
    return _page(request, session)


@router.get("/{preset_id}/download")
def presets_download(preset_id: str, session: SessionDep) -> Response:
    """One preset as a TOML file."""
    try:
        preset = get_preset(session, preset_id)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    return Response(
        preset_text(preset),
        media_type="application/toml",
        headers={"Content-Disposition": f'attachment; filename="{preset.id}.toml"'},
    )


@router.post("/upload")
def presets_upload(
    request: Request, session: SessionDep, file: Annotated[UploadFile, File()]
):
    """Add an own preset from a TOML file."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return _page(request, session, 422, ["The file is too large for a preset."])
    try:
        preset = load_preset(data.decode("utf-8-sig"))
        save_user_preset(session, preset)
        session.commit()
    except UnicodeDecodeError:
        return _page(request, session, 422, ["The file is not UTF-8 text."])
    except PresetError as exc:
        session.rollback()
        return _page(request, session, 422, [f"{file.filename or 'Preset'}: {exc}"])
    return redirect(request, "/presets")


@router.post("/{preset_id}/delete")
def presets_delete(request: Request, preset_id: str, session: SessionDep):
    """Delete an own preset."""
    try:
        delete_user_preset(session, preset_id)
        session.commit()
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    except PresetError as exc:
        session.rollback()
        return _page(request, session, 422, [str(exc)])
    return redirect(request, "/presets")
