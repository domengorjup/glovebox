"""Presets page: list shipped and own presets; download, upload, delete."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from glovebox import models
from glovebox.importers import presets as preset_store
from glovebox.importers.presets import (
    USER_PREFIX,
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
        locked_ids=_locked_ids(session),
    )


def _locked_ids(session: Session) -> set[str]:
    """Ids of the user presets that are locked."""
    slugs = session.scalars(select(models.Preset.slug).where(models.Preset.locked))
    return {USER_PREFIX + slug for slug in slugs}


def _is_locked(session: Session, preset: Preset) -> bool:
    """Shipped presets are always locked; user presets only when asked."""
    return preset.shipped or preset.id in _locked_ids(session)


def _set_locked(session: Session, preset_id: str, locked: bool) -> None:
    row = session.scalar(
        select(models.Preset).where(models.Preset.slug == preset_id[len(USER_PREFIX):])
    )
    row.locked = locked


def _copy_name(session: Session, name: str) -> str:
    """"<name> (copy)", numbered when that name is already taken."""
    taken = {p.name.casefold() for p in list_presets(session)}
    candidate, number = f"{name} (copy)", 2
    while candidate.casefold() in taken:
        candidate, number = f"{name} (copy {number})", number + 1
    return candidate


def preset_text(preset: Preset) -> str:
    """TOML to download: the original file for a shipped preset (it has comments)."""
    if preset.shipped:
        return (preset_store.SHIPPED_DIR / f"{preset.id}.toml").read_text(encoding="utf-8")
    return write_preset(preset)


@router.get("")
def presets_home(request: Request, session: SessionDep):
    """List of presets with download, delete and the upload form."""
    return _page(request, session)


def _detail_page(
    request: Request, session: Session, preset: Preset, status: int = 200,
    errors: list[str] | None = None, note: str | None = None,
):
    return render(
        request,
        "presets/form.html",
        status,
        preset=preset,
        locked=_is_locked(session, preset),
        note=preset.note if note is None else note,
        errors=errors or [],
    )


def _load(session: Session, preset_id: str) -> Preset:
    try:
        return get_preset(session, preset_id)
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None


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


@router.get("/{preset_id}")
def presets_detail(request: Request, preset_id: str, session: SessionDep):
    """One preset in full: editable note for an own preset, read-only if shipped."""
    return _detail_page(request, session, _load(session, preset_id))


@router.post("/{preset_id}/edit")
def presets_edit(
    request: Request, preset_id: str, session: SessionDep, note: Annotated[str, Form()] = ""
):
    """Change the note of an own preset."""
    preset = _load(session, preset_id)
    if _is_locked(session, preset):
        raise HTTPException(403, detail="A locked preset cannot be changed.")
    # The note is one line in the TOML file; fold line breaks into spaces.
    clean = " ".join(note.split())
    try:
        save_user_preset(session, replace(preset, note=clean), replace_id=preset_id)
        session.commit()
    except PresetError as exc:
        session.rollback()
        return _detail_page(request, session, preset, 422, [str(exc)], note)
    return redirect(request, "/presets")


@router.post("/{preset_id}/lock")
def presets_lock(request: Request, preset_id: str, session: SessionDep, locked: Annotated[str, Form()] = "1"):
    """Lock (``locked=1``) or unlock (``locked=0``) an own preset."""
    preset = _load(session, preset_id)
    if preset.shipped:
        raise HTTPException(403, detail="Shipped presets are always locked.")
    _set_locked(session, preset_id, locked == "1")
    session.commit()
    return redirect(request, "/presets")


@router.post("/{preset_id}/duplicate")
def presets_duplicate(request: Request, preset_id: str, session: SessionDep):
    """Make an unlocked own copy of any preset and open it."""
    preset = _load(session, preset_id)
    save_user_preset(session, replace(preset, name=_copy_name(session, preset.name)))
    session.commit()
    return redirect(request, "/presets")


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
    if _is_locked(session, _load(session, preset_id)):
        return _page(request, session, 422, ["A locked preset cannot be deleted. Unlock it first."])
    try:
        delete_user_preset(session, preset_id)
        session.commit()
    except NotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    except PresetError as exc:
        session.rollback()
        return _page(request, session, 422, [str(exc)])
    return redirect(request, "/presets")
