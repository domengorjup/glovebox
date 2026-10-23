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
    reminders,
    stations,
    statistics,
    timeline,
    vehicles,
)

router = APIRouter()
for module in (
    timeline, statistics, manage, preferences, vehicles, refuels, expenses,
    stations, imports, exports, presets, reminders,
):
    router.include_router(module.router)
router.include_router(refuels.quick_router)
router.include_router(expenses.quick_router)
