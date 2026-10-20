"""Tests for services/stats.py (statistics and stats-api summary specs)."""

from __future__ import annotations

from datetime import date

import pytest

from autotracker.models import Expense, ExpenseCategory, Refuel, Station, Vehicle
from autotracker.services.records import NotFoundError
from autotracker.services.stats import (
    Allocation,
    GroupBy,
    StatsFilter,
    avg_consumption,
    cost_breakdown,
    cost_per_km,
    segments,
    station_stats,
    vehicle_summary,
)

INS = ExpenseCategory.INSURANCE


@pytest.fixture
def vid(session) -> int:
    vehicle = Vehicle(name="Golf", archived=False)
    session.add(vehicle)
    session.flush()
    return vehicle.id


def fill(session, vid, odo, litres, day=date(2026, 1, 1), full=True, missed=False,
         station=None, price=1500):
    refuel = Refuel(
        vehicle_id=vid, date=day, odometer_km=odo, litres_milli=int(litres * 1000),
        price_per_litre_milli=price, total_cents=round(litres * price / 10),
        is_full=full, missed_previous=missed, station_id=station,
    )
    session.add(refuel)
    session.flush()
    return refuel


def expense(session, vid, day, amount, cat=INS, start=None, end=None, odo=None):
    item = Expense(
        vehicle_id=vid, date=day, category=cat, title="x", amount_cents=amount,
        coverage_start=start, coverage_end=end, odometer_km=odo,
    )
    session.add(item)
    session.flush()
    return item


def station(session, name, brand=None):
    item = Station(name=name, brand=brand)
    session.add(item)
    session.flush()
    return item.id


# --- consumption -------------------------------------------------------------


def test_partial_fill_included_in_segment(session, vid):
    fill(session, vid, 1000, 40)
    fill(session, vid, 1200, 10, full=False)
    fill(session, vid, 1600, 30)
    last = segments(session.query(Refuel).all())[-1]
    assert last.valid and last.distance_km == 600 and last.litres_milli == 40000
    assert last.consumption == pytest.approx(6.6667, abs=1e-3)


def test_missed_fill_invalidates_segment(session, vid):
    fill(session, vid, 1000, 40)
    fill(session, vid, 1600, 30, missed=True)
    segs = segments(session.query(Refuel).all())
    assert segs[-1].valid is False
    assert segs[-1].invalid_reason == "missed"
    assert segs[-1].consumption is None
    assert avg_consumption(segs) is None


def test_missed_flag_on_partial_inside_segment_invalidates(session, vid):
    fill(session, vid, 1000, 40)
    fill(session, vid, 1200, 10, full=False, missed=True)
    fill(session, vid, 1600, 30)
    assert segments(session.query(Refuel).all())[-1].invalid_reason == "missed"


def test_first_fill_has_no_consumption(session, vid):
    fill(session, vid, 1000, 40)
    segs = segments(session.query(Refuel).all())
    assert len(segs) == 1 and segs[0].invalid_reason == "no_previous_full"
    assert avg_consumption(segs) is None


def test_non_positive_distance_invalid(session, vid):
    fill(session, vid, 1000, 40)
    fill(session, vid, 1000, 30)
    assert segments(session.query(Refuel).all())[-1].invalid_reason == (
        "non_positive_distance"
    )


def test_unsorted_input_is_sorted(session, vid):
    a = fill(session, vid, 1600, 30)
    b = fill(session, vid, 1000, 40)
    segs = segments([a, b])
    assert segs[-1].end_refuel_id == a.id


def test_weighted_average(session, vid):
    fill(session, vid, 0, 50)
    fill(session, vid, 200, 20)
    fill(session, vid, 1200, 60)
    segs = segments(session.query(Refuel).all())
    assert avg_consumption(segs) == pytest.approx(80 / 1200 * 100)


# --- allocation ---------------------------------------------------------------


def monthly(breakdown):
    return {p.period: p.by_category[INS] for p in breakdown.monthly}


def test_yearly_insurance_spread_over_12_months(session, vid):
    expense(session, vid, date(2026, 3, 1), 36500, start=date(2026, 3, 1),
            end=date(2027, 2, 28))
    result = cost_breakdown(session, StatsFilter())
    parts = monthly(result)
    assert len(parts) == 12
    assert parts["2026-03"] == 3100
    assert parts["2026-04"] == 3000
    assert parts["2027-02"] == 2800
    assert sum(parts.values()) == 36500
    assert result.by_category[INS] == 36500


def test_largest_remainder_sums_exactly(session, vid):
    expense(session, vid, date(2026, 1, 1), 10001, start=date(2026, 1, 1),
            end=date(2026, 12, 31))
    assert sum(monthly(cost_breakdown(session, StatsFilter())).values()) == 10001


def test_payment_without_coverage_same_in_both_modes(session, vid):
    expense(session, vid, date(2026, 5, 10), 12000, cat=ExpenseCategory.REGISTRATION)
    for mode in Allocation:
        result = cost_breakdown(session, StatsFilter(), mode)
        assert [(p.period, p.by_category[ExpenseCategory.REGISTRATION])
                for p in result.monthly] == [("2026-05", 12000)]


