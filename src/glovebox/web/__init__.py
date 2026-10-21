"""HTML routes: Timeline, Stats, Manage and the pages below them."""

from __future__ import annotations

from fastapi import APIRouter

from glovebox.web import (
    exports,
    expenses,
    imports,
    manage,
    preferences,
    presets,
    refuels,
    stations,
    statistics,
    timeline,
    vehicles,
)

router = APIRouter()
for module in (
    timeline, statistics, manage, preferences, vehicles, refuels, expenses,
    stations, imports, exports, presets,
):
    router.include_router(module.router)
