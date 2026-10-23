"""The standard format definition and its Data Package descriptor."""

from __future__ import annotations

import json

from glovebox import standard

RECORD_COLUMNS = [
    "type", "vehicle", "date", "time", "odometer_km", "odometer_estimated", "fuel_l", "price_per_l",
    "total", "currency", "full", "missed_previous", "station",
    "station_location", "station_brand", "category", "title", "coverage_start",
    "coverage_end", "notes", "derived", "source", "source_ref",
]


def test_record_field_order() -> None:
    assert [f.name for f in standard.RECORD_FIELDS] == RECORD_COLUMNS


def test_backup_table_columns() -> None:
    assert [f.name for f in standard.VEHICLE_FIELDS] == [
        "name", "make", "model", "plate", "fuel_type", "initial_odometer_km",
        "archived", "notes", "vin", "model_year", "engine", "tyre_size",
        "insurance_policy", "insurance_valid_until", "registration_valid_until",
    ]
    assert [f.name for f in standard.STATION_FIELDS] == ["name", "location", "brand"]


def test_required_flags() -> None:
    always = [f.name for f in standard.RECORD_FIELDS if f.required == "always"]
    assert always == ["type", "vehicle", "date"]
    by_name = {f.name: f for f in standard.RECORD_FIELDS}
    assert by_name["odometer_km"].required == "refuel"
    assert by_name["title"].required == "expense"
    assert by_name["total"].required == "expense"


def test_every_field_is_documented() -> None:
    for fields in standard.TABLES.values():
        for f in fields:
            assert f.description and f.example, f.name
            assert f.type in {"string", "number", "integer", "date", "time", "boolean", "enum"}
            if f.type == "enum":
                assert f.enum, f.name
            if f.type == "number":
                assert f.unit, f.name


def test_example_records_use_known_columns() -> None:
    assert len(standard.EXAMPLE_RECORDS) == 2
    assert {r["type"] for r in standard.EXAMPLE_RECORDS} == {"refuel", "expense"}
    for row in standard.EXAMPLE_RECORDS:
        assert set(row) <= set(RECORD_COLUMNS)


def test_datapackage_structure() -> None:
    package = standard.datapackage()
    json.dumps(package)  # plain JSON
    assert package["profile"] == "tabular-data-package"
    assert "glovebox" not in package
    resources = {r["name"]: r for r in package["resources"]}
    assert list(resources) == [
        "records", "vehicles", "stations", "reminders",
    ]
    for name, resource in resources.items():
        assert resource["profile"] == "tabular-data-resource"
        assert resource["path"] == f"{name}.csv"
        assert resource["format"] == "csv"
        assert "dialect" not in resource  # RFC 4180 defaults

    fields = resources["records"]["schema"]["fields"]
    assert [f["name"] for f in fields] == RECORD_COLUMNS
    required = [f["name"] for f in fields if f.get("constraints", {}).get("required")]
    assert required == ["type", "vehicle", "date"]
    by_name = {f["name"]: f for f in fields}
    assert by_name["odometer_km"]["type"] == "number"
    assert by_name["odometer_km"]["unit"] == "km"
    assert by_name["date"]["type"] == "date"
    assert by_name["full"]["trueValues"] == ["true"]
    assert by_name["category"]["constraints"]["enum"] == list(standard.CATEGORIES)
    assert by_name["fuel_l"]["description"] and by_name["fuel_l"]["example"] == "45.200"


def test_datapackage_meta() -> None:
    meta = {"version": "1.0", "currency": "EUR"}
    assert standard.datapackage(meta)["glovebox"] == meta