def test_coverage_crossing_year_boundary(session, vid):
    expense(session, vid, date(2026, 7, 1), 36500, start=date(2026, 7, 1),
            end=date(2027, 6, 30))
    yearly = {p.period: p.by_category[INS]
              for p in cost_breakdown(session, StatsFilter()).yearly}
    assert yearly == {"2026": 18400, "2027": 18100}


def test_as_paid_shows_full_payment_in_payment_month(session, vid):
    expense(session, vid, date(2026, 3, 1), 42000, start=date(2026, 3, 1),
            end=date(2027, 2, 28))
    result = cost_breakdown(session, StatsFilter(), Allocation.PAID)
    assert monthly(result) == {"2026-03": 42000}
    assert result.allocation is Allocation.PAID


def test_spread_period_gets_only_in_period_share(session, vid):
    expense(session, vid, date(2026, 3, 1), 36500, start=date(2026, 3, 1),
            end=date(2027, 2, 28))
    flt = StatsFilter(date_from=date(2026, 4, 1), date_to=date(2026, 5, 31))
    assert cost_breakdown(session, flt).by_category[INS] == 3000 + 3100
    # as paid: the payment date (March) is outside the period
    assert cost_breakdown(session, flt, Allocation.PAID).by_category[INS] == 0


def test_spread_expense_paid_before_range_still_counts(session, vid):
    expense(session, vid, date(2025, 12, 1), 36500, start=date(2026, 1, 1),
            end=date(2026, 12, 31))
    flt = StatsFilter(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert cost_breakdown(session, flt).by_category[INS] == 3100


def test_toggle_leaves_data_unchanged(session, vid):
    item = expense(session, vid, date(2026, 3, 1), 36500, start=date(2026, 3, 1),
                   end=date(2027, 2, 28))
    cost_breakdown(session, StatsFilter(), Allocation.SPREAD)
    cost_breakdown(session, StatsFilter(), Allocation.PAID)
    assert not session.dirty and not session.new
    session.refresh(item)
    assert (item.amount_cents, item.coverage_start, item.coverage_end) == (
        36500, date(2026, 3, 1), date(2027, 2, 28))
    assert cost_breakdown(session, StatsFilter()).allocation is Allocation.SPREAD


def test_fuel_never_spread_and_category_totals(session, vid):
    fill(session, vid, 100, 40, day=date(2026, 2, 3))
    expense(session, vid, date(2026, 2, 5), 20000, cat=ExpenseCategory.MAINTENANCE)
    for mode in Allocation:
        result = cost_breakdown(session, StatsFilter(), mode)
        assert result.fuel_cents == 6000
        assert result.by_category[ExpenseCategory.MAINTENANCE] == 20000
        assert result.total_cents == 26000
        assert result.monthly[0].total_cents == 26000


def test_category_and_vehicle_filter(session, vid):
    expense(session, vid, date(2026, 2, 5), 100, cat=ExpenseCategory.MAINTENANCE)
    expense(session, vid, date(2026, 2, 5), 200, cat=INS)
    flt = StatsFilter(vehicles=(vid,), categories=(INS,))
    assert cost_breakdown(session, flt).total_cents == 200
    assert cost_breakdown(session, StatsFilter(vehicles=(vid + 1,))).total_cents == 0


# --- cost per km ---------------------------------------------------------------


def test_cost_per_km(session, vid):
    fill(session, vid, 10000, 50, day=date(2026, 1, 5), price=6000)  # 300 EUR
    fill(session, vid, 15000, 1, day=date(2026, 2, 5), price=0)
    expense(session, vid, date(2026, 1, 20), 20000, cat=ExpenseCategory.MAINTENANCE,
            odo=12000)
    result = cost_per_km(session, StatsFilter())
    assert result.distance_km == 5000
    assert result.total_cents == 50000
    assert result.per_km == pytest.approx(0.10)


def test_cost_per_km_none_without_distance(session, vid):
    fill(session, vid, 10000, 50)
    assert cost_per_km(session, StatsFilter()).per_km is None
    assert cost_per_km(session, StatsFilter(vehicles=(999,))).distance_km is None


def test_cost_per_km_follows_allocation(session, vid):
    fill(session, vid, 0, 1, day=date(2026, 3, 1), price=0)
    fill(session, vid, 1000, 1, day=date(2026, 3, 31), price=0)
    expense(session, vid, date(2026, 3, 1), 36500, start=date(2026, 3, 1),
            end=date(2027, 2, 28))
    flt = StatsFilter(date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))
    assert cost_per_km(session, flt, Allocation.SPREAD).per_km == pytest.approx(0.031)
    assert cost_per_km(session, flt, Allocation.PAID).per_km == pytest.approx(0.365)


# --- stations ---------------------------------------------------------------


