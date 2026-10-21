"""
Full backup ZIP (design D7). Signature FROZEN by task group 1; task group 4
implements it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from glovebox.config import Settings


def export_backup(session: Session, settings: Settings) -> bytes:
    """
    ZIP with ``records.csv`` (standard format, all fields), ``vehicles.csv``,
    ``stations.csv`` and ``datapackage.json`` (with the ``glovebox`` metadata).
    """
    raise NotImplementedError("task 4.2")
