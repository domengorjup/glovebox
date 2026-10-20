"""HTML routes. Group 6 adds pages to ``router`` (or submodules it includes)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from autotracker.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Placeholder home page; replaced by the dashboard in group 6."""
    return templates.TemplateResponse(request, "index.html")
