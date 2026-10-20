"""Native full export (D8). FROZEN SIGNATURE; implemented in group 5."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session


def export_native(session: Session, vehicle_ids: Sequence[int] | None = None) -> bytes:
    """
    Build the native export ZIP.

    Contains ``vehicles.csv``, ``stations.csv``, ``refuels.csv``,
    ``expenses.csv`` and ``manifest.json``, UTF-8, ISO dates, ``.`` decimals.

    Parameters
    ----------
    vehicle_ids : Sequence[int] | None, optional
        Vehicles to export; ``None`` exports all.

    Returns
    -------
    bytes
        The ZIP file content.
    """
    raise NotImplementedError
