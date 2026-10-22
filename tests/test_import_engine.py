"""Import engine: reading files, scoring presets and applying mappings."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import date, time

import pytest

from glovebox.importers import engine
from glovebox.importers.base import Answers, QuestionKind
from glovebox.importers.presets import load_preset
from glovebox.models import DerivedField, ExpenseCategory

STANDARD = engine.standard_preset()

FUELIO_FILLUPS = """
name = "Fuelio fill-ups"
[file]
section = "Log"
[format]
distance_unit = "auto"
volume_unit = "auto"
[fields]
type = { value = "refuel" }
date = { column = "Data" }
odometer_km = { column = "Odo" }
fuel_l = { column = "Fuel" }
total = { column = "Price (optional)", missing_values = ["0"] }
price_per_l = { column = "VolumePrice", missing_values = ["0"] }
full = { column = "Full", true_values = ["1"], false_values = ["0"], default = "true" }
missed_previous = { column = "Missed", true_values = ["1"], false_values = ["0"] }
station = { column = "City (optional)" }
notes = { column = "Notes (optional)" }
source_ref = { column = "UniqueId" }
"""

FUELIO_COSTS = """
name = "Fuelio costs"
[file]
section = "Costs"
[format]
distance_unit = "km"
[fields]
type = { value = "expense" }
date = { column = "Date" }
odometer_km = { column = "Odo", missing_values = ["0"] }
total = { column = "Cost" }
title = { column = "CostTitle" }
category = { column = "CostTitle", map = { maintenance = ["Oil change"], insurance = ["Policy 2024"] }, default = "other" }
notes = { column = "Notes" }
[[skip_rows]]
column = "isTemplate"
values = ["1"]
[[skip_rows]]
column = "isIncome"
values = ["1"]
"""


def preset(text: str):
    if "[format]" not in text:
        text = text.replace(
            "[fields]", '[format]\ndistance_unit = "km"\nvolume_unit = "l"\n[fields]', 1
        )
    return load_preset(text, id="test")


def run(preset_, data: bytes, answers: Answers | None = None):
    source = engine.read_file(data, preset_, answers)
    return engine.apply(preset_, source, answers)


def simple(extra_format: str = "", fields: str = "", file: str = ""):
    """A refuel preset over `d,odo,l,p,t` columns (units km and litres unless set)."""
    settings = {"distance_unit": "km", "volume_unit": "l"}
    for line in filter(None, extra_format.split("\n")):
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip().strip('"')
    format_text = "\n".join(f'{k} = "{v}"' for k, v in settings.items())
    return preset(
        f"""
