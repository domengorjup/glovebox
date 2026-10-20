"""Stats API under ``/api/v1`` (D10). Endpoints are added in group 7."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["api-v1"])
