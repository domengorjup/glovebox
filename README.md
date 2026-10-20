# Autotracker

Self-hosted tracker for car running costs (fuel, maintenance, insurance and registration) with statistics, CSV import (Drivvo, Fuelio, Fuelly) and export. Runs as a Home Assistant add-on or as a standalone Docker container.

## Install as a Home Assistant add-on

1. Settings, Add-ons, Add-on store, menu, Repositories: add this repository's URL.
2. Install "Autotracker". The image is built locally on the HA host from `addon/autotracker/Dockerfile`.
3. Start it and enable "Show in sidebar".

Options and details: [addon/autotracker/DOCS.md](addon/autotracker/DOCS.md).

## Run standalone

```sh
docker build -t autotracker .
docker run -d --name autotracker -p 8080:8080 -v ./data:/data autotracker
```

Open `http://localhost:8080/`. The container runs as UID 1000, so the data folder must be writable by it. Either `chown 1000 ./data` or add `--user "$(id -u):$(id -g)"`. On SELinux hosts (Fedora) append `:Z` to the volume option.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `AUTOTRACKER_MODE` | `standalone` | `standalone` or `addon` (behind HA Ingress, no login) |
| `AUTOTRACKER_HOST` | `0.0.0.0` | Bind address |
| `AUTOTRACKER_PORT` | `8080` (`8099` in addon mode) | Listen port |
| `DATA_DIR` | `/data` | Folder holding the SQLite database |
| `AUTOTRACKER_PASSWORD` | unset | Enables the login (standalone) |
| `AUTOTRACKER_API_TOKEN` | unset | Bearer token for `/api/v1` (standalone) |
| `AUTOTRACKER_SECRET` | unset | Key for signing session cookies |
| `CURRENCY` | `EUR` | Display currency code |
| `BASE_PATH` | empty | URL prefix when served behind a reverse proxy |

Without `AUTOTRACKER_PASSWORD` there is no login: put a reverse proxy in front if the port is reachable by others.

## Backup and restore

Use the native full export in the app (a ZIP of CSV files plus a manifest) as a backup. To restore, start the app on a fresh `/data` volume and import that ZIP. In the add-on, `/data` is also included in Home Assistant backups.

## Add-on developer documentation used

The packaging follows the Home Assistant add-on ("app") developer docs, checked 2026-10-20 (the old `developers.home-assistant.io/docs/add-ons/` pages now redirect):

- https://contributors.home-assistant.io/apps/reference/configuration/ (`config.yaml` keys)
- https://contributors.home-assistant.io/apps/guides/options/ (options, schema, `/data/options.json`)
- https://contributors.home-assistant.io/apps/guides/ingress/ (Ingress)
- https://contributors.home-assistant.io/apps/guides/dockerfile/ (base images, `build.yaml` deprecated)
- https://contributors.home-assistant.io/apps/guides/repository/ (`repository.yaml`)
- https://contributors.home-assistant.io/apps/guides/presentation/ (README, DOCS, icon, logo)
- https://contributors.home-assistant.io/apps/guides/testing/ (local builds)
- https://contributors.home-assistant.io/apps/reference/environment/ (`/data`, ingress address)