name = "Simple"
{file}
[format]
{format_text}
[fields]
type = {{ value = "refuel" }}
date = {{ column = "d" }}
odometer_km = {{ column = "odo" }}
fuel_l = {{ column = "l" }}
price_per_l = {{ column = "p" }}
total = {{ column = "t" }}
{fields}
"""
    )


class TestHeaderMatching:
    def test_case_and_whitespace_ignored(self) -> None:
        assert engine.match_header("fuel  litres", " Fuel Litres ")

    def test_trailing_parenthesis_of_header_ignored(self) -> None:
        assert engine.match_header("Odo", "Odo (km)")

    def test_candidate_with_parenthesis_matches_only_itself(self) -> None:
        assert engine.match_header("Price (optional)", "Price (optional)")
        assert not engine.match_header("Price (optional)", "Price")
        assert not engine.match_header("Price (optional)", "Price (km)")

    def test_other_text_does_not_match(self) -> None:
        assert not engine.match_header("Odo", "Odometer")

    def test_candidates_are_tried_in_order(self) -> None:
        assert engine.find_column(["b", "a"], ["a", "b"]) == 1
        assert engine.find_column(["x"], ["a", "b"]) is None


class TestReadFile:
    def test_utf8_bom_and_comma(self) -> None:
        source = engine.read_file(b"\xef\xbb\xbfd,odo\n2024-01-01,5\n")
        table = source.tables[0]
        assert table.headers == ["d", "odo"]
        assert table.encoding == "utf-8" and table.delimiter == ","
        assert table.rows == [(2, ["2024-01-01", "5"])]

    def test_cp1252_fallback(self) -> None:
        source = engine.read_file("d;note\n2024-01-01;Straße\n".encode("cp1252"))
        table = source.tables[0]
        assert table.encoding == "cp1252" and table.delimiter == ";"
        assert table.rows[0][1][1] == "Straße"

    def test_forced_encoding_and_delimiter(self) -> None:
        data = "d|x\n1|2\n".encode("utf-16")
        source = engine.read_file(
            data, answers=Answers(encoding="utf-16", delimiter=";")
        )
        assert source.tables[0].headers == ["d|x"]

    def test_unknown_encoding_gives_no_tables(self) -> None:
        assert engine.read_file(b"a,b\n", answers=Answers(encoding="nope")).tables == []

    def test_tab_delimiter(self) -> None:
        assert engine.read_file(b"a\tb\n1\t2\n").tables[0].delimiter == "\t"

    def test_empty_and_garbage_do_not_raise(self) -> None:
        assert engine.read_file(b"").tables == []
        assert engine.read_file(b"PK\x03\x04garbage").tables == []
        engine.read_file(bytes(range(256)))

    def test_blank_lines_are_dropped_but_line_numbers_kept(self) -> None:
        table = engine.read_file(b"a,b\n\n1,2\n\n3,4\n").tables[0]
        assert [line for line, _ in table.rows] == [3, 5]

    def test_multiline_cell_keeps_line_numbers(self) -> None:
        table = engine.read_file(b'a,b\n"x\ny",2\n3,4\n').tables[0]
        assert [line for line, _ in table.rows] == [2, 4]

    def test_header_row_detected_below_preamble(self) -> None:
        data = b"Report,,\nexported today,,\nd,odo,l,p,t\n2024-01-01,10,5,1,5\n"
        source = engine.read_file(data, simple())
        table = source.tables[0]
        assert table.header_row == 3
        assert table.headers[:2] == ["d", "odo"]
        assert table.rows[0][0] == 4

    def test_header_row_override(self) -> None:
        data = b"d,odo,l,p,t\nd,odo,l,p,t\n2024-01-01,10,5,1,5\n"
        table = engine.read_file(data, simple(), Answers(header_row=2)).tables[0]
        assert table.header_row == 2 and table.rows[0][0] == 3

    def test_header_row_from_preset_file_settings(self) -> None:
        data = b"x\nd,odo,l,p,t\n2024-01-01,10,5,1,5\n"
        table = engine.read_file(data, simple(file="[file]\nheader_row = 2")).tables[0]
        assert table.headers[0] == "d"

    def test_header_within_first_twenty_rows_only(self) -> None:
        data = b"x\n" * 25 + b"d,odo,l,p,t\n2024-01-01,10,5,1,5\n"
        table = engine.read_file(data, simple()).tables[0]
        assert table.header_row == 1

    def test_delimiter_chosen_by_header_match(self) -> None:
        # The title line contains commas but the real header is semicolon-separated.
        data = b"Fuel log, 2024, mine\nd;odo;l;p;t\n2024-01-01;10;5;1;5\n"
        table = engine.read_file(data, simple()).tables[0]
        assert table.delimiter == ";" and table.headers[0] == "d"

    def test_sections_quoted_and_unquoted(self) -> None:
        data = (
            b'"## Vehicle"\n"Name"\n"Golf"\n## Log\nData,Odo\n2024-01-01,5\n'
            b'"## Costs"\nDate\n2024-02-02\n'
        )
        preset_ = replace(simple(), file=replace(simple().file, section="Log"))
        source = engine.read_file(data, preset_)
        assert source.sections == ["Vehicle", "Log", "Costs"]
        table = source.tables[0]
        assert table.headers == ["Data", "Odo"]
        assert table.rows == [(6, ["2024-01-01", "5"])]

    def test_missing_section_gives_no_tables(self) -> None:
        preset_ = replace(simple(), file=replace(simple().file, section="Nope"))
        source = engine.read_file(b"## Log\nd\n1\n", preset_)
        assert source.tables == [] and source.sections == ["Log"]

    def test_zip_members_are_tables_named_by_stem(self) -> None:
        data = _zip({"Golf.csv": "d,odo\n1,2\n", "Polo.csv": "d,odo\n3,4\n", "x.txt": "no"})
        source = engine.read_file(data)
        assert [t.name for t in source.tables] == ["Golf", "Polo"]
        assert not source.is_backup

    def test_zip_with_datapackage_is_a_backup(self) -> None:
        data = _zip({"records.csv": "a\n1\n", "datapackage.json": "{}"})
        source = engine.read_file(data)
        assert source.is_backup and [t.name for t in source.tables] == [""]

    def test_zip_ignores_directories_and_macos_junk(self) -> None:
        data = _zip({"__MACOSX/._a.csv": "x", "a.csv": "d\n1\n"})
        assert [t.name for t in engine.read_file(data).tables] == ["a"]


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


class TestScore:
    def test_full_match(self) -> None:
        data = b"d,odo,l,p,t\n2024-01-01,1,1,1,1\n"
        preset_ = simple()
        assert engine.score(preset_, engine.read_file(data, preset_)) == 1.0

    def test_partial_match(self) -> None:
        data = b"d,odo,x\n2024-01-01,1,1\n"
        preset_ = simple()
        assert engine.score(preset_, engine.read_file(data, preset_)) == pytest.approx(0.4)

    def test_missing_date_column_scores_zero(self) -> None:
        data = b"odo,l,p,t\n1,1,1,1\n"
        preset_ = simple()
        assert engine.score(preset_, engine.read_file(data, preset_)) == 0.0

    def test_missing_section_scores_zero(self) -> None:
        preset_ = preset(FUELIO_FILLUPS)
        source = engine.read_file(b"Data,Odo\n2024-01-01,1\n", preset_)
        assert engine.score(preset_, source) == 0.0

    def test_constants_do_not_count(self) -> None:
        preset_ = simple()
        data = b"d,odo,l,p,t\n2024-01-01,1,1,1,1\n"
        # `type` is a constant: five column fields, all found.
        assert len([m for m in preset_.fields.values() if m.columns]) == 5
        assert engine.score(preset_, engine.read_file(data, preset_)) == 1.0

    def test_standard_file_with_a_few_columns_is_recognised(self) -> None:
        data = b"type,vehicle,date,odometer_km,total,title\nexpense,A,2024-01-01,,5,x\n"
        assert engine.score(STANDARD, engine.read_file(data, STANDARD)) == 1.0

    def test_other_layout_does_not_look_like_standard(self) -> None:
        data = b"Data,Odo (km),Fuel (litres),Full\n2024-01-01,1,1,1\n"
        assert engine.score(STANDARD, engine.read_file(data, STANDARD)) == 0.0

    def test_fallback_preset_assigns_exact_names_only(self) -> None:
        data = b"date,type,Odo (km),notes\n2024-01-01,refuel,1,x\n"
        fallback = engine.fallback_preset(engine.read_file(data))
        assert set(fallback.fields) == {"date", "type", "notes"}
        assert fallback.id == ""


class TestNumbers:
    def test_decimal_comma_semicolon_file(self, fixtures_dir) -> None:
        preset_ = replace(STANDARD, format=replace(STANDARD.format, decimal_char=","))
        result = run(preset_, (fixtures_dir / "standard_semicolon_comma.csv").read_bytes())
        assert result.row_errors == [] and result.errors == []
        first, second = result.refuels
        assert (first.litres_milli, first.price_per_litre_milli, first.total_cents) == (
            45200, 1459, 6595,
        )  # fmt: skip
        assert (second.litres_milli, second.price_per_litre_milli, second.total_cents) == (
            40000, None, 5800,
        )  # fmt: skip
        assert result.expenses[0].amount_cents == 18050

    def test_decimal_comma_detected_automatically(self, fixtures_dir) -> None:
        data = (fixtures_dir / "standard_semicolon_comma.csv").read_bytes()
        fallback = engine.fallback_preset(engine.read_file(data))
        result = run(fallback, data)
        assert result.row_errors == [] and result.refuels[0].litres_milli == 45200

    def test_stray_separator_is_a_row_error_naming_the_value(self) -> None:
        data = b"d,odo,l,p,t\n2024-01-01,10,\"45,20\",,65.95\n2024-01-02,20,40.0,,60\n"
        result = run(simple('date_format = "%Y-%m-%d"\ndecimal_char = "."'), data)
        assert len(result.refuels) == 1
        (error,) = result.row_errors
        assert (error.line, error.field, error.value) == (2, "fuel_l", "45,20")
        assert "decimal separator" in error.message

    def test_thousands_separator_is_removed_when_set(self) -> None:
        data = b'd,odo,l,p,t\n2024-01-01,"12,500",40.0,,60\n'
        result = run(simple('group_char = ","\ndecimal_char = "."'), data)
        assert result.refuels[0].odometer_km == 12500.0

    def test_space_and_apostrophe_thousands(self) -> None:
        spaced = b"d,odo,l,p,t\n2024-01-01,12 500,40.0,,60\n"
        quoted = b"d,odo,l,p,t\n2024-01-01,13'500,40.0,,60\n"
        assert run(simple('group_char = " "'), spaced).refuels[0].odometer_km == 12500.0
        assert run(simple("group_char = \"'\""), quoted).refuels[0].odometer_km == 13500.0

    def test_dot_group_with_comma_decimal(self) -> None:
        data = b'd,odo,l,p,t\n2024-01-01,"12.500,5","40,0",,60\n'
        result = run(simple('group_char = "."\ndecimal_char = ","'), data)
        assert result.refuels[0].odometer_km == 12500.5

    def test_garbage_number_is_an_error(self) -> None:
        data = b"d,odo,l,p,t\n2024-01-01,abc,40,,60\n"
        (error,) = run(simple(), data).row_errors
        assert error.field == "odometer_km" and error.value == "abc"

    def test_negative_odometer_is_an_error(self) -> None:
        data = b"d,odo,l,p,t\n2024-01-01,-5,40,,60\n"
        assert run(simple(), data).row_errors[0].field == "odometer_km"


class TestDates:
    def test_ambiguous_dates_ask(self) -> None:
        data = b"d,odo,l,p,t\n01/02/2024,10,40,,60\n03/04/2024,20,40,,60\n"
        result = run(simple(), data)
        assert [q.kind for q in result.questions] == [QuestionKind.DATE_ORDER]
        assert result.questions[0].options == ("dmy", "mdy")
        assert result.refuels == []

    def test_answer_resolves_the_question(self) -> None:
        data = b"d,odo,l,p,t\n01/02/2024,10,40,,60\n03/04/2024,20,40,,60\n"
        dmy = run(simple(), data, Answers(date_order="dmy"))
        mdy = run(simple(), data, Answers(date_order="mdy"))
        assert dmy.questions == [] and dmy.refuels[0].date == date(2024, 2, 1)
        assert mdy.refuels[0].date == date(2024, 1, 2)

    def test_unambiguous_dates_do_not_ask(self) -> None:
        data = b"d,odo,l,p,t\n13/02/2024,10,40,,60\n03/04/2024,20,40,,60\n"
        result = run(simple(), data)
        assert result.questions == []
        assert result.refuels[1].date == date(2024, 4, 3)

    def test_iso_dates_do_not_ask(self) -> None:
        result = run(simple(), b"d,odo,l,p,t\n2024-01-02,10,40,,60\n")
        assert result.questions == [] and result.refuels[0].date == date(2024, 1, 2)

    def test_one_bad_date_is_a_row_error_not_a_blocker(self) -> None:
        rows = b"".join(
            b"%02d/03/2024,%d,40,,60\n" % (day, 100 * day) for day in (13, 14, 15)
        )
        data = b"d,odo,l,p,t\n" + rows + b"31/31/2024,5000,40,,60\n"
        result = run(simple(), data)
        assert len(result.refuels) == 3 and result.questions == []
        (error,) = result.row_errors
        assert (error.line, error.field, error.value) == (5, "date", "31/31/2024")

    def test_explicit_pattern(self) -> None:
        data = b"d,odo,l,p,t\n02.03.2024 14:05,10,40,,60\n"
        result = run(simple('date_format = "%d.%m.%Y %H:%M"'), data)
        refuel = result.refuels[0]
        assert refuel.date == date(2024, 3, 2) and refuel.time == time(14, 5)

    def test_explicit_pattern_mismatch_is_a_row_error(self) -> None:
        data = b"d,odo,l,p,t\n2024-03-02,10,40,,60\n"
        result = run(simple('date_format = "%d.%m.%Y"'), data)
        assert result.refuels == [] and result.row_errors[0].field == "date"

    def test_time_from_datetime_cell_and_from_time_column(self) -> None:
        data = b"d,tm,odo,l,p,t\n2024-03-02 08:15,,10,40,,60\n2024-03-03,19:45:10,20,40,,60\n"
        preset_ = preset(
            """
