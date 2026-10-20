"""Tests for services/records.py (fuel-records, expense-records, vehicles)."""

from __future__ import annotations

from datetime import date

import pytest

from autotracker.models import DerivedField, ExpenseCategory, Expense, Refuel
from autotracker.services.records import (
    ConfirmationRequired,
    ExpenseInput,
    NotFoundError,
    RefuelInput,
    StationInput,
    ValidationError,
    VehicleInput,
    archive_vehicle,
    count_vehicle_records,
    create_expense,
    create_refuel,
    create_station,
    create_vehicle,
    delete_station,
    delete_vehicle,
    derive_price_figures,
    list_expenses,
    list_refuels,
    list_stations,
    list_vehicles,
    merge_stations,
    preview_refuel,
    set_brand_bulk,
    update_expense,
    update_refuel,
    update_station,
    update_vehicle,
)
from autotracker.services.stats import StatsFilter


@pytest.fixture
def vehicle(session):
    return create_vehicle(session, VehicleInput(name="Golf"))


def refuel_input(vehicle_id, day=date(2026, 10, 1), odo=120500, **kw):
    kw.setdefault("litres_milli", 45200)
    kw.setdefault("price_per_litre_milli", 1459)
    return RefuelInput(vehicle_id=vehicle_id, date=day, odometer_km=odo, **kw)


# --- vehicles ---------------------------------------------------------------


def test_create_vehicle(session):
    created = create_vehicle(session, VehicleInput(name="Golf"))
    assert [v.name for v in list_vehicles(session)] == ["Golf"]
    assert created.id is not None


def test_duplicate_active_name_rejected(session, vehicle):
    with pytest.raises(ValidationError):
        create_vehicle(session, VehicleInput(name="Golf"))


def test_empty_name_rejected(session):
    with pytest.raises(ValidationError):
        create_vehicle(session, VehicleInput(name="  "))


def test_name_reusable_after_archive_and_restore_rechecked(session, vehicle):
    archive_vehicle(session, vehicle.id)
    second = create_vehicle(session, VehicleInput(name="Golf"))
    with pytest.raises(ValidationError):
        archive_vehicle(session, vehicle.id, archived=False)
    assert second.id != vehicle.id


def test_update_vehicle_keeps_own_name(session, vehicle):
    updated = update_vehicle(session, vehicle.id, VehicleInput(name="Golf", make="VW"))
    assert updated.make == "VW"


def test_archive_hides_from_default_list_but_keeps_records(session, vehicle):
    create_refuel(session, refuel_input(vehicle.id))
    archive_vehicle(session, vehicle.id)
    assert list_vehicles(session) == []
    assert len(list_vehicles(session, include_archived=True)) == 1
    assert len(list_refuels(session, StatsFilter(vehicles=(vehicle.id,)))) == 1


def test_delete_requires_confirmation(session, vehicle):
    create_refuel(session, refuel_input(vehicle.id))
    create_expense(
        session,
        ExpenseInput(vehicle.id, date(2026, 1, 1), ExpenseCategory.OTHER, 100),
    )
    assert count_vehicle_records(session, vehicle.id).refuels == 1
    with pytest.raises(ConfirmationRequired) as info:
        delete_vehicle(session, vehicle.id)
    assert (info.value.refuels, info.value.expenses) == (1, 1)
    delete_vehicle(session, vehicle.id, confirm=True)
    assert session.query(Refuel).count() == 0
    assert session.query(Expense).count() == 0
    with pytest.raises(NotFoundError):
        delete_vehicle(session, vehicle.id)


def test_delete_empty_vehicle_needs_no_confirmation(session, vehicle):
    delete_vehicle(session, vehicle.id)
    assert list_vehicles(session) == []


# --- price derivation -------------------------------------------------------


def test_save_full_refuel(session, vehicle):
    station = create_station(session, StationInput(name="Petrol Tržaška"))
    refuel = create_refuel(session, refuel_input(vehicle.id, station_id=station.id))
    assert refuel.total_cents == 6595
    assert refuel.is_full is True
    assert refuel.derived_field == DerivedField.TOTAL


