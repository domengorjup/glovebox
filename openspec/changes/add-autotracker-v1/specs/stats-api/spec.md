## ADDED Requirements

### Requirement: Versioned read-only stats API
The system SHALL expose read-only JSON endpoints under `/api/v1`:
- `GET /vehicles`
- `GET /vehicles/{id}/summary?allocation=`
- `GET /vehicles/{id}/consumption?from=&to=`
- `GET /stations/stats?vehicle=&from=&to=`

Endpoints that return costs SHALL accept `allocation=spread|paid`, defaulting to `spread`, and SHALL reject other values with HTTP 422. Their responses SHALL include the `allocation` used. Field names and meanings SHALL stay stable within v1. Fields MAY be added. Removing or renaming a field SHALL require a new version prefix.

#### Scenario: Unknown vehicle
- **WHEN** a client requests `/api/v1/vehicles/999/summary` for a non-existent vehicle
- **THEN** the response is HTTP 404 with a JSON error body

### Requirement: Vehicle summary
The summary SHALL include:
- vehicle id and name;
- currency;
- last odometer (km);
- last refuel (date, litres, price per litre, total, station name);
- last valid segment consumption (L/100 km);
- distance-weighted average consumption over the last 12 months;
- cost this calendar month;
- cost this calendar year;
- cost per km over the last 12 months.

The summary SHALL NOT include reminder or "next service due" fields. Cost fields follow the `allocation` parameter. A value that cannot be computed SHALL be `null`, not omitted.

#### Scenario: New vehicle without records
- **WHEN** the summary is requested for a vehicle with no records
- **THEN** all computed fields are `null`
- **AND** both costs are 0

#### Scenario: Allocation parameter
- **WHEN** a vehicle has a 365 € insurance paid on 2026-03-01 with coverage to 2027-02-28, and the summary is requested on 2026-03-15
- **THEN** with `allocation=paid` "cost this month" includes the full 365 €
- **AND** with the default `spread` it includes only March's 31.00 € share

### Requirement: Same numbers as the UI
API values SHALL be computed by the same statistics functions as the web pages.

#### Scenario: Consistency
- **WHEN** the stats page and the summary endpoint are queried for the same vehicle and period
- **THEN** the average consumption and the cost totals are equal

### Requirement: API authentication
In add-on mode, the API SHALL be reachable through Ingress under the same rules as the UI. In standalone mode, when `GLOVEBOX_API_TOKEN` is set, the API SHALL require `Authorization: Bearer <token>` or a valid login session, and SHALL return HTTP 401 otherwise.

#### Scenario: Missing token
- **WHEN** standalone mode has a token configured and a request arrives without credentials
- **THEN** the API returns 401
