"""Fuelly-compatible export (D8). FROZEN SIGNATURE; implemented in group 5."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ExportFile:
    """A downloadable file."""

    filename: str
    media_type: str
    content: bytes


def export_fuelly(session: Session, vehicle_ids: Sequence[int] | None = None) -> ExportFile:
    """
    Build the Fuelly-compatible export.

    One CSV per vehicle with header
    ``fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags``;
    zipped when there is more than one vehicle. Expenses are omitted.
    """
    raise NotImplementedError