name = "T"
[fields]
type = { value = "refuel" }
date = { column = "d" }
time = { column = "tm" }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
total = { column = "t" }
"""
        )
        first, second = run(preset_, data).refuels
        assert first.time == time(8, 15) and second.time == time(19, 45, 10)

    def test_bad_time_is_a_row_error(self) -> None:
        preset_ = preset(
            """
name = "T"
[fields]
type = { value = "refuel" }
date = { column = "d" }
time = { column = "tm" }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
total = { column = "t" }
"""
        )
        result = run(preset_, b"d,tm,odo,l,t\n2024-03-02,25:99,10,40,60\n")
        assert result.row_errors[0].field == "time"


class TestUnits:
    def test_miles_from_header(self) -> None:
        preset_ = simple('distance_unit = "auto"\nvolume_unit = "l"')
        result = run(preset_, b"d,odo (mi),l,p,t\n2024-01-01,100,40,,60\n")
        assert result.refuels[0].odometer_km == pytest.approx(160.9344)

    def test_no_unit_in_header_asks(self) -> None:
        preset_ = simple('distance_unit = "auto"\nvolume_unit = "l"')
        result = run(preset_, b"d,odo,l,p,t\n2024-01-01,100,40,,60\n")
        assert [q.kind for q in result.questions] == [QuestionKind.DISTANCE_UNIT]
        answered = run(preset_, b"d,odo,l,p,t\n2024-01-01,100,40,,60\n", Answers(distance_unit="mi"))
        assert answered.questions == []
        assert answered.refuels[0].odometer_km == pytest.approx(160.9344)

    def test_ask_always_asks_both(self) -> None:
        preset_ = simple('distance_unit = "ask"\nvolume_unit = "ask"')
        result = run(preset_, b"d,odo,l,p,t\n2024-01-01,100,40,,60\n")
        assert {q.kind for q in result.questions} == {
            QuestionKind.DISTANCE_UNIT, QuestionKind.VOLUME_UNIT,
        }  # fmt: skip
        answered = run(
            preset_, b"d,odo,l,p,t\n2024-01-01,100,40,,60\n",
            Answers(distance_unit="km", volume_unit="gal_us"),
        )  # fmt: skip
        assert answered.questions == []

    def test_us_gallons_and_price_per_gallon(self) -> None:
        preset_ = simple('distance_unit = "mi"\nvolume_unit = "gal_us"')
        result = run(preset_, b"d,odo,l,p,t\n2024-04-01,1000,10.000,3.500,\n")
        refuel = result.refuels[0]
        assert refuel.litres_milli == 37854
        assert refuel.price_per_litre_milli == 925
        assert refuel.odometer_km == pytest.approx(1609.344)

    def test_uk_gallons(self) -> None:
        preset_ = simple('distance_unit = "km"\nvolume_unit = "gal_uk"')
        result = run(preset_, b"d,odo,l,p,t\n2024-04-01,1000,10.000,,50\n")
        assert result.refuels[0].litres_milli == 45461

    def test_volume_unit_from_header(self) -> None:
        preset_ = simple('distance_unit = "km"\nvolume_unit = "auto"')
        result = run(preset_, b"d,odo,l (US gal),p,t\n2024-04-01,1000,10,,50\n")
        assert result.refuels[0].litres_milli == 37854

    def test_answer_wins_over_nothing_but_header_unit_is_kept_without_answer(self) -> None:
        preset_ = simple('distance_unit = "auto"\nvolume_unit = "auto"')
        result = run(preset_, b"d,odo (km),l (litres),p,t\n2024-04-01,1000,10,,50\n")
        assert result.questions == []
        assert result.refuels[0].litres_milli == 10000


class TestFieldRules:
    def test_value_map_is_case_and_whitespace_insensitive(self) -> None:
        preset_ = preset(
            """
