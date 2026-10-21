# API reference

Base path `/api/v1`. Read-only JSON. Field names are stable within v1: additions are allowed, removals need `/api/v2`.

**Auth.** Add-on API port 8100 and standalone with `GLOVEBOX_API_TOKEN`: `Authorization: Bearer <token>`. Through Ingress no header is needed.

**Units.** Money in currency units (not cents), litres in litres, consumption in L/100 km, distances in km. Dates are ISO `YYYY-MM-DD`.

**Errors.** 404 for an unknown vehicle, 422 for an invalid parameter or a `from` after `to`.

## `GET /api/v1/vehicles`

Non-archived vehicles. Returns a list of `id`, `name`, `make`, `model`, `plate`, `fuel_type`.

## `GET /api/v1/vehicles/{id}/summary`

| Parameter | Values | Default |
|---|---|---|
| `allocation` | `spread`, `paid` | `spread` |

Response fields: `vehicle_id`, `name`, `currency`, `allocation`, `last_odometer_km`, `last_refuel` (object with `date`, `litres`, `price_per_litre`, `total`, `station`, or `null`), `last_consumption`, `avg_consumption_12m`, `cost_this_month`, `cost_this_year`, `cost_per_km_12m`. The cost fields follow `allocation`.

## `GET /api/v1/vehicles/{id}/consumption`

| Parameter | Meaning |
|---|---|
| `from`, `to` | Optional date range, by the date of the fill that closes each segment |

Response: `vehicle_id`, `from`, `to`, `avg_consumption` (distance-weighted), and `segments`, a list of `end_date`, `station_id`, `distance_km`, `litres`, `consumption`, `valid`, `invalid_reason`.

## `GET /api/v1/stations/stats`

| Parameter | Meaning | Default |
|---|---|---|
| `vehicle` | Vehicle id; all vehicles if omitted | all |
| `from`, `to` | Date range | none |
| `group_by` | `station` or `brand` | `station` |

Response: `vehicle_id`, `from`, `to`, `group_by`, and `stations`, a list of `key`, `label`, `fills`, `litres`, `avg_price_per_litre`, `min_price_per_litre`, `max_price_per_litre`, `consumption`, `consumption_segments`. `consumption` is `null` when fewer than 2 single-station segments qualify.

Source: `src/glovebox/api/v1.py`.