def test_derive_price_per_litre():
    figures = derive_price_figures(40000, None, 6000)
    assert figures.price_per_litre_milli == 1500
    assert figures.derived_field == DerivedField.PRICE_PER_LITRE


def test_derive_litres():
    figures = derive_price_figures(None, 1500, 6000)
    assert figures.litres_milli == 40000
    assert figures.derived_field == DerivedField.LITRES


def test_all_three_given_not_derived():
    figures = derive_price_figures(40000, 1500, 7000)
    assert figures.derived_field is None
    assert figures.total_cents == 7000


@pytest.mark.parametrize("args", [(40000, None, None), (None, None, None)])
def test_fewer_than_two_rejected(args):
    with pytest.raises(ValidationError):
        derive_price_figures(*args)


@pytest.mark.parametrize("args", [(0, 1500, None), (40000, -1, None)])
def test_non_positive_rejected(args):
    with pytest.raises(ValidationError):
        derive_price_figures(*args)


def test_inconsistent_figures_warn_but_save(session, vehicle):
    data = refuel_input(
        vehicle.id, litres_milli=40000, price_per_litre_milli=1500, total_cents=7000
    )
    assert any("1 %" in w for w in preview_refuel(session, data).warnings)
    assert create_refuel(session, data).total_cents == 7000


def test_consistent_figures_no_warning(session, vehicle):
    data = refuel_input(
        vehicle.id, litres_milli=40000, price_per_litre_milli=1500, total_cents=6020
    )
    assert preview_refuel(session, data).warnings == []


def test_out_of_order_odometer_warns(session, vehicle):
    create_refuel(session, refuel_input(vehicle.id, date(2026, 9, 1), 120000))
    late = refuel_input(vehicle.id, date(2026, 9, 15), 119000)
    assert len(preview_refuel(session, late).warnings) == 1


def test_odometer_warning_for_later_dated_record_and_exclude(session, vehicle):
    later = create_refuel(session, refuel_input(vehicle.id, date(2026, 9, 15), 121000))
    early = refuel_input(vehicle.id, date(2026, 9, 1), 122000)
    assert len(preview_refuel(session, early).warnings) == 1
    assert preview_refuel(session, early, exclude_id=later.id).warnings == []


def test_update_refuel_rederives(session, vehicle):
    refuel = create_refuel(session, refuel_input(vehicle.id))
    updated = update_refuel(
        session,
        refuel.id,
        refuel_input(vehicle.id, litres_milli=40000, total_cents=6000,
                     price_per_litre_milli=None),
    )
    assert updated.price_per_litre_milli == 1500
    assert updated.derived_field == DerivedField.PRICE_PER_LITRE


# --- stations ---------------------------------------------------------------


def test_duplicate_station_with_null_location_rejected(session):
    create_station(session, StationInput(name="OMV"))
    with pytest.raises(ValidationError):
        create_station(session, StationInput(name="OMV"))
    create_station(session, StationInput(name="OMV", location="Celje"))


def test_update_station(session):
    station = create_station(session, StationInput(name="OMV"))
    updated = update_station(
        session, station.id, StationInput(name="OMV 2", brand="OMV")
    )
    assert (updated.name, updated.brand) == ("OMV 2", "OMV")


def test_merge_stations(session, vehicle):
    first = create_station(session, StationInput(name="PETROL Trzaska"))
    second = create_station(session, StationInput(name="Petrol Tržaška"))
    refuel = create_refuel(session, refuel_input(vehicle.id, station_id=first.id))
    merge_stations(session, first.id, second.id)
    session.refresh(refuel)
    assert refuel.station_id == second.id
    assert [s.id for s in list_stations(session)] == [second.id]


def test_bulk_brand(session):
    stations = [
        create_station(session, StationInput(name=f"S{i}")) for i in range(3)
    ]
    set_brand_bulk(session, [s.id for s in stations], "OMV")
    assert {s.brand for s in list_stations(session)} == {"OMV"}
    set_brand_bulk(session, [stations[0].id], None)
    assert stations[0].brand is None