name = "E"
[fields]
type = { value = "expense" }
date = { column = "d" }
total = { column = "t" }
title = { column = "what" }
category = { column = "what", map = { maintenance = ["Oil change", "Service"] }, default = "other" }
"""
        )
        data = b"d,t,what\n2024-01-01,10,oil  CHANGE\n2024-01-02,5,Parking\n"
        first, second = run(preset_, data).expenses
        assert first.category == ExpenseCategory.MAINTENANCE and first.title == "oil  CHANGE"
        assert second.category == ExpenseCategory.OTHER

    def test_unlisted_value_without_default_is_a_row_error(self) -> None:
        preset_ = preset(
            """
name = "E"
[fields]
type = { value = "expense" }
date = { column = "d" }
total = { column = "t" }
title = { column = "what" }
category = { column = "what", map = { maintenance = ["Service"] } }
"""
        )
        result = run(preset_, b"d,t,what\n2024-01-01,10,Parking\n")
        assert result.expenses == []
        assert (result.row_errors[0].field, result.row_errors[0].value) == ("category", "Parking")

    def test_type_map_splits_one_file_into_both_types(self) -> None:
        preset_ = preset(
            """
name = "M"
[fields]
type = { column = "kind", map = { refuel = ["fuel"], expense = ["cost"] } }
date = { column = "d" }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
total = { column = "t" }
title = { column = "name" }
"""
        )
        data = b"kind,d,odo,l,t,name\nFuel,2024-01-01,10,40,60,\ncost,2024-01-02,,,25,Wash\n"
        result = run(preset_, data)
        assert (len(result.refuels), len(result.expenses)) == (1, 1)

    def test_boolean_lists_and_default(self) -> None:
        data = b"d,odo,l,p,t,part\n2024-01-01,1,40,,60,0\n2024-01-02,2,40,,60,1\n2024-01-03,3,40,,60,\n2024-01-04,4,40,,60,2\n"
        fields = 'full = { column = "part", true_values = ["0"], false_values = ["1"], default = "true" }'
        result = run(simple(fields=fields), data)
        assert [r.is_full for r in result.refuels] == [True, False, True, True]

    def test_boolean_unlisted_without_default_is_an_error(self) -> None:
        data = b"d,odo,l,p,t,part\n2024-01-01,1,40,,60,maybe\n"
        fields = 'full = { column = "part", true_values = ["0"], false_values = ["1"] }'
        result = run(simple(fields=fields), data)
        assert result.refuels == [] and result.row_errors[0].field == "full"

    def test_boolean_without_lists_accepts_plain_words(self) -> None:
        data = b"d,odo,l,p,t,f\n2024-01-01,1,40,,60,No\n2024-01-02,2,40,,60,true\n2024-01-03,3,40,,60,\n"
        result = run(simple(fields='full = { column = "f" }'), data)
        assert [r.is_full for r in result.refuels] == [False, True, True]

    def test_missed_previous_defaults_to_false(self) -> None:
        result = run(simple(), b"d,odo,l,p,t\n2024-01-01,1,40,,60\n")
        assert result.refuels[0].missed_previous is False

    def test_missing_values_count_as_empty(self) -> None:
        data = b"d,odo,l,p,t\n2024-01-01,1,40,0,60\n"
        result = run(simple(), data)
        # Without missing_values a price of 0 is read as 0 (the pipeline rejects it).
        assert result.refuels[0].price_per_litre_milli == 0
        preset_ = preset(
            """
