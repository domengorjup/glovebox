"""Tests for the shared locale helpers in importers/base.py (task 3.1)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, time
from decimal import Decimal

import pytest

from glovebox.importers import base


class TestEncoding:
    def test_utf8(self) -> None:
        assert base.decode_text("Škoda".encode("utf-8")) == "Škoda"

    def test_utf8_bom_is_removed(self) -> None:
        assert base.decode_text(b"\xef\xbb\xbfDate,Odo") == "Date,Odo"

    def test_cp1252_fallback(self) -> None:
        assert base.decode_text("Citroën".encode("cp1252")) == "Citroën"


class TestDelimiter:
    @pytest.mark.parametrize("delimiter", [",", ";", "\t"])
    def test_sniffs_each_delimiter(self, delimiter: str) -> None:
        text = delimiter.join(["Date", "Odo", "Litres"]) + "\n1,5\n"
        assert base.sniff_delimiter(text) == delimiter

    def test_decimal_commas_in_data_do_not_mislead(self) -> None:
        text = "Date;Odo;Litres\n2024-01-01;1000;45,20\n"
        assert base.sniff_delimiter(text) == ";"

    def test_quoted_delimiter_in_header_is_ignored(self) -> None:
        assert base.sniff_delimiter('"Price, total";"Odo"\n') == ";"


class TestNumbers:
    def test_decimal_comma(self) -> None:
        decimal = base.detect_decimal_separator(["45,20", "10,5"])
        assert decimal == ","
        assert base.parse_number("45,20", decimal) == Decimal("45.20")

    def test_decimal_point(self) -> None:
        assert base.detect_decimal_separator(["45.20", "3.5"]) == "."

    def test_thousands_with_decimal_comma(self) -> None:
        decimal = base.detect_decimal_separator(["1.234,56"])
        assert base.parse_number("1.234,56", decimal) == Decimal("1234.56")

    def test_thousands_with_decimal_point(self) -> None:
        decimal = base.detect_decimal_separator(["1,234.56"])
        assert base.parse_number("1,234.56", decimal) == Decimal("1234.56")

    def test_three_decimals_decided_by_column(self) -> None:
        # "40,000" alone is ambiguous, but another value settles the column.
        assert base.detect_decimal_separator(["40,000", "12,5"]) == ","
        assert base.detect_decimal_separator(["40.000", "12.5"]) == "."

    def test_empty_is_none_and_garbage_raises(self) -> None:
        assert base.parse_number("  ") is None
        with pytest.raises(ValueError):
            base.parse_number("abc")

    def test_currency_symbol_ignored(self) -> None:
        assert base.parse_number("€ 65,95", ",") == Decimal("65.95")

    def test_scale_to_int_rounds_half_up(self) -> None:
        assert base.scale_to_int(Decimal("37.8541"), 1000) == 37854
        assert base.scale_to_int(Decimal("0.0005"), 1000) == 1


class TestDates:
    def test_iso_is_unambiguous(self) -> None:
        detection = base.detect_date_order(["2024-03-04", "2024-04-05 10:30"])
        assert detection == base.DateDetection("ymd", False)

    def test_day_first_when_a_value_exceeds_twelve(self) -> None:
        assert base.detect_date_order(["03/04/2024", "15/04/2024"]).order == "dmy"

    def test_month_first_when_second_exceeds_twelve(self) -> None:
        assert base.detect_date_order(["03/04/2024", "04/15/2024"]).order == "mdy"

    def test_ambiguous(self) -> None:
        detection = base.detect_date_order(["03/04/2024", "05/06/2024"])
        assert detection.ambiguous and detection.order is None

    def test_answer_resolves_ambiguity(self) -> None:
        values = ["03/04/2024", "05/06/2024"]
        assert base.resolve_date_order(values, "mdy").order == "mdy"

    def test_answer_cannot_contradict_data(self) -> None:
        detection = base.resolve_date_order(["15/04/2024"], "mdy")
        assert detection.order == "dmy"

    def test_unrecognised(self) -> None:
        assert base.detect_date_order(["yesterday"]) == base.DateDetection(None)

    def test_parse_with_time_and_dots(self) -> None:
        assert base.parse_date_value("04.03.2024 08:05", "dmy") == (
            date(2024, 3, 4),
            time(8, 5),
        )

    def test_two_digit_year(self) -> None:
        assert base.parse_date_value("3/4/24", "mdy") == (date(2024, 3, 4), None)

    def test_impossible_date(self) -> None:
        assert base.parse_date_value("2024-02-30", "ymd") is None


class TestAliases:
    def test_matching_ignores_case_and_whitespace(self, tmp_path) -> None:
        (tmp_path / "x.toml").write_text(
            '[meta]\nprovisional = true\n[t]\nodo = ["Odometer", "Km  Stand"]\n'
        )
        table = base.load_aliases("x", tmp_path)
        assert table.provisional
        assert table.match("t", ["Date", " km STAND "]) == {"odo": 1}

    def test_lookup_is_reverse_and_normalised(self, tmp_path) -> None:
        (tmp_path / "x.toml").write_text('[c]\ninsurance = ["Car  Insurance"]\n')
        table = base.load_aliases("x", tmp_path)
        assert table.lookup("c", "car insurance") == "insurance"
        assert table.lookup("c", "parking") is None

    @pytest.mark.parametrize("name", ["drivvo", "fuelio", "fuelly"])
    def test_shipped_files_load(self, name: str) -> None:
        assert base.load_aliases(name).sections

    def test_drivvo_is_marked_provisional(self) -> None:
        assert base.load_aliases("drivvo").provisional


def test_leading_zip_member_reads_name_and_content() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.csv", "## Log\n" * 50)
    name, content = base.leading_zip_member(buffer.getvalue()[:200])
    assert name == "a.csv"
    assert content.startswith(b"## Log")
