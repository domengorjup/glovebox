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
| `api_token`| unset   | Optional bearer token for the stats API (`/api/v1`).                     |

Example:

```yaml
currency: EUR
api_token: "a-long-random-string"
```

## Data and backups

The SQLite database is stored in the add-on's `/data` folder, which survives restarts and upgrades and is included in Home Assistant backups. Database migrations run automatically at startup. You can also use the native CSV export in the app as a backup that does not depend on Home Assistant.

## Known limitations

- Access is only through Ingress (no separate port, no app login). Anyone who can open the Home Assistant sidebar entry can use the app.
- Only the `amd64` and `aarch64` architectures are supported.

## Support

Report problems in the project's issue tracker.
