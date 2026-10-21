"""Tests for the preset-driven CSV export (data-export spec)."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, time

import pytest
from sqlalchemy.orm import Session

from glovebox.config import Settings
from glovebox.exporters.csv_export import export_csv, renamed_vehicles
from glovebox.importers.presets import Preset, PresetError, load_preset
from glovebox.models import Expense, ExpenseCategory, Refuel, Station, Vehicle
from glovebox.standard import RECORD_FIELDS

FUELLY_HEADER = "fuelup_date,odometer,litres,price,partial_fuelup,missed_fuelup,notes,tags"

FUELLY = """
name = "Fuelly (metric)"
export = true
split_by_vehicle = true

[format]
distance_unit = "km"
volume_unit = "l"

[fields]
type = { value = "refuel" }
date = { column = "fuelup_date" }
odometer_km = { column = ["odometer", "km"] }
fuel_l = { column = ["litres", "liters"] }
price_per_l = { column = "price" }
full = { column = "partial_fuelup", true_values = ["0"], false_values = ["1"] }
missed_previous = { column = "missed_fuelup", true_values = ["1"], false_values = ["0"] }
notes = { column = "notes" }
station = { column = "tags" }
"""

STANDARD = "name = \"Standard\"\nexport = true\n[fields]\n" + "".join(
    f'{f.name} = {{ column = "{f.name}" }}\n' for f in RECORD_FIELDS
)


def _preset(text: str) -> Preset:
    return load_preset(text, id="test", shipped=True)


def _refuel(vehicle_id: int, station_id: int | None, **kw) -> Refuel:
    values = dict(
        vehicle_id=vehicle_id, date=date(2026, 5, 2), odometer_km=98000,
        litres_milli=20500, price_per_litre_milli=1459, total_cents=2991,
        station_id=station_id,
    )  # fmt: skip
    return Refuel(**{**values, **kw})


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8").splitlines()


def test_fuelly_export_row(session: Session) -> None:
    car, station = Vehicle(name="Car"), Station(name="OMV Celje")
    session.add_all([car, station])
    session.flush()
    session.add(_refuel(car.id, station.id, is_full=False))
    session.add(
        Expense(
            vehicle_id=car.id, date=date(2026, 5, 3),
            category=ExpenseCategory.OTHER, title="Wash", amount_cents=500,
        )
    )  # fmt: skip
    session.flush()

    data, media = export_csv(session, Settings(), _preset(FUELLY))

    assert media == "text/csv"
    assert not data.startswith(b"\xef\xbb\xbf")
    assert _lines(data) == [FUELLY_HEADER, "2026-05-02,98000,20.500,1.459,1,0,,OMV Celje"]


def test_fuelly_flags_and_missing_station(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(_refuel(car.id, None, missed_previous=True, odometer_km=98000.5))
    session.flush()

    data, _ = export_csv(session, Settings(), _preset(FUELLY))
    assert _lines(data)[1] == "2026-05-02,98000.5,20.500,1.459,0,1,,"


def test_fuelly_multiple_vehicles_are_zipped(session: Session) -> None:
    one, two = Vehicle(name="One"), Vehicle(name="Two/Car")
    session.add_all([one, two])
    session.flush()
    session.add_all([_refuel(one.id, None), _refuel(two.id, None)])
    session.flush()

    data, media = export_csv(session, Settings(), _preset(FUELLY))
    assert media == "application/zip"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert len(names) == 2 and all(n.endswith(".csv") for n in names)
        assert all("/" not in n for n in names)
        for name in names:
            assert archive.read(name).decode().startswith(FUELLY_HEADER)

    _, single_media = export_csv(session, Settings(), _preset(FUELLY), [one.id])
    assert single_media == "text/csv"


def test_standard_export_has_both_types(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add_all(
        [_refuel(car.id, None, time=time(14, 30), date=date(2026, 5, 2 + i)) for i in range(3)]
    )
    session.add_all(
        [
            Expense(
                vehicle_id=car.id, date=date(2026, 6, 1 + i),
                category=ExpenseCategory.MAINTENANCE, title=f"Job {i}", amount_cents=12000,
            )
            for i in range(2)
        ]
    )  # fmt: skip
    session.flush()

    data, _ = export_csv(session, Settings(), _preset(STANDARD))
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert list(rows[0]) == [f.name for f in RECORD_FIELDS]
    assert [r["type"] for r in rows] == ["refuel"] * 3 + ["expense"] * 2
    first = rows[0]
    assert (first["vehicle"], first["date"], first["time"]) == ("Car", "2026-05-02", "14:30")
    assert (first["odometer_km"], first["fuel_l"], first["price_per_l"], first["total"]) == (
        "98000", "20.500", "1.459", "29.91",
    )  # fmt: skip
    assert (first["currency"], first["full"], first["missed_previous"]) == ("EUR", "true", "false")
    expense = rows[3]
    assert (expense["category"], expense["title"], expense["total"]) == (
        "maintenance", "Job 0", "120.00",
    )  # fmt: skip
    assert expense["fuel_l"] == "" and expense["full"] == ""
    assert data.endswith(b"\r\n")


def test_custom_semicolon_export(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(
        _refuel(car.id, None, litres_milli=45200, price_per_litre_milli=1459, total_cents=6595)
    )
    session.flush()
    preset = _preset(
        """
