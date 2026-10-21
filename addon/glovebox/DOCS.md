# Glovebox

Track the running costs of your cars: refuelling, maintenance, insurance and registration. The add-on shows consumption and cost statistics and imports history from Drivvo, Fuelio and Fuelly CSV files.

## Installation

1. In Home Assistant open Settings, Add-ons, Add-on store, menu (three dots), Repositories.
2. Add the repository URL of this project and close the dialog.
3. Select Glovebox, then Install. The image is built on your Home Assistant host, so the first install takes a few minutes.
4. Start the add-on. Optionally enable "Show in sidebar". The panel "Glovebox" opens the app through Ingress.

## Options

Options are written by Home Assistant to `/data/options.json` and read when the add-on starts. Restart the add-on after changing them.

| Option     | Default | Description                                                              |
|------------|---------|--------------------------------------------------------------------------|
| `currency` | `EUR`   | Three-letter currency code used for display. It does not convert values. |
| `api_token`| unset   | Bearer token for the optional stats API port (at least 16 characters; shorter values stop the add-on with an error). Leave empty to keep the API off. |

Example:

```yaml
currency: EUR
```

## Stats API for Home Assistant sensors

Through Ingress the stats API (`/api/v1`) is only reachable from the sidebar. To read it from Home Assistant REST sensors or another client:

1. Set `api_token` in the add-on options to a random string of 16 or more characters.
2. In the add-on Network section, set a host port for `8100/tcp` (for example 8100). The port is off by default.
3. Restart the add-on. If the port is mapped but no token is set, the API port does not start and the log says why.

That port serves only `/api/v1/*` and only with `Authorization: Bearer <token>`; every other path returns 404. It is plain HTTP, so use it only on a network you trust. Ingress access is unchanged.

Store the token in `secrets.yaml`, including the word `Bearer`:

```yaml
glovebox_api_header: "Bearer YOUR_TOKEN"
```

Example `configuration.yaml` (the `rest:` integration, see https://www.home-assistant.io/integrations/rest/). Replace `1` with the vehicle id from `/api/v1/vehicles`; from the HA host or another add-on use the add-on hostname or the HA IP with the host port:

```yaml
rest:
  - resource: http://homeassistant.local:8100/api/v1/vehicles/1/summary
    scan_interval: 3600
    headers:
      Authorization: !secret glovebox_api_header
    sensor:
      - name: "Car last consumption"
        value_template: "{{ value_json.last_consumption }}"
        unit_of_measurement: "L/100km"
      - name: "Car cost this month"
        value_template: "{{ value_json.cost_this_month }}"
        unit_of_measurement: "EUR"
```

Check the field names against `/api/v1/vehicles/1/summary` before relying on them.

## Data and backups

The SQLite database is stored in the add-on's `/data` folder, which survives restarts and upgrades and is included in Home Assistant backups. Database migrations run automatically at startup. You can also use the full backup in the app as a backup that does not depend on Home Assistant.

## Importing

Import a CSV (or a ZIP of CSV files, such as a full backup) on the Import page. A preset maps the columns; you can adjust it in the mapping step. The preview shows what would be added and writes nothing until you confirm. Re-importing the same file adds nothing, and every import can be undone from the batch list.

- Files without a vehicle name (Drivvo, Fuelly, Fuelio) ask which vehicle the records belong to.
- Fuelly: the `tags` column is taken as the gas station name (the whole cell, so several tags become one station), which is how our own Fuelly export keeps the station. Brands are never guessed.
- The Drivvo presets are best effort and untested. If headers are not recognised, map the columns in the mapping step and save the mapping as a preset.

## Known limitations

- The web app is only reachable through Ingress (no app login); the optional API port serves the stats API only. Anyone who can open the Home Assistant sidebar entry can use the app.
- Expenses need a title (for example the service type) and may have an optional coverage period; the dashboard can spread such costs over the period or show them as paid.
- Only the `amd64` and `aarch64` architectures are supported.

## Support

Report problems in the project's issue tracker.