def test_delete_station_keeps_refuels(session, vehicle):
    station = create_station(session, StationInput(name="OMV"))
    refuel = create_refuel(session, refuel_input(vehicle.id, station_id=station.id))
    delete_station(session, station.id)
    session.refresh(refuel)
    assert refuel.station_id is None


def test_filter_refuels_by_brand_and_newest_first(session, vehicle):
    mol = create_station(session, StationInput(name="M1", brand="MOL"))
    other = create_station(session, StationInput(name="O1", brand="OMV"))
    create_refuel(session, refuel_input(vehicle.id, date(2026, 1, 1), 1, station_id=mol.id))
    create_refuel(session, refuel_input(vehicle.id, date(2026, 2, 1), 2, station_id=mol.id))
    create_refuel(session, refuel_input(vehicle.id, date(2026, 3, 1), 3, station_id=other.id))
    rows = list_refuels(session, StatsFilter(brands=("MOL",)))
    assert [r.date.month for r in rows] == [2, 1]


# --- expenses ---------------------------------------------------------------


def test_record_insurance_payment(session, vehicle):
    expense = create_expense(
        session,
        ExpenseInput(
            vehicle.id, date(2026, 3, 1), ExpenseCategory.INSURANCE, 42000,
            title="Annual policy",
        ),
    )
    assert expense.category == ExpenseCategory.INSURANCE
    assert expense.amount_cents == 42000


def test_unknown_category_rejected(session, vehicle):
    with pytest.raises(ValidationError):
        create_expense(
            session, ExpenseInput(vehicle.id, date(2026, 3, 1), "parking", 500)
        )
    ok = create_expense(
        session,
        ExpenseInput(vehicle.id, date(2026, 3, 1), "other", 500, title="Parking"),
    )
    assert ok.category == ExpenseCategory.OTHER


def test_coverage_period_stored(session, vehicle):
    expense = create_expense(
        session,
        ExpenseInput(
            vehicle.id, date(2026, 3, 1), ExpenseCategory.INSURANCE, 42000,
            coverage_start=date(2026, 3, 1), coverage_end=date(2027, 2, 28),
        ),
    )
    assert expense.amount_cents == 42000
    assert expense.coverage_end == date(2027, 2, 28)


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 3, 1), None),
        (None, date(2026, 3, 1)),
        (date(2026, 3, 2), date(2026, 3, 1)),
    ],
)
def test_incomplete_or_reversed_coverage_rejected(session, vehicle, start, end):
    data = ExpenseInput(
        vehicle.id, date(2026, 3, 1), ExpenseCategory.INSURANCE, 100,
        coverage_start=start, coverage_end=end,
    )
    with pytest.raises(ValidationError):
        create_expense(session, data)


def test_same_day_coverage_allowed_and_update_validates(session, vehicle):
    data = ExpenseInput(
        vehicle.id, date(2026, 3, 1), ExpenseCategory.OTHER, 100,
        coverage_start=date(2026, 3, 1), coverage_end=date(2026, 3, 1),
    )
    expense = create_expense(session, data)
    bad = ExpenseInput(
        vehicle.id, date(2026, 3, 1), ExpenseCategory.OTHER, 100,
        coverage_start=date(2026, 3, 2), coverage_end=date(2026, 3, 1),
    )
    with pytest.raises(ValidationError):
        update_expense(session, expense.id, bad)


def test_filtered_expense_list(session, vehicle):
    for month, cat in [(1, "maintenance"), (2, "insurance"), (3, "maintenance")]:
        create_expense(
            session, ExpenseInput(vehicle.id, date(2026, month, 1), cat, 1000)
        )
    create_expense(
        session, ExpenseInput(vehicle.id, date(2025, 5, 1), "maintenance", 1000)
    )
    flt = StatsFilter(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        categories=(ExpenseCategory.MAINTENANCE,),
    )
    rows = list_expenses(session, flt)
    assert [e.date.month for e in rows] == [3, 1]
    assert sum(e.amount_cents for e in rows) == 2000