name = "S"
[fields]
type = { value = "refuel" }
date = { column = "d" }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
price_per_l = { column = "p", missing_values = ["0"] }
total = { column = "t" }
"""
        )
        refuel = run(preset_, data).refuels[0]
        assert refuel.price_per_litre_milli is None and refuel.total_cents == 6000

    def test_default_for_empty_cell(self) -> None:
        fields = 'station = { column = "s", default = "Unknown" }'
        data = b"d,odo,l,p,t,s\n2024-01-01,1,40,,60,\n2024-01-02,2,40,,60,OMV\n"
        first, second = run(simple(fields=fields), data).refuels
        assert (first.station_name, second.station_name) == ("Unknown", "OMV")

    def test_one_column_may_feed_several_fields(self) -> None:
        fields = 'notes = { column = "s" }\nstation = { column = "s" }'
        result = run(simple(fields=fields), b"d,odo,l,p,t,s\n2024-01-01,1,40,,60,OMV\n")
        assert (result.refuels[0].notes, result.refuels[0].station_name) == ("OMV", "OMV")

    def test_candidate_columns_tried_in_order(self) -> None:
        preset_ = preset(
            """
name = "S"
[fields]
type = { value = "refuel" }
date = { column = ["date", "Data"] }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
total = { column = "t" }
"""
        )
        assert run(preset_, b"Data,odo,l,t\n2024-01-01,1,40,60\n").refuels

    def test_skip_rules_count_rows(self) -> None:
        text = """
