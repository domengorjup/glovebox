"""Period ranges and comparison ranges of the Timeline summary (pure date maths)."""

from __future__ import annotations

from datetime import date

import pytest

from glovebox.services import periods

TODAY = date(2026, 10, 20)


def test_this_month_compares_with_the_same_days_of_last_month() -> None:
    period = periods.resolve("month", date(2026, 10, 10))
    assert (period.start, period.end) == (date(2026, 10, 1), date(2026, 10, 10))
    assert period.previous == (date(2026, 9, 1), date(2026, 9, 10))
    assert period.previous_text == "September"


def test_this_month_comparison_is_clamped_at_the_end_of_a_short_month() -> None:
    # 31 March against 1-28 February (not a leap year)
    period = periods.resolve("month", date(2026, 3, 31))
    assert period.previous == (date(2026, 2, 1), date(2026, 2, 28))
    # and 1-29 February in a leap year
    assert periods.resolve("month", date(2028, 3, 31)).previous == (
        date(2028, 2, 1), date(2028, 2, 29))  # fmt: skip
    # 31 October against 1-30 September
    assert periods.resolve("month", date(2026, 10, 31)).previous == (
        date(2026, 9, 1), date(2026, 9, 30))  # fmt: skip


def test_this_month_in_january_compares_with_december() -> None:
    period = periods.resolve("month", date(2027, 1, 15))
    assert period.previous == (date(2026, 12, 1), date(2026, 12, 15))
    assert period.previous_text == "December"


def test_this_year_compares_with_the_same_days_of_last_year() -> None:
    period = periods.resolve("year", TODAY)
    assert (period.start, period.end) == (date(2026, 1, 1), TODAY)
    assert period.previous == (date(2025, 1, 1), date(2025, 10, 20))
    assert period.previous_text == "same days in 2025"


def test_this_year_on_a_leap_day_uses_28_february_of_last_year() -> None:
    period = periods.resolve("year", date(2028, 2, 29))
    assert period.previous == (date(2027, 1, 1), date(2027, 2, 28))


def test_last_30_days_includes_today_and_compares_with_the_30_before() -> None:
    period = periods.resolve("30d", TODAY)
    assert (period.start, period.end) == (date(2026, 9, 21), TODAY)
    assert period.previous == (date(2026, 8, 22), date(2026, 9, 20))
    assert period.previous_text == "previous 30 days"


def test_last_12_months_is_the_window_of_the_vehicle_summary() -> None:
    period = periods.resolve("12m", TODAY)
    assert (period.start, period.end) == (date(2025, 10, 21), TODAY)
    # 365 days before the window, ending the day before it
    assert period.previous == (date(2024, 10, 21), date(2025, 10, 20))


def test_last_12_months_on_a_leap_day() -> None:
    period = periods.resolve("12m", date(2028, 2, 29))
    assert period.start == date(2027, 3, 1)


def test_all_time_starts_at_the_first_record_and_has_no_comparison() -> None:
    period = periods.resolve("all", TODAY, first_record=date(2024, 5, 3))
    assert (period.start, period.end) == (date(2024, 5, 3), TODAY)
    assert period.previous is None
    assert periods.resolve("all", TODAY).start == TODAY


def test_custom_range_is_compared_with_the_range_of_equal_length_before() -> None:
    period = periods.resolve(
        "custom", TODAY, custom_from=date(2026, 6, 1), custom_to=date(2026, 6, 30))
    assert period.previous == (date(2026, 5, 2), date(2026, 5, 31))
    assert period.previous_text == "previous 30 days"


def test_custom_range_with_reversed_dates_is_swapped() -> None:
    period = periods.resolve(
        "custom", TODAY, custom_from=date(2026, 6, 30), custom_to=date(2026, 6, 1))
    assert (period.start, period.end) == (date(2026, 6, 1), date(2026, 6, 30))


def test_custom_range_without_dates_falls_back_to_30_days() -> None:
    assert periods.resolve("custom", TODAY).key == "30d"


@pytest.mark.parametrize("key", ["", "bogus", "week"])
def test_unknown_period_is_last_12_months(key: str) -> None:
    assert periods.resolve(key, TODAY).key == "12m"
