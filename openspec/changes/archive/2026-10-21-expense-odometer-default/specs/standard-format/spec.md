## MODIFIED Requirements

### Requirement: Standard records format
The system SHALL define a standard CSV format for records with one row per refuel or expense and these columns, in this order:
`type`, `vehicle`, `date`, `time`, `odometer_km`, `odometer_estimated`, `fuel_l`, `price_per_l`, `total`, `currency`, `full`, `missed_previous`, `station`, `station_location`, `station_brand`, `category`, `title`, `coverage_start`, `coverage_end`, `notes`, `derived`, `source`, `source_ref`.

- **File conventions:**
  - RFC 4180 CSV: comma delimiter, `"` quoting, CRLF line ends, one header row.
  - UTF-8: written without BOM; a BOM SHALL be accepted on import.
- **Value conventions:**
  - Dates `YYYY-MM-DD`; times `HH:MM` (`HH:MM:SS` accepted on import).
  - Dot as decimal separator, no thousands separator.
  - Booleans `true` or `false`; an empty cell means no value.
- **Units and money:** distances in km, volumes in litres, money as a decimal number in the currency named by `currency`. The unit SHALL be part of the column name where the column has one.
- **Per-type rules:**
  - `type` is `refuel` or `expense`. `vehicle`, `date` and `type` are required on every row.
  - A refuel requires `odometer_km` and at least two of `fuel_l`, `price_per_l` and `total`.
  - An expense requires `title` and a positive `total`. `category` is one of `maintenance`, `insurance`, `registration`, `other` and defaults to `other`. `coverage_start` and `coverage_end` are set both or neither.
  - `odometer_estimated` applies to expenses only: true when the odometer was filled in by the app, not entered. It is optional, defaults to false, and is ignored when `odometer_km` is empty.
  - Columns that do not apply to a row's type SHALL be empty.
- **`currency`:** a non-empty value that differs from the app currency SHALL make that row an error on import.
- **Export precision:** `fuel_l` and `price_per_l` with 3 decimals, `total` with 2 decimals, `odometer_km` without trailing zeros.

#### Scenario: Refuel row
- **WHEN** a full refuel of 45.2 L at 1.459 EUR/L, total 65.95, at 98000 km on 2026-05-02 at station "OMV Celje" for vehicle "Golf" is exported in the standard format
- **THEN** its row has `type` "refuel", `vehicle` "Golf", `date` "2026-05-02", `odometer_km` "98000", `fuel_l` "45.200", `price_per_l` "1.459", `total` "65.95", `currency` "EUR", `full` "true", `station` "OMV Celje"
- **AND** the expense-only columns are empty

#### Scenario: Estimated odometer round trip
- **WHEN** an expense with an estimated odometer is exported and imported with the standard preset
- **THEN** the imported expense has the same odometer and `odometer_estimated` true

#### Scenario: Wrong currency
- **WHEN** a standard file row has `currency` "USD" and the app currency is EUR
- **THEN** the preview lists that row as an error and it is not imported