def test_litre_weighted_price_min_max(session, vid):
    s = station(session, "A")
    fill(session, vid, 1, 10, station=s, price=1500)
    fill(session, vid, 2, 30, station=s, price=1400)
    (stat,) = station_stats(session, StatsFilter())
    assert stat.avg_price_per_litre_milli == 1425
    assert (stat.min_price_per_litre_milli, stat.max_price_per_litre_milli) == (1400, 1500)
    assert stat.fills == 2 and stat.litres_milli == 40000


def test_station_consumption_needs_two_single_source_segments(session, vid):
    a, b = station(session, "A"), station(session, "B")
    fill(session, vid, 0, 40, station=a)
    fill(session, vid, 500, 30, station=a)
    fill(session, vid, 1000, 30, station=a)
    stats = {s.key: s for s in station_stats(session, StatsFilter())}
    assert stats[a].consumption_segments == 2
    assert stats[a].consumption == pytest.approx(60 / 1000 * 100)
    assert stats.get(b) is None


def test_below_two_segments_is_na(session, vid):
    a = station(session, "A")
    fill(session, vid, 0, 40, station=a)
    fill(session, vid, 500, 30, station=a)
    (stat,) = station_stats(session, StatsFilter())
    assert stat.consumption is None and stat.consumption_segments == 1


def test_mixed_station_segment_excluded(session, vid):
    a, b = station(session, "A"), station(session, "B")
    fill(session, vid, 0, 40, station=a)
    fill(session, vid, 300, 10, full=False, station=a)
    fill(session, vid, 600, 30, station=b)
    fill(session, vid, 1100, 30, station=b)
    fill(session, vid, 1600, 30, station=b)
    stats = {s.key: s for s in station_stats(session, StatsFilter())}
    assert stats[a].consumption_segments == 0
    assert stats[b].consumption_segments == 2  # the mixed one is not counted


def test_group_by_brand(session, vid):
    a = station(session, "A", "MOL")
    b = station(session, "B", "MOL")
    c = station(session, "C")
    fill(session, vid, 0, 40, station=a)
    fill(session, vid, 500, 30, station=b)
    fill(session, vid, 1000, 30, station=a)
    fill(session, vid, 1500, 30, station=c)
    stats = {s.key: s for s in station_stats(session, StatsFilter(), GroupBy.BRAND)}
    assert stats["MOL"].fills == 3 and stats["MOL"].consumption_segments == 2
    assert stats[None].label == "(no brand)"
    assert stats[None].consumption is None


def test_station_filter_by_date_range(session, vid):
    a = station(session, "A")
    fill(session, vid, 0, 40, day=date(2025, 1, 1), station=a)
    fill(session, vid, 500, 30, day=date(2025, 2, 1), station=a)
    fill(session, vid, 1000, 30, day=date(2026, 2, 1), station=a)
    flt = StatsFilter(date_from=date(2026, 1, 1))
    (stat,) = station_stats(session, flt)
    assert stat.fills == 1 and stat.consumption_segments == 1


# --- summary -------------------------------------------------------------------


def test_summary_for_empty_vehicle(session, vid):
    s = vehicle_summary(session, vid, date(2026, 3, 15))
    assert s.name == "Golf"
    assert s.last_odometer_km is None and s.last_refuel is None
    assert s.last_consumption is None and s.avg_consumption_12m is None
    assert s.cost_per_km_12m is None
    assert s.cost_this_month_cents == 0 and s.cost_this_year_cents == 0


def test_summary_unknown_vehicle(session):
    with pytest.raises(NotFoundError):
        vehicle_summary(session, 999, date(2026, 3, 15))


def test_summary_allocation_parameter(session, vid):
    expense(session, vid, date(2026, 3, 1), 36500, start=date(2026, 3, 1),
            end=date(2027, 2, 28))
    today = date(2026, 3, 15)
    assert vehicle_summary(session, vid, today).cost_this_month_cents == 3100
    paid = vehicle_summary(session, vid, today, Allocation.PAID)
    assert paid.cost_this_month_cents == 36500
    assert paid.allocation is Allocation.PAID


def test_summary_values(session, vid):
    s = station(session, "Petrol")
    fill(session, vid, 1000, 40, day=date(2025, 1, 1))
    fill(session, vid, 1600, 30, day=date(2026, 2, 1))
    fill(session, vid, 2200, 36, day=date(2026, 3, 1), station=s, price=1500)
    expense(session, vid, date(2026, 3, 2), 100, odo=2300)
    summary = vehicle_summary(session, vid, date(2026, 3, 15))
    assert summary.last_odometer_km == 2300
    assert summary.last_refuel.station_name == "Petrol"
    assert summary.last_refuel.litres_milli == 36000
    assert summary.last_consumption == pytest.approx(6.0)
    # the 2025 fill is outside the 12-month window; two segments inside
    assert summary.avg_consumption_12m == pytest.approx(66 / 1200 * 100)
    assert summary.cost_this_month_cents == 5400 + 100
