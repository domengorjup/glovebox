## Why

The Timeline summary mixed periods: cost was always "this month" while consumption, cost per km and price used the last 12 months. Users could not look at another period, for example the last 30 days or a calendar year.

## What Changes

- **Period per summary:** every summary heading (single vehicle, the combined "All vehicles" summary, each vehicle in the all-vehicles view) gets a period chip: This month, Last 30 days, This year, Last 12 months (default), All time, Custom range.
- **One period for four cards:** cost, average consumption, cost per km and average price per litre follow the period. Last refuel and odometer ignore it.
- **Cost comparison:** the cost card compares with the previous period (same days of the previous month or year for This month and This year; equal length before for the others; none for All time).
- **Remembered on the server:** per vehicle, plus one for the combined summary. Works without JavaScript.
- **Behaviour change:** the cost card is titled "Cost" and no longer always means the current month.

## Capabilities

### Modified Capabilities
- `ui-preferences`: Timeline summary cards and period.

## Impact

- Code: new `services/periods.py`, `services/preferences.py`, `web/preferences.py` (`POST /preferences/period`), `web/timeline.py`, `timeline.html`, `app.css`, `app.js`.
- Docs: `docs/user/timeline.md`, `docs/dev/design.md`. No data-model change (new rows in the `setting` table); `/api/v1` is unchanged.
