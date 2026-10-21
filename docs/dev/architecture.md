# Architecture

Glovebox is one Python app (FastAPI) that serves server-rendered HTML pages and a read-only JSON API from the same process, on top of a SQLite database.

## Components

| Component | Role |
|---|---|
| `web/` | HTML routes, Jinja2 templates, vendored static files. Forms work through normal POST requests; JavaScript only enhances them (charts, dialogs). |
| `api/v1.py` | Read-only stats API. |
| `services/records.py` | Create, read, update, delete and validation. Derives the third price figure. |
| `services/stats.py` | Consumption, cost, allocation and station statistics. Used by both the HTML pages and the API, so their numbers cannot differ. |
| `importers/` | One pipeline, one adapter per format, header alias tables. |
| `exporters/` | Native ZIP and Fuelly-compatible CSV. |
| `auth.py` | Add-on source check (Ingress proxy only), standalone login, Bearer token. |
| `db.py`, `models.py`, `migrations/` | SQLAlchemy models, Alembic migrations run at startup. |

## Data flow

```text
browser -> web routes -> services/records -> SQLite
                      \-> services/stats  -> SQLite (read)
HA REST sensor -> api/v1 -> services/stats
CSV file -> importers/pipeline (detect, parse, dedupe, preview, commit) -> services/records
```

## Modes

- **Add-on** (`GLOVEBOX_MODE=addon`): listens on 8099, accepts requests only from the HA Ingress proxy, no login. The URL prefix comes from the `X-Ingress-Path` header. An optional second listener on 8100 serves only `/api/v1` with a Bearer token, and starts only if a token of 16+ characters is set. Both servers run in one process and share the engine and settings.
- **Standalone** (default): port 8080, optional password login with a signed session cookie, optional Bearer token for the API.

All templates build URLs through `urls.url(request, path)` so the prefix is always applied.

## Units and money

- Distance in km, volume in litres. Importers convert miles and gallons.
- Money is stored as integer cents. Price per litre is stored in milli-units (3 decimals). Litres in millilitres.
- One app-wide currency code, for display only.
- A refuelling keeps all three of litres, price per litre and total. `derived_field` records which one was computed (`litres`, `price_per_litre` or `total`).
- Expense categories are a fixed set: `maintenance`, `insurance`, `registration`, `other`. The original label is kept in `title`.
- Spread amounts are computed in cents with the largest-remainder method, so monthly parts sum exactly to the total.

## Preferences

The UI remembers the selected vehicle and the choice of summary cards on the server, in a small preferences table, so they are the same on every device.

!!! note
    The preferences table belongs to the rebuilt UI. Check `models.py` and `migrations/` for the exact schema.

## Database

SQLite at `$DATA_DIR/glovebox.db`, WAL mode. Alembic runs `upgrade head` at startup, so upgrades need no manual step.