name = "S"
[fields]
type = { value = "refuel" }
date = { column = "d" }
odometer_km = { column = "odo" }
fuel_l = { column = "l" }
total = { column = "t" }
[[skip_rows]]
column = "flag"
values = ["1", "x"]
"""
        data = b"d,odo,l,t,flag\n2024-01-01,1,40,60,0\n2024-01-02,2,40,60,1\n2024-01-03,3,40,60, X \n"
        result = run(preset(text), data)
        assert len(result.refuels) == 1 and result.skipped == 2

    def test_coverage_needs_both_dates(self) -> None:
        preset_ = preset(
            """
name = "E"
[fields]
type = { value = "expense" }
date = { column = "d" }
total = { column = "t" }
title = { column = "n" }
coverage_start = { column = "s" }
coverage_end = { column = "e" }
"""
        )
        data = b"d,t,n,s,e\n2024-01-01,5,Ins,2024-01-01,2024-12-31\n2024-01-02,5,Ins,2024-01-01,\n"
        result = run(preset_, data)
        assert result.expenses[0].coverage_end == date(2024, 12, 31)
        assert len(result.expenses) == 1 and result.row_errors[0].field == "coverage_end"

    def test_expense_needs_positive_amount_and_title(self) -> None:
        preset_ = preset(
            """
name = "E"
[fields]
type = { value = "expense" }
date = { column = "d" }
total = { column = "t" }
title = { column = "n" }
"""
        )
        data = b"d,t,n\n2024-01-01,0,A\n2024-01-02,5,\n2024-01-03,5,B\n"
        result = run(preset_, data)
        assert len(result.expenses) == 1
        assert [e.field for e in result.row_errors] == ["total", "title"]


class TestVehicleAndDerivation:
    def test_vehicle_column(self) -> None:
        result = run(
            simple(fields='vehicle = { column = "v" }'),
            b"d,odo,l,p,t,v\n2024-01-01,1,40,,60,Golf\n2024-01-02,2,40,,60,Polo\n",
        )
        assert [v.name for v in result.vehicles] == ["Golf", "Polo"]

    def test_zip_member_name_is_the_default_vehicle(self) -> None:
        data = _zip(
            {"Golf.csv": "d,odo,l,p,t\n2024-01-01,1,40,,60\n",
             "Polo.csv": "d,odo,l,p,t\n2024-01-01,1,30,,45\n"}
        )  # fmt: skip
        result = run(simple(), data)
        assert [r.vehicle_name for r in result.refuels] == ["Golf", "Polo"]

    def test_plain_csv_has_no_vehicle(self) -> None:
        result = run(simple(), b"d,odo,l,p,t\n2024-01-01,1,40,,60\n")
        assert result.refuels[0].vehicle_name is None and result.vehicles == []

    def test_two_of_three_leaves_the_third_for_the_pipeline(self) -> None:
        result = run(simple(), b"d,odo,l,p,t\n2024-01-01,1,40.000,,60.00\n")
        refuel = result.refuels[0]
        assert (refuel.litres_milli, refuel.price_per_litre_milli, refuel.total_cents) == (
            40000, None, 6000,
        )  # fmt: skip

    def test_a_missing_figure_is_not_an_engine_error(self) -> None:
        # Too few price figures are rejected by the pipeline (derive_price_figures).
        result = run(simple(), b"d,odo,l,p,t\n2024-01-01,1,40.000,,\n")
        assert result.row_errors == [] and result.refuels[0].total_cents is None

    def test_derived_marker_is_read(self, fixtures_dir) -> None:
        result = run(STANDARD, (fixtures_dir / "standard_records.csv").read_bytes())
        assert result.refuels[1].derived == DerivedField.PRICE_PER_LITRE
        assert result.refuels[0].derived is None


class TestBlockingErrors:
    def test_unmapped_required_fields_are_named(self) -> None:
        data = b"Datum,Km\n2024-01-01,5\n"
        result = run(STANDARD, data)
        assert result.refuels == [] and result.expenses == []
        text = " ".join(result.errors)
        assert "'type'" in text and "'date'" in text

    def test_unmapped_odometer_blocks_a_refuel_preset(self) -> None:
        preset_ = preset(
            """
