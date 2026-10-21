"""The generated format documentation is current and its example is valid."""

from __future__ import annotations

import json
import re

import pytest

from glovebox import formatdocs
from glovebox.importers import engine
from glovebox.importers.presets import STANDARD_ID, shipped_presets
from glovebox.standard import RECORD_FIELDS, TABLES


@pytest.mark.parametrize("name", list(formatdocs.rendered_files()))
def test_committed_file_matches_rendered(name: str) -> None:
    path = formatdocs.DOCS_DIR / name
    assert path.exists(), f"{name} is missing. Run: {formatdocs.COMMAND}"
    assert path.read_text(encoding="utf-8") == formatdocs.rendered_files()[name], (
        f"{name} is out of date. Run: {formatdocs.COMMAND}"
    )


def test_check_flag_reports_stale_file(tmp_path, capsys) -> None:
    assert formatdocs.main(["--check", "--docs-dir", str(tmp_path)]) == 1
    assert formatdocs.COMMAND in capsys.readouterr().err
    assert formatdocs.main(["--docs-dir", str(tmp_path)]) == 0
    assert formatdocs.main(["--check", "--docs-dir", str(tmp_path)]) == 0


def test_descriptor_fields_match_record_fields() -> None:
    descriptor = json.loads(
        (formatdocs.DOCS_DIR / formatdocs.DATAPACKAGE_JSON).read_text(encoding="utf-8")
    )
    resources = {r["name"]: r for r in descriptor["resources"]}
    assert set(resources) == set(TABLES)
    records = resources["records"]["schema"]["fields"]
    assert [f["name"] for f in records] == [f.name for f in RECORD_FIELDS]
    required = {f["name"] for f in records if f.get("constraints", {}).get("required")}
    assert required == {"type", "vehicle", "date"}
    assert all(f["description"] and f["example"] for f in records)


def test_docs_example_csv_is_valid_standard_file() -> None:
    """Imports the example from the docs page with the standard preset (needs group 2)."""
    page = (formatdocs.DOCS_DIR / formatdocs.STANDARD_MD).read_text(encoding="utf-8")
    block = re.search(r"```csv\n(.*?)\n```", page, re.DOTALL)
    assert block, "no csv example on the standard format page"
    data = block.group(1).replace("\n", "\r\n").encode("utf-8") + b"\r\n"
    assert data == formatdocs.example_csv().encode("utf-8")
    preset = next(p for p in shipped_presets() if p.id == STANDARD_ID)
    result = engine.apply(preset, engine.read_file(data, preset))
    assert not result.errors
    assert not result.row_errors
    assert not result.questions
    assert len(result.refuels) == 1
    assert len(result.expenses) == 1
