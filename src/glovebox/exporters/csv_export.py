"""
Preset-driven CSV export (design D8). Signature FROZEN by task group 1;
task group 4 implements it.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from glovebox.config import Settings
from glovebox.importers.presets import Preset


def export_csv(
    session: Session,
    settings: Settings,
    preset: Preset,
    vehicle_ids: Sequence[int] | None = None,
) -> tuple[bytes, str]:
    """
    Export records through an exportable preset (``export`` set, no skip rules).

    Parameters
    ----------
    vehicle_ids : Sequence[int] | None
        Vehicles to export; ``None`` means all.

    Returns
    -------
    tuple[bytes, str]
        The content and its media type: ``text/csv``, or ``application/zip``
        when the preset splits by vehicle and more than one file results.
    """
    raise NotImplementedError("task 4.1")
