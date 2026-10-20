# Autotracker

Track the running costs of your cars: refuelling, maintenance, insurance and registration. The add-on shows consumption and cost statistics and imports history from Drivvo, Fuelio and Fuelly CSV files.

## Installation

1. In Home Assistant open Settings, Add-ons, Add-on store, menu (three dots), Repositories.
2. Add the repository URL of this project and close the dialog.
3. Select Autotracker, then Install. The image is built on your Home Assistant host, so the first install takes a few minutes.
4. Start the add-on. Optionally enable "Show in sidebar". The panel "Autotracker" opens the app through Ingress.

## Options

Options are written by Home Assistant to `/data/options.json` and read when the add-on starts. Restart the add-on after changing them.

| Option     | Default | Description                                                              |
|------------|---------|--------------------------------------------------------------------------|
| `currency` | `EUR`   | Three-letter currency code used for display. It does not convert values. |
| `api_token`| unset   | Not used in add-on mode yet: the add-on only accepts requests from Ingress, so the stats API (`/api/v1`) is reachable only through Ingress and the token is not checked. |

Example:

```yaml
currency: EUR
```

## Data and backups

The SQLite database is stored in the add-on's `/data` folder, which survives restarts and upgrades and is included in Home Assistant backups. Database migrations run automatically at startup. You can also use the native CSV export in the app as a backup that does not depend on Home Assistant.

## Importing

Import a CSV (or a ZIP for Fuelio and the native export) on the Import page. The preview shows what would be added and writes nothing until you confirm. Re-importing the same file adds nothing, and every import can be undone from the batch list.

- Files without a vehicle name (Drivvo, Fuelly) ask which vehicle the records belong to.
- Fuelly: the `tags` column is taken as the gas station name (the whole cell, so several tags become one station), which is how our own Fuelly export keeps the station. Brands are never guessed.
- The Drivvo column mapping is provisional (not yet checked against a real export). If headers are not recognised, the preview lists the headers found and expected.

## Known limitations

- Access is only through Ingress (no separate port, no app login). Anyone who can open the Home Assistant sidebar entry can use the app.
- Expenses need a title (for example the service type) and may have an optional coverage period; the dashboard can spread such costs over the period or show them as paid.
- Only the `amd64` and `aarch64` architectures are supported.

## Support

Report problems in the project's issue tracker.
