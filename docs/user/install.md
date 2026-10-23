# Install

## Home Assistant add-on

You need Home Assistant OS or Supervised (the add-on store). Supported architectures: `amd64` and `aarch64`.

!!! note "Add-ons are called apps in newer Home Assistant"
    Since Home Assistant 2026.6, add-ons are called **apps**: **Settings → Apps** and the **Install app** button replace **Settings → Add-ons** and the **Add-on store**. The steps are the same. This guide says "add-on" throughout.

[![Add the Glovebox repository to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdomengorjup%2Fglovebox)

Press the button above, or add the repository by hand:

1. Open **Settings → Add-ons → Add-on store** (newer versions: **Settings → Apps → Install app**).
2. Open the menu (three dots, top right) and choose **Repositories**.
3. Paste `https://github.com/domengorjup/glovebox` and click **Add**, then close the dialog.
4. Find **Glovebox** in the store and click **Install**. The image is built on your Home Assistant host, so the first install takes a few minutes.
5. Click **Start**.
6. Turn on **Show in sidebar**, then open **Glovebox** from the sidebar.

Home Assistant has already logged you in, so Glovebox has no login of its own. Anyone who can open the sidebar entry can use the app.

### Open Glovebox from your phone's home screen

With the Home Assistant Android app you can open Glovebox in one tap, which is handy at the pump:

1. In the app, open **Settings → Companion app → Manage shortcuts**.
2. Add a shortcut of type **Dashboard** with the path `/dc7a9428_glovebox` and a label such as "Glovebox".
3. Long-press the Home Assistant app icon: the shortcut is in its menu. Drag it onto the home screen to keep it there.

The shortcut opens Glovebox on the Timeline. From version 0.2.5 you can open a quick form directly with these paths instead: `/dc7a9428_glovebox/quick` (refuelling), `/dc7a9428_glovebox/quick-service` and `/dc7a9428_glovebox/quick-expense`. Older versions open the Timeline, where **+** leads to the same forms.

The path is the part after your Home Assistant address when Glovebox is open in the sidebar. See the [companion app docs](https://companion.home-assistant.io/docs/integrations/android-shortcuts/) for details.

### Options

| Option | Default | Meaning |
|---|---|---|
| `currency` | `EUR` | Three-letter code shown next to amounts. It does not convert anything. |
| `api_token` | empty | Token for the optional stats API port. See [Stats API](api.md). |

Restart the add-on after changing options.

## Standalone Docker

Build and run (the data folder must be writable by UID 1000):

```sh
docker build -t glovebox .
mkdir -p data && chown 1000 data
docker run -d --name glovebox -p 8080:8080 -v ./data:/data glovebox
```

Open `http://localhost:8080/`.

!!! tip
    Instead of `chown`, you can add `--user "$(id -u):$(id -g)"`. On SELinux hosts such as Fedora, use `-v ./data:/data:Z`.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `GLOVEBOX_MODE` | `standalone` | `standalone`, or `addon` (behind HA Ingress, no login) |
| `GLOVEBOX_HOST` | `0.0.0.0` | Bind address |
| `GLOVEBOX_PORT` | `8080` | Listen port (`8099` in add-on mode) |
| `DATA_DIR` | `/data` | Folder with the SQLite database |
| `GLOVEBOX_PASSWORD` | unset | Turns on the login page |
| `GLOVEBOX_API_TOKEN` | unset | Bearer token for `/api/v1` |
| `GLOVEBOX_SECRET` | unset | Key for signing session cookies |
| `CURRENCY` | `EUR` | Currency code for display |
| `BASE_PATH` | empty | URL prefix behind a reverse proxy |

!!! warning
    Without `GLOVEBOX_PASSWORD` there is no login. Put a reverse proxy in front of the container if other people can reach the port.