name = "S"
[fields]
type = { value = "refuel" }
date = { column = "d" }
fuel_l = { column = "l" }
total = { column = "t" }
"""
        )
        result = run(preset_, b"d,l,t\n2024-01-01,40,60\n")
        assert any("odometer_km" in e for e in result.errors)

    def test_expense_preset_needs_title_and_total(self) -> None:
        preset_ = preset(
            """
name = "S"
[fields]
type = { value = "expense" }
date = { column = "d" }
"""
        )
        result = run(preset_, b"d\n2024-01-01\n")
        assert any("'total'" in e for e in result.errors)
        assert any("'title'" in e for e in result.errors)

    def test_no_tables(self) -> None:
        assert run(STANDARD, b"").errors

    def test_missing_section_message(self) -> None:
        preset_ = preset(FUELIO_FILLUPS)
        assert '"Log"' in run(preset_, b"a,b\n1,2\n").errors[0]


class TestStandardFixtures:
    def test_every_field_of_both_types(self, fixtures_dir) -> None:
        result = run(STANDARD, (fixtures_dir / "standard_records.csv").read_bytes())
        assert result.errors == [] and result.row_errors == [] and result.questions == []
        assert (len(result.refuels), len(result.expenses)) == (3, 2)
        first = result.refuels[0]
        assert first.vehicle_name == "Golf" and first.date == date(2026, 5, 2)
        assert first.time == time(14, 30) and first.odometer_km == 98000.0
        assert (first.litres_milli, first.price_per_litre_milli, first.total_cents) == (
            45200, 1459, 6595,
        )  # fmt: skip
        assert (first.station_name, first.station_location, first.station_brand) == (
            "OMV Celje", "Celje", "OMV",
        )  # fmt: skip
        assert first.is_full and not first.missed_previous
        assert (first.notes, first.source, first.source_ref) == ("First fill", "manual", "r1")
        second = result.refuels[1]
        assert not second.is_full and second.missed_previous
        assert second.source == "sample-preset"
        oil, insurance = result.expenses
        assert (oil.category, oil.title, oil.odometer_km, oil.amount_cents) == (
            ExpenseCategory.MAINTENANCE, "Oil change", 98400.0, 18000,
        )  # fmt: skip
        assert (insurance.coverage_start, insurance.coverage_end) == (
            date(2026, 1, 1), date(2026, 12, 31),
        )  # fmt: skip
        assert [v.name for v in result.vehicles] == ["Golf", "Polo"]

    def test_bad_rows_are_listed_with_line_numbers(self, fixtures_dir) -> None:
        result = run(STANDARD, (fixtures_dir / "standard_bad_rows.csv").read_bytes())
        assert (len(result.refuels), len(result.expenses)) == (3, 1)
        found = {(e.line, e.field) for e in result.row_errors}
        assert found == {
            (3, "date"), (4, "odometer_km"), (5, "odometer_km"), (6, "type"),
            (8, "total"), (12, "odometer_km"),
        }  # fmt: skip
        thousands = next(e for e in result.row_errors if e.line == 4)
        assert thousands.value == "98,500"
        # The refuel after the multi-line cell keeps its notes.
        assert result.refuels[2].notes == "two\nlines"


FUELIO_FILE = b"""\
"## Vehicle"
"Name","Description"
"Test Golf","x"
"## Log"
"Data","Odo (km)","Fuel (litres)","Full","Price (optional)","Missed","City (optional)","Notes (optional)","VolumePrice","UniqueId"
"2024-03-01 08:30","10000","40.000","1","60.00","0","Alpha Fuel","first","1.500","u1"
"2024-03-15 18:00","10600","20.000","0","31.00","0","Beta Oil","","1.550","u2"
"2024-04-02 12:00","11200","45.200","1","65.95","1","","","1.459","u3"
"2024-05-01 09:15","12000","72.604","1","3000.0","0","Alpha Fuel","","41.32","u4"
"## Costs"
"CostTitle","Date","Odo","CostTypeID","Notes","Cost","isTemplate","isIncome"
"Oil change","2024-03-20 10:00","10800","1","with filter","120.50","0","0"
"Policy 2024","2024-01-10 00:00","0","2","","400.00","0","0"
"Garage","2024-02-02 16:00","0","3","","5.00","0","0"
"Template service","2024-02-03 00:00","0","1","","99.00","1","0"
"Refund","2024-02-04 00:00","0","1","","50.00","0","1"
"Free check","2024-02-05 00:00","0","1","","0.00","0","0"
"""


class TestSectionedFile:
    def test_fillups_section(self) -> None:
        preset_ = preset(FUELIO_FILLUPS)
        result = run(preset_, FUELIO_FILE)
        assert result.errors == [] and result.row_errors == []
        assert len(result.refuels) == 4 and result.expenses == []
        first, second, third, fourth = result.refuels
        assert first.date == date(2024, 3, 1) and first.time == time(8, 30)
        assert first.odometer_km == 10000.0 and first.station_name == "Alpha Fuel"
        assert not second.is_full and third.missed_previous
        assert third.station_name is None
        assert (fourth.total_cents, fourth.price_per_litre_milli) == (300000, 41320)
        assert fourth.source_ref == "u4"

    def test_costs_section(self) -> None:
        preset_ = preset(FUELIO_COSTS)
        result = run(preset_, FUELIO_FILE)
        assert result.skipped == 2
        assert [e.title for e in result.expenses] == ["Oil change", "Policy 2024", "Garage"]
        assert [e.category.value for e in result.expenses] == [
            "maintenance", "insurance", "other",
        ]  # fmt: skip
        assert result.expenses[0].odometer_km == 10800.0
        assert result.expenses[1].odometer_km is None  # "0" is a missing value
        (error,) = result.row_errors
        assert (error.field, error.value) == ("total", "0.00")

    def test_line_numbers_count_the_whole_file(self) -> None:
        result = run(preset(FUELIO_COSTS), FUELIO_FILE)
        assert result.row_errors[0].line == 17

    def test_each_preset_scores_in_its_own_section_only(self) -> None:
        fillups, costs = preset(FUELIO_FILLUPS), preset(FUELIO_COSTS)
        assert engine.score(fillups, engine.read_file(FUELIO_FILE, fillups)) == 1.0
        assert engine.score(costs, engine.read_file(FUELIO_FILE, costs)) == 1.0
        std = engine.read_file(FUELIO_FILE, STANDARD)
        assert engine.score(STANDARD, std) < 0.5

    def test_single_hash_section_markers(self) -> None:
        data = b"\n#Vehicle\n\nname,model,\nCar,X,\n\n#Refueling\n\nDate,Odo\n2024-01-01,5\n"
        assert engine.read_file(data).sections == ["Vehicle", "Refueling"]
        wanted = preset('name = "W"\n[file]\nsection = "Refueling"\n[fields]\n'
                        'type = { value = "refuel" }\ndate = { column = "Date" }\n'
                        'odometer_km = { column = "Odo" }\n[format]\ndistance_unit = "km"\n')
        table = engine.read_file(data, wanted).tables[0]
        assert table.headers == ["Date", "Odo"] and len(table.rows) == 1


class TestWebExportQuirks:
    def test_percent_u_escapes_are_decoded(self) -> None:
        data = b"Date,Odo,Station\n2024-01-01,5,%u010Crpalka %u0160entvid %uD83D%uDE97\n"
        table = engine.read_file(data, STANDARD).tables[0]
        assert table.rows[0][1][2] == "Črpalka Šentvid \U0001f697"

    def test_quoted_header_after_spaces(self) -> None:
        data = b'"Date",  "Price / gal",  "Total cost"\n2024-01-01,1.5,30\n'
        table = engine.read_file(data, STANDARD).tables[0]
        assert table.headers == ["Date", "Price / gal", "Total cost"]


# --- zero_amount = "note" ---------------------------------------------------

ZERO_NOTE = load_preset(
    """
