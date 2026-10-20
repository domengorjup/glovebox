"""
Import pipeline (D6): detect, parse, dedupe, preview, commit, undo.
FROZEN SIGNATURES; implemented in group 3. The web UI calls only this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from autotracker.importers.base import (
    Ambiguity,
    HeaderMismatch,
    ImportOptions,
    ImporterAdapter,
)
from autotracker.models import ImportBatch


@dataclass
class ImportPreview:
    """
    What would happen on commit; ``preview_import`` writes nothing.

    ``duplicate_*`` are counted against existing rows (D6 keys). A preview
    with ``errors`` or ``header_mismatch`` cannot be committed.
    """

    format: str
    vehicle_names: list[str]
    new_refuels: int
    new_expenses: int
    duplicate_refuels: int
    duplicate_expenses: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)
    header_mismatch: HeaderMismatch | None = None


@dataclass(frozen=True)
class VehicleMapping:
    """File vehicle name -> existing vehicle id, or ``None`` to create it.
    ``default_vehicle_id`` serves files without vehicle names."""

    by_name: dict[str, int | None] = field(default_factory=dict)
    default_vehicle_id: int | None = None


def available_formats() -> list[ImporterAdapter]:
    """Registered adapters (drivvo, fuelio, fuelly, native)."""
    raise NotImplementedError


def detect_format(data: bytes) -> str | None:
    """Return the best-matching adapter name, or ``None`` if none matches."""
    raise NotImplementedError


def preview_import(
    session: Session,
    data: bytes,
    *,
    format: str | None = None,
    options: ImportOptions | None = None,
    mapping: VehicleMapping | None = None,
) -> ImportPreview:
    """Parse and count without writing. ``format`` overrides detection."""
    raise NotImplementedError


def commit_import(
    session: Session,
    data: bytes,
    filename: str,
    mapping: VehicleMapping,
    *,
    format: str | None = None,
    options: ImportOptions | None = None,
) -> ImportBatch:
    """Write all new records in one transaction under a new ``ImportBatch``;
    duplicates are skipped and counted."""
    raise NotImplementedError


def list_batches(session: Session) -> list[ImportBatch]:
    """Import batches, newest first."""
    raise NotImplementedError


def undo_batch(session: Session, batch_id: int) -> None:
    """Delete the batch's refuels, expenses and stations created only by it."""
    raise NotImplementedError


__all__ = [
    "ImportPreview",
    "VehicleMapping",
    "available_formats",
    "commit_import",
    "detect_format",
    "list_batches",
    "preview_import",
    "undo_batch",
]
