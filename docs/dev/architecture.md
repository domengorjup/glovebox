# Architecture

Glovebox is one Python app (FastAPI) that serves server-rendered HTML pages and a read-only JSON API from the same process, on top of a SQLite database.

## Components

| Component | Role |
|---|---|
| `web/` | HTML routes, Jinja2 templates, vendored static files. Forms work through normal POST requests; JavaScript only enhances them (charts, dialogs). |
| `api/v1.py` | Read-only stats API. |
| `services/records.py` | Create, read, update, delete and validation. Derives the third price figure. |
| `services/preferences.py` | Server-side UI preferences (selected vehicle, Timeline cards and summaries). |
| `services/stats.py` | Consumption, cost, allocation and station statistics. Used by both the HTML pages and the API, so their numbers cannot differ. |
| `importers/` | One pipeline and one preset-driven engine; presets are TOML files in `presets/`. |
| `exporters/` | Preset-driven CSV export and the full backup ZIP. |
| `auth.py` | Add-on source check (Ingress proxy only), standalone login, Bearer token. |
| `db.py`, `models.py`, `migrations/` | SQLAlchemy models, Alembic migrations run at startup. |

## Data flow

```text
browser -> web routes -> services/records -> SQLite
                      \-> services/stats  -> SQLite (read)
HA REST sensor -> api/v1 -> services/stats
CSV file -> importers/pipeline (detect preset, engine, dedupe, preview, commit) -> services/records
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

The UI remembers the selected vehicle, the choice of Timeline summary cards and the hidden summaries on the server, in the key/value `setting` table, so they are the same on every device.

## Database

SQLite at `$DATA_DIR/glovebox.db`, WAL mode. Alembic runs `upgrade head` at startup, so upgrades need no manual step.

## Home Assistant Core API client

Reminders are written to a Home Assistant calendar by a small client for the Core API. It uses only the standard library, so it adds no dependency, and it is written so another add-on can copy it.

- **Files:** `src/glovebox/services/ha_calendar.py` is the client (`HaClient`, with its own error classes). `src/glovebox/services/reminder_sync.py` decides what to write for each reminder.
- **Access:** the add-on sets `homeassistant_api: true`. Requests go to `http://supervisor/core/api` with the `SUPERVISOR_TOKEN` environment variable as Bearer token. REST is enough to list calendars, read states, list events and call `calendar.create_event`.
- **Websocket:** changing and deleting an event exists only as websocket commands (`calendar/event/update`, `calendar/event/delete`). A minimal websocket client (handshake, auth message, masked text frames, one command per connection, no TLS, no fragmentation) talks to `ws://supervisor/core/websocket`. This URL is **not yet verified inside a running add-on** (task 0.1 of the reminders change). If it needs more than the small client offers, the fallback is the `websockets` package.
- **Timeouts and threads:** every call has a 10 s timeout and runs in a worker thread, so a slow Home Assistant never blocks a request. A failure never undoes saving; it sets a state and a plain message on the reminder.
- **Retry:** one background task in the app lifespan, guarded by a lock, retries every 15 minutes and once at startup. "Sync now" runs the same pass.
- **No duplicates:** `calendar.create_event` returns no uid. Before creating, the sync looks for an existing event by a marker line in the description, in a date window around the due date. Retries and restores therefore do not create a second event.
- **Adapting:** the code reads only the calendar's `supported_features` (create, delete, update) and does nothing per calendar provider. A missing feature turns into a message ("edit it there"), not an error.
- **Standalone:** there is no token, so the client is `None` and sync is skipped. Everything else works.