name = "Visits"
zero_amount = "note"
[format]
date_format = "%Y-%m-%d"
distance_unit = "km"
[fields]
type = { value = "expense" }
date = { column = "Date" }
odometer_km = { column = "Odo" }
title = { column = "Item" }
category = { value = "maintenance" }
total = { column = "Cost" }
notes = { column = "Notes" }
"""
)


def _visits(text: str, preset=ZERO_NOTE):
    data = ("Date,Odo,Item,Cost,Notes\n" + text).encode()
    return engine.apply(preset, engine.read_file(data, preset), Answers())


def test_free_items_are_appended_to_the_priced_item_of_the_visit() -> None:
    result = _visits(
        "2025-04-10,11500,Oil,48,\n2025-04-10,11500,Filter,0,\n"
        "2025-04-10,11500,Air filter,0,\n2025-04-10,11500,Filter,0,\n"
        "2025-04-10,11500,Wipers,25,Own note\n"
    )
    assert not result.errors and not result.row_errors and result.skipped == 0
    assert [e.title for e in result.expenses] == ["Oil", "Wipers"]
    assert result.expenses[0].notes == "Also: Filter, Air filter"
    assert result.expenses[1].notes == "Own note"


def test_free_item_is_added_after_existing_notes() -> None:
    result = _visits("2025-04-10,11500,Oil,48,Garage\n2025-04-10,11500,Filter,0,\n")
    assert result.expenses[0].notes == "Garage\nAlso: Filter"


def test_free_item_without_a_priced_item_of_its_visit_is_skipped() -> None:
    result = _visits(
        "2025-04-10,11500,Oil,48,\n2025-04-10,11600,Filter,0,\n2025-05-01,11500,Wash,0,\n"
    )
    assert [e.title for e in result.expenses] == ["Oil"]
    assert result.expenses[0].notes is None and result.skipped == 2


def test_zero_amount_is_an_error_by_default() -> None:
    plain = replace(ZERO_NOTE, zero_amount="error")
    result = _visits("2025-04-10,11500,Filter,0,\n", plain)
    assert len(result.row_errors) == 1
