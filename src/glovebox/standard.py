"""
The Glovebox standard CSV format: the single code-level definition (design D1/D2).

Import mapping targets, export columns, the standard preset, the generated
documentation and the Data Package descriptor are all derived from the tuples
below. Nothing else lists the columns. FROZEN after task group 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Field types, as used by ``StandardField.type``.
STRING, NUMBER, DATE, TIME, BOOLEAN, ENUM = (
    "string",
    "number",
    "date",
    "time",
    "boolean",
    "enum",
)

# ``StandardField.required`` values.
REQUIRED_ALWAYS = "always"
REQUIRED_REFUEL = "refuel"
REQUIRED_EXPENSE = "expense"
REQUIRED_NO = "no"

REFUEL = "refuel"
EXPENSE = "expense"
RECORD_TYPES = (REFUEL, EXPENSE)
CATEGORIES = ("maintenance", "insurance", "registration", "other")
DERIVED_VALUES = ("fuel_l", "price_per_l", "total")

TRUE_VALUE = "true"
FALSE_VALUE = "false"


@dataclass(frozen=True)
class StandardField:
    """
    One column of a standard CSV table.

    Attributes
    ----------
    name : str
        Column name; the unit is part of it where there is one.
    type : str
        ``string``, ``number``, ``date``, ``time``, ``boolean`` or ``enum``.
    unit : str | None
        Unit of a number (``km``, ``l``, ``currency``, ``currency/l``).
    applies_to : tuple[str, ...]
        ``("refuel",)``, ``("expense",)``, both, or ``("vehicle",)`` /
        ``("station",)`` for the backup tables.
    required : str
        ``always``, ``refuel`` (required on refuel rows), ``expense``
        (required on expense rows) or ``no``.
    rule : str
        Extra rule in words ("two of three", "both or neither"); empty if none.
    enum : tuple[str, ...]
        Allowed values of an ``enum`` field.
    default : str | None
        Value used when the cell is empty (as written in the file).
    export_decimals : int | None
        Decimals written on export; ``None`` for no trailing zeros / not a number.
    description : str
    example : str
    """

    name: str
    type: str
    description: str
    example: str
    applies_to: tuple[str, ...] = RECORD_TYPES
    required: str = REQUIRED_NO
    rule: str = ""
    unit: str | None = None
    enum: tuple[str, ...] = ()
    default: str | None = None
    export_decimals: int | None = None


RECORD_FIELDS: tuple[StandardField, ...] = (
    StandardField(
        "type", ENUM, "Kind of record.", "refuel",
        required=REQUIRED_ALWAYS, enum=RECORD_TYPES,
    ),
    StandardField(
        "vehicle", STRING, "Vehicle name.", "Golf", required=REQUIRED_ALWAYS
    ),
    StandardField(
        "date", DATE, "Date of the record, YYYY-MM-DD.", "2026-05-02",
        required=REQUIRED_ALWAYS,
    ),
    StandardField(
        "time", TIME, "Time of day, HH:MM (HH:MM:SS is also accepted).", "14:30",
        applies_to=(REFUEL,),
    ),
    StandardField(
        "odometer_km", NUMBER, "Odometer reading.", "98000",
        required=REQUIRED_REFUEL, unit="km",
    ),
    StandardField(
        "odometer_estimated", BOOLEAN,
        "Written by Glovebox: the expense odometer is the last known reading, "
        "not an entered one. Leave empty.", "false",
        applies_to=(EXPENSE,), enum=(TRUE_VALUE, FALSE_VALUE), default=FALSE_VALUE,
    ),
    StandardField(
        "fuel_l", NUMBER, "Fuel quantity.", "45.200",
        applies_to=(REFUEL,), unit="l", export_decimals=3,
        rule="Give two of fuel_l, price_per_l and total; the third is derived.",
    ),
    StandardField(
        "price_per_l", NUMBER, "Price per litre.", "1.459",
        applies_to=(REFUEL,), unit="currency/l", export_decimals=3,
        rule="Give two of fuel_l, price_per_l and total; the third is derived.",
    ),
    StandardField(
        "total", NUMBER, "Refuel total, or expense amount (greater than 0).",
        "65.95", required=REQUIRED_EXPENSE, unit="currency", export_decimals=2,
        rule="Refuel: give two of fuel_l, price_per_l and total. Expense: required.",
    ),
    StandardField(
        "currency", STRING,
        "ISO 4217 currency code; must equal the app currency when given.", "EUR",
    ),
    StandardField(
        "full", BOOLEAN, "The tank was filled completely.", "true",
        applies_to=(REFUEL,), enum=(TRUE_VALUE, FALSE_VALUE), default=TRUE_VALUE,
    ),
    StandardField(
        "missed_previous", BOOLEAN,
        "A fill-up before this one was not recorded.", "false",
        applies_to=(REFUEL,), enum=(TRUE_VALUE, FALSE_VALUE), default=FALSE_VALUE,
    ),
    StandardField(
        "station", STRING, "Station name.", "OMV Celje", applies_to=(REFUEL,)
    ),
    StandardField(
        "station_location", STRING,
        "Station location; with the name it identifies the station.", "Celje",
        applies_to=(REFUEL,),
    ),
    StandardField(
        "station_brand", STRING,
        "Station brand; used only when the station is created.", "OMV",
        applies_to=(REFUEL,),
    ),
    StandardField(
        "category", ENUM, "Expense category.", "maintenance",
        applies_to=(EXPENSE,), enum=CATEGORIES, default="other",
    ),
    StandardField(
        "title", STRING, "Short label of the expense.", "Oil change",
        applies_to=(EXPENSE,), required=REQUIRED_EXPENSE,
    ),
    StandardField(
        "coverage_start", DATE,
        "First day the expense covers (insurance, registration), YYYY-MM-DD.",
        "2026-01-01", applies_to=(EXPENSE,),
        rule="Set both coverage_start and coverage_end, or neither.",
    ),
    StandardField(
        "coverage_end", DATE, "Last day the expense covers, YYYY-MM-DD.",
        "2026-12-31", applies_to=(EXPENSE,),
        rule="Set both coverage_start and coverage_end, or neither.",
    ),
    StandardField("notes", STRING, "Free text.", "Winter tyres"),
    StandardField(
        "derived", ENUM,
        "Written by Glovebox: which refuel figure was derived. Leave empty.",
        "total", applies_to=(REFUEL,), enum=DERIVED_VALUES,
    ),
    StandardField(
        "source", STRING,
        "Written by Glovebox: where the record came from. Leave empty.", "manual",
    ),
    StandardField(
        "source_ref", STRING,
        "Written by Glovebox: the record's id in its source. Leave empty.", "1042",
    ),
)

VEHICLE_FIELDS: tuple[StandardField, ...] = (
    StandardField(
        "name", STRING, "Vehicle name, as used in records.csv.", "Golf",
        applies_to=("vehicle",), required=REQUIRED_ALWAYS,
    ),
    StandardField("make", STRING, "Manufacturer.", "Volkswagen", applies_to=("vehicle",)),
    StandardField("model", STRING, "Model.", "Golf VII", applies_to=("vehicle",)),
    StandardField("plate", STRING, "Registration plate.", "LJ AB-123", applies_to=("vehicle",)),
    StandardField("fuel_type", STRING, "Fuel type.", "Diesel", applies_to=("vehicle",)),
    StandardField(
        "initial_odometer_km", NUMBER, "Odometer when tracking started.", "85000",
        applies_to=("vehicle",), unit="km",
    ),
    StandardField(
        "archived", BOOLEAN, "The vehicle is archived.", "false",
        applies_to=("vehicle",), enum=(TRUE_VALUE, FALSE_VALUE), default=FALSE_VALUE,
    ),
    StandardField("notes", STRING, "Free text.", "Company car", applies_to=("vehicle",)),
)

STATION_FIELDS: tuple[StandardField, ...] = (
    StandardField(
        "name", STRING, "Station name.", "OMV Celje",
        applies_to=("station",), required=REQUIRED_ALWAYS,
    ),
    StandardField(
        "location", STRING, "Station location.", "Celje", applies_to=("station",)
    ),
    StandardField("brand", STRING, "Station brand.", "OMV", applies_to=("station",)),
)

TABLES: dict[str, tuple[StandardField, ...]] = {
    "records": RECORD_FIELDS,
    "vehicles": VEHICLE_FIELDS,
    "stations": STATION_FIELDS,
}

# One refuel and one expense; rows of ``RECORD_FIELDS`` (empty = no value).
EXAMPLE_RECORDS: tuple[dict[str, str], ...] = (
    {
        "type": "refuel", "vehicle": "Golf", "date": "2026-05-02", "time": "14:30",
        "odometer_km": "98000", "fuel_l": "45.200", "price_per_l": "1.459",
        "total": "65.95", "currency": "EUR", "full": "true",
        "missed_previous": "false", "station": "OMV Celje",
        "station_location": "Celje", "station_brand": "OMV",
    },
    {
        "type": "expense", "vehicle": "Golf", "date": "2026-05-10",
        "odometer_km": "98400", "total": "180.00", "currency": "EUR",
        "category": "maintenance", "title": "Oil change", "notes": "Winter tyres",
    },
)

# Table Schema / Data Package property names follow the published v1 specs:
#   https://specs.frictionlessdata.io/table-schema/   (fields, missingValues,
#       field: name, title, description, example, type, format, constraints
#       {required, enum}, trueValues, falseValues, decimalChar, groupChar)
#   https://specs.frictionlessdata.io/data-package/   (resources, name, profile,
#       title, description, version, created; extra properties allowed)
#   https://specs.frictionlessdata.io/data-resource/  (name, path, format,
#       mediatype, encoding, schema)
#   https://specs.frictionlessdata.io/tabular-data-resource/ (profile
#       "tabular-data-resource" and a schema are required; "dialect" only if
#       the CSV differs from RFC 4180 rules, which ours does not)
# Both specs allow extra properties on descriptors and field descriptors, so
# ``unit`` (field) and ``glovebox`` (package) are custom properties.
# The "tabular-data-package" profile is named in the data-package spec.
DATAPACKAGE_PROFILE = "tabular-data-package"
RESOURCE_PROFILE = "tabular-data-resource"
_SCHEMA_TYPES = {
    STRING: "string", NUMBER: "number", DATE: "date", TIME: "time",
    BOOLEAN: "boolean", ENUM: "string",
}
_TABLE_TITLES = {
    "records": "Records (refuels and expenses)",
    "vehicles": "Vehicles (backup only)",
    "stations": "Stations (backup only)",
}


def _describe(field: StandardField) -> str:
    parts = [field.description]
    if field.unit:
        parts.append(f"Unit: {field.unit}.")
    if field.rule:
        parts.append(field.rule)
    applies = [a for a in field.applies_to if a in RECORD_TYPES]
    if applies and len(applies) < len(RECORD_TYPES):
        parts.append(f"Applies to {applies[0]} rows only.")
    if field.required == REQUIRED_REFUEL:
        parts.append("Required on refuel rows.")
    elif field.required == REQUIRED_EXPENSE and not field.rule:
        parts.append("Required on expense rows.")
    return " ".join(parts)


def _schema_field(field: StandardField) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "name": field.name,
        "type": _SCHEMA_TYPES[field.type],
        "description": _describe(field),
        "example": field.example,
    }
    if field.type == TIME:
        descriptor["format"] = "%H:%M"
    if field.type == BOOLEAN:
        descriptor["trueValues"] = [TRUE_VALUE]
        descriptor["falseValues"] = [FALSE_VALUE]
    if field.type == NUMBER:
        descriptor["decimalChar"] = "."
        descriptor["groupChar"] = ""
    if field.unit:
        descriptor["unit"] = field.unit
    constraints: dict[str, Any] = {}
    if field.required == REQUIRED_ALWAYS:
        constraints["required"] = True
    if field.type == ENUM:
        constraints["enum"] = list(field.enum)
    if constraints:
        descriptor["constraints"] = constraints
    return descriptor


def datapackage(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build the Data Package descriptor: one Table Schema per table.

    Parameters
    ----------
    meta : dict | None
        Stored under the custom ``glovebox`` property (app version, schema
        version, export time, currency) when given; omitted otherwise, so
        the committed descriptor stays free of run-specific values.

    Only always-required columns get ``constraints.required``; conditional
    rules are stated in each field's ``description``.
    """
    resources = [
        {
            "name": name,
            "path": f"{name}.csv",
            "profile": RESOURCE_PROFILE,
            "format": "csv",
            "mediatype": "text/csv",
            "encoding": "utf-8",
            "title": _TABLE_TITLES[name],
            "schema": {
                "fields": [_schema_field(f) for f in fields],
                "missingValues": [""],
            },
        }
        for name, fields in TABLES.items()
    ]
    package: dict[str, Any] = {
        "name": "glovebox-standard-format",
        "title": "Glovebox standard format",
        "profile": DATAPACKAGE_PROFILE,
        "resources": resources,
    }
    if meta is not None:
        package["glovebox"] = dict(meta)
    return package
