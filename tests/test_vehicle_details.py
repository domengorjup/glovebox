"""Vehicle details: migration 0006 and service rules."""

from __future__ import annotations

from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from glovebox.db import MIGRATIONS_DIR, make_engine, run_migrations
from glovebox.services import records
from glovebox.services.records import ValidationError, VehicleInput

def _config(connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


DETAIL_COLUMNS = {
    "vin", "model_year", "engine", "tyre_size", "insurance_policy",
    "insurance_valid_until", "registration_valid_until",
}  # fmt: skip


def test_upgrade_adds_nullable_columns_and_keeps_rows() -> None:
    engine = make_engine()
    with engine.begin() as connection:
        command.upgrade(_config(connection), "0005")
        connection.execute(text(
            "INSERT INTO vehicle (name, archived) VALUES ('Golf', 0)"
        ))
        command.upgrade(_config(connection), "0006")
    columns = {c["name"]: c for c in inspect(engine).get_columns("vehicle")}
    assert DETAIL_COLUMNS <= set(columns)
    assert all(columns[name]["nullable"] for name in DETAIL_COLUMNS)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT name, vin FROM vehicle")).one()
    assert tuple(row) == ("Golf", None)
    engine.dispose()


def test_downgrade_drops_columns() -> None:
    engine = make_engine()
    run_migrations(engine)
    with engine.begin() as connection:
        command.downgrade(_config(connection), "0005")
    assert not DETAIL_COLUMNS & {c["name"] for c in inspect(engine).get_columns("vehicle")}
    engine.dispose()


def test_details_are_cleaned_and_stored(session: Session) -> None:
    vehicle = records.create_vehicle(session, VehicleInput(
        name="Golf", vin="  wvwzzz1kz6w000001 ", model_year=2018, engine=" 1.5 TSI ",
        tyre_size="", insurance_valid_until=date(2027, 3, 14),
    ))
    assert vehicle.vin == "WVWZZZ1KZ6W000001"
    assert vehicle.engine == "1.5 TSI"
    assert vehicle.tyre_size is None
    assert vehicle.insurance_valid_until == date(2027, 3, 14)
    assert vehicle.registration_valid_until is None


@pytest.mark.parametrize("year", [1800, 3000])
def test_model_year_out_of_range_is_rejected(session: Session, year: int) -> None:
    with pytest.raises(ValidationError, match="Model year"):
        records.create_vehicle(session, VehicleInput(name="Golf", model_year=year))
