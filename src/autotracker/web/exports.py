"""Export page and download endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Response

from autotracker.exporters import fuelly, native
from autotracker.services import records
from autotracker.web.common import SessionDep, parse_ints, render

router = APIRouter(prefix="/export")


def _vehicle_ids(request: Request) -> list[int] | None:
    """Vehicle ids from ``?vehicle=`` (blank means all)."""
    ids = parse_ints(request.query_params.getlist("vehicle"), "vehicle")
    return list(ids) or None


@router.get("")
def export_home(request: Request, session: SessionDep):
    """Export page with the download forms."""
    vehicles = records.list_vehicles(session, include_archived=True)
    return render(request, "export.html", vehicles=vehicles)


@router.get("/native")
def export_native(request: Request, session: SessionDep) -> Response:
    """Download the native full export (ZIP)."""
    content = native.export_native(
        session, request.app.state.settings, _vehicle_ids(request)
    )
    filename = f"autotracker-export-{date.today().isoformat()}.zip"
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/fuelly")
def export_fuelly(request: Request, session: SessionDep) -> Response:
    """Download the Fuelly-compatible export (CSV, or ZIP for several vehicles)."""
    export = fuelly.export_fuelly(session, _vehicle_ids(request))
    return Response(
        export.content,
        media_type=export.media_type,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )
