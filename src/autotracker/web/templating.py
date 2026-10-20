"""Shared Jinja2 environment; templates build URLs only through ``url``."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from autotracker.urls import url

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.globals["url"] = url
