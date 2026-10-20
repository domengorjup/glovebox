"""HTML routes: dashboard, vehicles, refuels, expenses, stations, import, export."""

from __future__ import annotations

from fastapi import APIRouter

from autotracker.web import (
    dashboard,
    exports,
    expenses,
    imports,
    refuels,
    stations,
    vehicles,
)

router = APIRouter()
for module in (dashboard, vehicles, refuels, expenses, stations, imports, exports):
    router.include_router(module.router)
