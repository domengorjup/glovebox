"""
Preset-driven CSV import engine (design D6). Pure: no database access.

Signatures are FROZEN by task group 1; task group 2 implements them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from glovebox.importers.base import Answers, ImportResult
from glovebox.importers.presets import Preset


@dataclass
class SourceTable:
    """
    One CSV table of an upload (a file, one ZIP member, or one section).

    Attributes
    ----------
    name : str
        File stem (ZIP member) or upload name; the default vehicle name when
        the preset has no ``vehicle`` field.
    headers : list[str]
        The header row as found.
    rows : list[tuple[int, list[str]]]
        Data rows with their 1-based line number in the file.
    encoding, delimiter : str
        What was used to read the table.
    header_row : int
        Header position over the non-blank rows (1 = first).
    """

    name: str
    headers: list[str]
    rows: list[tuple[int, list[str]]]
    encoding: str = "utf-8"
    delimiter: str = ","
    header_row: int = 1


@dataclass
class SourceFile:
    """
    A read upload: its tables, and whether it is a full backup (a ZIP with
    ``datapackage.json``; its members ``records.csv``, ``vehicles.csv`` and
    ``stations.csv`` are then in ``tables``).
    """

    tables: list[SourceTable] = field(default_factory=list)
    is_backup: bool = False
    sections: list[str] = field(default_factory=list)  # ``## name`` lines found


def read_file(
    data: bytes, preset: Preset | None = None, answers: Answers | None = None
) -> SourceFile:
    """
    Decode and split an upload (CSV, or ZIP of CSVs) into tables.

    Encoding, delimiter, section and header row come from ``answers`` first,
    then the preset's ``file`` settings, then detection (the header row is the
    one among the first 20 non-blank rows that contains most of the preset's
    candidate headers). Never raises on bad content; an unreadable file gives
    no tables.
    """
    raise NotImplementedError("task 2.1")


def score(preset: Preset, source: SourceFile) -> float:
    """
    Fraction (0.0-1.0) of the preset's ``column`` fields whose header is found
    in the source; 0.0 if its ``date`` column or its ``section`` is missing.
    """
    raise NotImplementedError("task 2.2")


def apply(
    preset: Preset, source: SourceFile, answers: Answers | None = None
) -> ImportResult:
    """
    Turn the source tables into canonical records with the preset's mapping
    and value formats. Row faults go to ``ImportResult.row_errors``; unmapped
    required fields and unanswered questions block (``errors`` / ``questions``).
    """
    raise NotImplementedError("task 2.3")
