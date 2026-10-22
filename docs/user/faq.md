# Troubleshooting and FAQ

## The add-on does not appear in the store

Open the add-on store menu (in newer Home Assistant versions the apps store, **Settings → Apps → Install app**) and choose **Check for updates** (or reload the page). Then check that the repository URL under **Repositories** is `https://github.com/domengorjup/glovebox`. Glovebox supports `amd64` and `aarch64` only.

## The add-on will not start

Open the add-on's **Log** tab. A common cause is an `api_token` shorter than 16 characters; the log says so. After fixing options, restart.

## The first install is slow

The image is built on your Home Assistant host. A few minutes is normal.

## The API port does not answer

You need both a token (16+ characters) and a host port set for `8100/tcp`. Restart after changing either. See [Stats API](api.md).

## My import says headers are not recognised

The mapping step lists the columns of your file and the required fields that are still unmapped. This is most likely with a file from an app whose preset was never tested against a real export, or a non-English file. Map the columns yourself and save the mapping as a preset. Nothing is imported until you confirm the preview.

## Consumption shows n/a

Check that full tanks are marked as full, that no *missed fill-up* is flagged in the stretch, and that there are at least two full fills with rising odometer values. See [Statistics](statistics.md#how-consumption-is-calculated).

## A home-screen shortcut on Android

In the Home Assistant Android app, open **Settings > Companion app > Manage shortcuts**, add a shortcut of type *Dashboard* with the path `/dc7a9428_glovebox`, and pin it to the home screen (Android 8 or later). See the [companion app docs](https://companion.home-assistant.io/docs/integrations/android-shortcuts/). The path of the Glovebox panel is the part after your HA address when Glovebox is open in the sidebar.

## Where is my data? How do I back it up?

In a SQLite database in `/data` (add-on: included in Home Assistant backups; standalone: the folder you mounted). Use the [full export](export.md) for a backup that does not depend on the install.

## Upgrading

Database changes run automatically when the app starts. Back up first with the full export.
