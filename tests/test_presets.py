"""Preset loading, validation, writing and user preset storage."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from glovebox.importers import presets
from glovebox.importers.presets import (
    PresetError,
    PresetNameError,
    load_preset,
    write_preset,
)
from glovebox.services.records import NotFoundError

FULL = '''
name = "Fuelly (metric)"
note = "Based on \\"public\\" descriptions\\nsecond line"
verified = false
export = true
split_by_vehicle = true

[file]
encoding = "cp1252"
delimiter = ";"
header_row = 2
section = "Log"

[format]
date_format = "%d.%m.%Y %H:%M"
decimal_char = ","
group_char = "."
distance_unit = "km"
volume_unit = "l"

[fields]
type = { value = "refuel" }
date = { column = "fuelup_date" }
odometer_km = { column = ["odometer", "km"] }
fuel_l = { column = "litres", missing_values = ["0"] }
full = { column = "partial_fuelup", true_values = ["0"], false_values = ["1"], default = "true" }
category = { column = "Title", map = { "maintenance" = ["Oil change", "Service"] }, default = "other" }
title = { column = "Title" }

[[skip_rows]]
column = "isTemplate"
values = ["1"]
'''


def test_load_full_preset() -> None:
    preset = load_preset(FULL, id="x")
    assert preset.name == "Fuelly (metric)"
    assert preset.export and preset.split_by_vehicle and not preset.verified
    assert preset.file.header_row == 2 and preset.file.section == "Log"
    assert preset.format.decimal_char == ","
    assert list(preset.fields)[:3] == ["type", "date", "odometer_km"]
    assert preset.fields["odometer_km"].columns == ("odometer", "km")
    assert preset.fields["type"].value == "refuel"
    assert preset.fields["category"].map == {"maintenance": ("Oil change", "Service")}
    assert preset.skip_rows[0].values == ("1",)


def test_defaults() -> None:
    preset = load_preset('name = "A"\n[fields]\ndate = { column = "d" }\n')
    assert preset.format == presets.FormatSettings("auto", "auto", "", "auto", "auto")
    assert preset.file == presets.FileSettings()
    assert not preset.export and preset.note == ""


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ('name = "A"\n[fields]\nlitres = { column = "x" }\n', "fields.litres"),
        ('name = "A"\nbogus = 1\n', "bogus"),
        ('name = "A"\n[fields]\nfull = { column = "x", true_value = ["0"] }\n',
         "fields.full.true_value"),
        ('name = "A"\n[fields]\nfull = { column = "x", true_values = "0" }\n',
         "fields.full.true_values: expected a list of strings"),
        ('name = "A"\n[fields]\ndate = { column = "x", value = "y" }\n', "fields.date"),
        ('name = "A"\n[fields]\ndate = {}\n', "fields.date"),
        ('name = "A"\n[fields]\ntype = { value = "trip" }\n', "fields.type.value"),
        ('name = "A"\n[fields]\nnotes = { column = "x", map = { a = ["b"] } }\n',
         "fields.notes.map"),
        ('name = "A"\n[fields]\ncategory = { column = "x", map = { food = ["b"] } }\n',
         "fields.category.map.food"),
        ('name = "A"\n[fields]\ndate = { column = "x", true_values = ["1"] }\n',
         "fields.date"),
        ('name = "A"\n[format]\ndecimal_char = ";"\n', "format.decimal_char"),
        ('name = "A"\n[format]\nvolume_unit = "pint"\n', "format.volume_unit"),
        ('name = "A"\n[format]\ndate_format = "dmy"\n', "format.date_format"),
        ('name = "A"\n[file]\nheader_row = 0\n', "file.header_row"),
        ('name = "A"\n[file]\nencoding = "nope"\n', "file.encoding"),
        ('name = "A"\n[file]\ndelimiter = "|"\n', "file.delimiter"),
        ('name = "A"\n[[skip_rows]]\ncolumn = "x"\n', "skip_rows[0].values"),
        ('name = "A"\n[[skip_rows]]\ncolumn = "x"\nvalues = []\nextra = 1\n',
         "skip_rows[0].extra"),
        ('note = "x"\n', "name"),
        ('name = ""\n', "name"),
        ('name = "A"\nexport = "yes"\n', "export"),
        ("name = ", "invalid TOML"),
    ],
)
def test_validation_names_the_key(text: str, path: str) -> None:
    with pytest.raises(PresetError) as error:
        load_preset(text)
    assert path in str(error.value)


def test_write_read_round_trip() -> None:
    preset = load_preset(FULL, id="x")
    assert load_preset(write_preset(preset), id="x") == preset


def test_round_trip_awkward_strings() -> None:
    text = (
        'name = "Q\\"uote \\\\ tab\\t \\u00e9 \\u007f"\n'
        'note = "line\\nbreak"\n'
        "[format]\ngroup_char = \"'\"\n"
        '[fields]\ntitle = { column = ["a \\"b\\"", "c\\\\d"] }\n'
        'category = { value = "other", map = { "other" = ["x y", "\\u0001"] } }\n'
    )
    preset = load_preset(text)
    assert load_preset(write_preset(preset)) == preset


def test_write_keeps_field_order() -> None:
    preset = load_preset(FULL)
    written = load_preset(write_preset(preset))
    assert list(written.fields) == list(preset.fields)


def test_shipped_presets_are_read_only_and_valid() -> None:
    for preset in presets.shipped_presets():
        assert preset.shipped and preset.id
        assert load_preset(write_preset(preset), id=preset.id, shipped=True) == preset


def test_shipped_dir_is_read(tmp_path, monkeypatch) -> None:
    (tmp_path / "b.toml").write_text('name = "B"\n[fields]\ndate = { column = "d" }\n')
    (tmp_path / "glovebox.toml").write_text('name = "Std"\n')
    (tmp_path / "bad.toml").write_text('name = "Bad"\nzzz = 1\n')
    monkeypatch.setattr(presets, "SHIPPED_DIR", tmp_path)
    with pytest.raises(PresetError, match=r"bad\.toml: zzz"):
        presets.shipped_presets()
    (tmp_path / "bad.toml").unlink()
    assert [p.id for p in presets.shipped_presets()] == ["glovebox", "b"]


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    (tmp_path / "fuelly-metric.toml").write_text(
        'name = "Fuelly (metric)"\n[fields]\ndate = { column = "d" }\n'
    )
    monkeypatch.setattr(presets, "SHIPPED_DIR", tmp_path)


def _mine(name: str = "My app") -> presets.Preset:
    return load_preset(f'name = "{name}"\n[fields]\ndate = {{ column = "when" }}\n')


def test_user_preset_crud(session: Session, shipped) -> None:
    saved = presets.save_user_preset(session, _mine())
    assert saved.id == "user-my-app" and not saved.shipped
    assert presets.get_preset(session, "user-my-app") == saved
    assert [p.id for p in presets.list_presets(session)] == ["user-my-app", "fuelly-metric"]

    renamed = presets.save_user_preset(session, _mine("My other app"), replace_id=saved.id)
    assert renamed.id == "user-my-app"  # id is stable
    assert presets.get_preset(session, "user-my-app").name == "My other app"

    presets.delete_user_preset(session, "user-my-app")
    with pytest.raises(NotFoundError):
        presets.get_preset(session, "user-my-app")


def test_name_clash_is_rejected(session: Session, shipped) -> None:
    presets.save_user_preset(session, _mine())
    with pytest.raises(PresetNameError):
        presets.save_user_preset(session, _mine("my APP"))
    with pytest.raises(PresetNameError):
        presets.save_user_preset(session, _mine("my-app"))  # same slug
    with pytest.raises(PresetNameError):
        presets.save_user_preset(session, _mine("fuelly (METRIC)"))  # shipped name
    with pytest.raises(PresetNameError):
        presets.save_user_preset(session, _mine("???"))


def test_shipped_not_writable(session: Session, shipped) -> None:
    with pytest.raises(PresetError):
        presets.save_user_preset(session, _mine("Copy"), replace_id="fuelly-metric")
    with pytest.raises(PresetError):
        presets.delete_user_preset(session, "fuelly-metric")
    assert presets.get_preset(session, "fuelly-metric").name == "Fuelly (metric)"


def test_missing_preset(session: Session, shipped) -> None:
    with pytest.raises(NotFoundError):
        presets.get_preset(session, "nope")
    with pytest.raises(NotFoundError):
        presets.delete_user_preset(session, "user-nope")
    with pytest.raises(NotFoundError):
        presets.save_user_preset(session, _mine(), replace_id="user-nope")


# --- steps and zero_amount -------------------------------------------------

MINIMAL = 'name = "X"\n{extra}\n[fields]\ntype = {{ value = "expense" }}\n'


def test_steps_and_zero_amount_round_trip() -> None:
    text = MINIMAL.format(extra='steps = ["One.", " Two. "]\nzero_amount = "note"')
    preset = load_preset(text)
    assert preset.steps == ("One.", "Two.") and preset.zero_amount == "note"
    assert load_preset(write_preset(preset)) == preset


def test_steps_and_zero_amount_defaults_are_not_written() -> None:
    preset = load_preset(MINIMAL.format(extra=""))
    assert preset.steps == () and preset.zero_amount == "error"
    assert "steps" not in write_preset(preset) and "zero_amount" not in write_preset(preset)


@pytest.mark.parametrize(
    ("extra", "path"),
    [
        ('steps = "one"', "steps"),
        ("steps = [1]", "steps"),
        ('steps = ["ok", " "]', "steps"),
        ('zero_amount = "skip"', "zero_amount"),
    ],
)
def test_invalid_steps_and_zero_amount_name_the_key(extra: str, path: str) -> None:
    with pytest.raises(PresetError, match=path):
        load_preset(MINIMAL.format(extra=extra))
