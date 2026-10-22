"""
SQLAlchemy models (design D3). FROZEN INTERFACE: change only via a migration.

Storage units: distance in km, volume in thousandths of a litre
(``litres_milli``), money in integer cents, price per litre in integer
milli-units of the currency (1.459 per litre is stored as 1459).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names are needed for Alembic batch operations on SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ExpenseCategory(StrEnum):
    """Fixed expense categories; the original label is kept in ``title``."""

    MAINTENANCE = "maintenance"
    INSURANCE = "insurance"
    REGISTRATION = "registration"
    OTHER = "other"


class DerivedField(StrEnum):
    """Which of the three refuel price figures was computed, not entered."""

    LITRES = "litres"
    PRICE_PER_LITRE = "price_per_litre"
    TOTAL = "total"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum *values* as plain strings with a CHECK constraint."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )


class ImportBatch(Base):
    """One committed import; rows reference it so the batch can be undone."""

    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    format: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    refuels_imported: Mapped[int] = mapped_column(Integer, default=0)
    expenses_imported: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0)


class Vehicle(Base):
    """A car. Name is unique among non-archived vehicles."""

    __tablename__ = "vehicle"
    __table_args__ = (
        Index(
            "uq_vehicle_active_name",
            "name",
            unique=True,
            sqlite_where=text("archived = 0"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    make: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    plate: Mapped[str | None] = mapped_column(String(30))
    fuel_type: Mapped[str | None] = mapped_column(String(50))
    initial_odometer: Mapped[float | None] = mapped_column(Float)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    vin: Mapped[str | None] = mapped_column(String(30))
    model_year: Mapped[int | None] = mapped_column(Integer)
    engine: Mapped[str | None] = mapped_column(String(100))
    tyre_size: Mapped[str | None] = mapped_column(String(50))
    insurance_policy: Mapped[str | None] = mapped_column(String(100))
    insurance_valid_until: Mapped[date | None] = mapped_column(Date)
    registration_valid_until: Mapped[date | None] = mapped_column(Date)


class Station(Base):
    """
    A gas station. ``brand`` is assigned by hand (or by an import that provides
    it) and is what brand comparisons group by.

    ``unique(name, location)`` does not stop duplicates when ``location`` is
    NULL (SQLite treats NULLs as distinct); the service layer must check.
    """

    __tablename__ = "station"
    __table_args__ = (UniqueConstraint("name", "location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    brand: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(200))
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id", ondelete="SET NULL")
    )


class Refuel(Base):
    """A refuelling. Ordered per vehicle by (odometer_km, date)."""

    __tablename__ = "refuel"
    __table_args__ = (
        # Duplicate-detection key: (vehicle, date, odometer, litres ~0.01).
        Index("ix_refuel_dedupe", "vehicle_id", "date", "odometer_km"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle.id", ondelete="CASCADE")
    )
    date: Mapped[date] = mapped_column(Date)
    time: Mapped[time | None] = mapped_column(Time)
    odometer_km: Mapped[float] = mapped_column(Float)
    litres_milli: Mapped[int] = mapped_column(Integer)
    price_per_litre_milli: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    derived_field: Mapped[DerivedField | None] = mapped_column(
        _enum(DerivedField, "derived_field")
    )
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("station.id", ondelete="SET NULL"), index=True
    )
    is_full: Mapped[bool] = mapped_column(Boolean, default=True)
    missed_previous: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(100))
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class Expense(Base):
    """
    A non-fuel cost. ``amount_cents`` is always the full price paid.
    ``coverage_start``/``coverage_end`` are both set or both NULL (inclusive).
    ``odometer_estimated`` marks an odometer that is a stand-in, not a reading.
    """

    __tablename__ = "expense"
    __table_args__ = (
        # Duplicate-detection key: (vehicle, date, category, amount).
        Index("ix_expense_dedupe", "vehicle_id", "date", "category", "amount_cents"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle.id", ondelete="CASCADE")
    )
    date: Mapped[date] = mapped_column(Date)
    odometer_km: Mapped[float | None] = mapped_column(Float)
    # True when the odometer was filled in by the app (last known reading),
    # not entered; such values never count as real readings in statistics.
    odometer_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    category: Mapped[ExpenseCategory] = mapped_column(
        _enum(ExpenseCategory, "expense_category")
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    amount_cents: Mapped[int] = mapped_column(Integer)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(100))
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class Setting(Base):
    """A UI preference (key/value text), shared by every device using the app."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Preset(Base):
    """
    A user-defined import/export preset, stored as TOML text.

    The preset id used elsewhere is ``user-<slug>``; ``body`` is exactly the
    file format, so a download returns what the user can hand-edit.
    """

    __tablename__ = "preset"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    # Protects against edits, overwrite and deletion; not part of the TOML file.
    locked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utc_now, onupdate=_utc_now
    )