name = "Custom"
export = true
[file]
delimiter = ";"
[format]
decimal_char = ","
[fields]
date = { column = "date" }
fuel_l = { column = "fuel_l" }
total = { column = "total" }
"""
    )

    data, _ = export_csv(session, Settings(), preset)
    assert _lines(data) == ["date;fuel_l;total", "2026-05-02;45,200;65,95"]


def test_export_in_miles_and_gallons(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(
        _refuel(
            car.id, None, odometer_km=160.9344, litres_milli=37854,
            price_per_litre_milli=1000, total_cents=3785,
        )
    )  # fmt: skip
    session.flush()
    preset = _preset(
        """
name = "Imperial"
export = true
[format]
distance_unit = "mi"
volume_unit = "gal_us"
date_format = "%d.%m.%Y"
[fields]
date = { column = "date" }
odometer_km = { column = "odometer" }
fuel_l = { column = "gallons" }
price_per_l = { column = "price" }
"""
    )

    data, _ = export_csv(session, Settings(), preset)
    assert _lines(data) == [
        "date,odometer,gallons,price",
        "02.05.2026,100,10.000,3.785",
    ]


def test_mapped_type_and_constant_filter(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(_refuel(car.id, None))
    session.add(
        Expense(
            vehicle_id=car.id, date=date(2026, 5, 3), category=ExpenseCategory.INSURANCE,
            title="Policy", amount_cents=500,
        )
    )  # fmt: skip
    session.flush()
    preset = _preset(
        """
name = "Mapped"
export = true
[fields]
type = { column = "kind", map = { refuel = ["F", "fuel"], expense = ["X"] } }
category = { column = "cat", map = { insurance = ["INS"] } }
"""
    )
    data, _ = export_csv(session, Settings(), preset)
    assert _lines(data) == ["kind,cat", "F,", "X,INS"]

    expenses_only = _preset(
        'name = "E"\nexport = true\n[fields]\ntype = { value = "expense" }\n'
        'title = { column = "title" }\n'
    )
    data, _ = export_csv(session, Settings(), expenses_only)
    assert _lines(data) == ["title", "Policy"]


def test_quoting_of_notes(session: Session) -> None:
    car = Vehicle(name="Car")
    session.add(car)
    session.flush()
    session.add(_refuel(car.id, None, notes='a, "quoted"\nnote'))
    session.flush()
    data, _ = export_csv(session, Settings(), _preset(STANDARD))
    rows = list(csv.DictReader(io.StringIO(data.decode(), newline="")))
    assert rows[0]["notes"] == 'a, "quoted"\nnote'


def test_archived_vehicle_with_clashing_name_is_renamed(session: Session) -> None:
    active = Vehicle(name="Golf")
    old = Vehicle(name="Golf", archived=True)
    older = Vehicle(name="golf", archived=True)
    solo = Vehicle(name="Polo", archived=True)
    session.add_all([active, old, older, solo])
    session.flush()
    session.add_all([_refuel(v.id, None) for v in (active, old, older, solo)])
    session.flush()

    data, _ = export_csv(session, Settings(), _preset(STANDARD))
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert [r["vehicle"] for r in rows] == [
        "Golf", "Golf (archived)", "golf (archived) (2)", "Polo",
    ]  # fmt: skip
    assert renamed_vehicles(session) == {
        "Golf": "Golf (archived)", "golf": "golf (archived) (2)",
    }  # fmt: skip
    assert renamed_vehicles(session, [old.id]) == {}


def test_not_exportable_preset_is_rejected(session: Session) -> None:
    with pytest.raises(PresetError):
        export_csv(session, Settings(), _preset('name = "x"\n[fields]\ndate = { column = "d" }\n'))
    with pytest.raises(PresetError):
        export_csv(
            session,
            Settings(),
            _preset(
                'name = "x"\nexport = true\n[fields]\ndate = { column = "d" }\n'
                '[[skip_rows]]\ncolumn = "a"\nvalues = ["1"]\n'
            ),
        )
