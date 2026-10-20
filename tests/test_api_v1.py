"""Tests for ``/api/v1`` with the stats service stubbed out."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from autotracker.models import Vehicle
from autotracker.services import records, stats
from autotracker.services.stats import (
    Allocation,
    LastRefuel,
    Segment,
    StationStat,
    VehicleSummary,
)


@pytest.fixture
def vehicle_id(engine, client: TestClient) -> int:
    from autotracker.db import make_session_factory

    with make_session_factory(engine)() as s:
        v = Vehicle(name="Clio", make="Renault")
        s.add(v)
        s.commit()
        return v.id


def _summary(vid: int, allocation: Allocation, month: int = 0) -> VehicleSummary:
    return VehicleSummary(
        vehicle_id=vid,
        name="Clio",
        allocation=allocation,
        last_odometer_km=1000.0,
        last_refuel=LastRefuel(date(2026, 3, 1), 40500, 1799, 7285, "Petrol"),
        last_consumption=6.5,
        avg_consumption_12m=6.4,
        cost_this_month_cents=month,
        cost_this_year_cents=month,
        cost_per_km_12m=0.12,
    )


def test_list_vehicles(client, vehicle_id):
    body = client.get("/api/v1/vehicles").json()
    assert body == [
        {
            "id": vehicle_id,
            "name": "Clio",
            "make": "Renault",
            "model": None,
            "plate": None,
            "fuel_type": None,
        }
    ]


def test_summary_shape_pinned(client, vehicle_id, monkeypatch):
    monkeypatch.setattr(
        stats, "vehicle_summary", lambda s, v, t, a: _summary(v, a, 3100)
    )
    body = client.get(f"/api/v1/vehicles/{vehicle_id}/summary").json()
    assert body == {
        "vehicle_id": vehicle_id,
        "name": "Clio",
        "currency": "EUR",
        "allocation": "spread",
        "last_odometer_km": 1000.0,
        "last_refuel": {
            "date": "2026-03-01",
            "litres": 40.5,
            "price_per_litre": 1.799,
            "total": 72.85,
            "station": "Petrol",
        },
        "last_consumption": 6.5,
        "avg_consumption_12m": 6.4,
        "cost_this_month": 31.0,
        "cost_this_year": 31.0,
        "cost_per_km_12m": 0.12,
    }
    assert "next_service_due" not in body


@pytest.mark.parametrize("mode", ["spread", "paid"])
def test_allocation_passed_and_echoed(client, vehicle_id, monkeypatch, mode):
    seen = []

    def fake(s, v, t, a):
        seen.append(a)
        return _summary(v, a)

    monkeypatch.setattr(stats, "vehicle_summary", fake)
    body = client.get(f"/api/v1/vehicles/{vehicle_id}/summary?allocation={mode}").json()
    assert body["allocation"] == mode
    assert seen == [Allocation(mode)]


def test_allocation_default_is_spread(client, vehicle_id, monkeypatch):
    monkeypatch.setattr(stats, "vehicle_summary", lambda s, v, t, a: _summary(v, a))
    assert client.get(f"/api/v1/vehicles/{vehicle_id}/summary").json()["allocation"] == "spread"


def test_allocation_invalid_is_422(client, vehicle_id):
    assert client.get(f"/api/v1/vehicles/{vehicle_id}/summary?allocation=x").status_code == 422


def test_empty_vehicle_nulls_and_zero_costs(client, vehicle_id, monkeypatch):
    empty = VehicleSummary(vehicle_id, "Clio", Allocation.SPREAD, None, None, None, None, 0, 0, None)
    monkeypatch.setattr(stats, "vehicle_summary", lambda *a: empty)
    body = client.get(f"/api/v1/vehicles/{vehicle_id}/summary").json()
    assert body["last_odometer_km"] is None and body["last_refuel"] is None
    assert body["cost_this_month"] == 0 and body["cost_this_year"] == 0
    assert body["avg_consumption_12m"] is None and body["cost_per_km_12m"] is None


def test_unknown_vehicle_404_json(client):
    # Real service raises NotFoundError; stub it so this runs before group 2 lands.
    def raise_nf(*_a):
        raise records.NotFoundError("Vehicle 999 not found")

    import autotracker.services.stats as st

    st.vehicle_summary, original = raise_nf, st.vehicle_summary
    try:
        r = client.get("/api/v1/vehicles/999/summary")
    finally:
        st.vehicle_summary = original
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_consumption_unknown_vehicle_404(client, monkeypatch):
    monkeypatch.setattr(
        records, "get_vehicle", lambda s, i: (_ for _ in ()).throw(records.NotFoundError("x"))
    )
    assert client.get("/api/v1/vehicles/999/consumption").status_code == 404


def _seg(end: date, cons: float | None, valid: bool = True) -> Segment:
    return Segment(1, 1, 2, end, 5, True, 500.0, 32000, cons, valid, None if valid else "missed")


def test_consumption_filters_by_end_date(client, vehicle_id, monkeypatch):
    segs = [_seg(date(2026, 1, 10), 6.0), _seg(date(2026, 2, 10), 7.0), _seg(date(2026, 3, 10), None, False)]
    monkeypatch.setattr(records, "list_refuels", lambda s, f: [])
    monkeypatch.setattr(stats, "segments", lambda r: segs)
    monkeypatch.setattr(stats, "avg_consumption", lambda ss: 7.0 if len(ss) == 2 else 0.0)
    body = client.get(
        f"/api/v1/vehicles/{vehicle_id}/consumption?from=2026-02-01&to=2026-03-31"
    ).json()
    assert body["avg_consumption"] == 7.0
    assert [s["end_date"] for s in body["segments"]] == ["2026-02-10", "2026-03-10"]
    assert body["segments"][1]["valid"] is False
    assert body["segments"][1]["invalid_reason"] == "missed"
    assert set(body["segments"][0]) == {
        "end_date", "station_id", "distance_km", "litres", "consumption", "valid", "invalid_reason",
    }


def test_bad_date_and_reversed_range_422(client, vehicle_id):
    base = f"/api/v1/vehicles/{vehicle_id}/consumption"
    assert client.get(f"{base}?from=nope").status_code == 422
    assert client.get(f"{base}?from=2026-03-01&to=2026-01-01").status_code == 422


def test_station_stats_shape(client, vehicle_id, monkeypatch):
    row = StationStat(3, "Petrol A", 4, 160000, 1799, 1750, 1850, 6.2, 3)
    captured = {}

    def fake(session, flt, group_by):
        captured.update(flt=flt, group_by=group_by)
        return [row]

    monkeypatch.setattr(stats, "station_stats", fake)
    body = client.get(f"/api/v1/stations/stats?vehicle={vehicle_id}&from=2026-01-01").json()
    assert body["group_by"] == "station"
    assert body["stations"] == [
        {
            "key": 3, "label": "Petrol A", "fills": 4, "litres": 160.0,
            "avg_price_per_litre": 1.799, "min_price_per_litre": 1.75,
            "max_price_per_litre": 1.85, "consumption": 6.2, "consumption_segments": 3,
        }
    ]
    assert captured["flt"].vehicles == (vehicle_id,)
    assert captured["flt"].date_from == date(2026, 1, 1)


def test_station_stats_bad_group_by_422(client):
    assert client.get("/api/v1/stations/stats?group_by=x").status_code == 422


def test_ui_api_consistency(engine, client, vehicle_id):
    """API summary equals the service output for the same vehicle (UI uses it too)."""
    from autotracker.db import make_session_factory

    with make_session_factory(engine)() as s:
        try:
            expected = stats.vehicle_summary(s, vehicle_id, date.today())
        except NotImplementedError:
            pytest.skip("stats service not implemented yet")
    body = client.get(f"/api/v1/vehicles/{vehicle_id}/summary").json()
    assert body["avg_consumption_12m"] == expected.avg_consumption_12m
    assert body["cost_this_month"] == round(expected.cost_this_month_cents / 100, 2)
    assert body["cost_this_year"] == round(expected.cost_this_year_cents / 100, 2)
