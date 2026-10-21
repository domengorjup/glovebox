# Export and backup

Go to **Manage → Export**.

| Export | Content |
|---|---|
| **Full CSV** | A ZIP with `vehicles.csv`, `stations.csv`, `refuels.csv`, `expenses.csv` and `manifest.json`. Everything, for all vehicles. |
| **Fuelly-compatible CSV** | Refuellings only, one CSV per vehicle (zipped if there is more than one). Expenses are left out. The station goes into the `tags` column. |

## Backup and restore

The full export is your portable backup.

To restore: start Glovebox on an empty data folder, then import the ZIP on the Import page. Everything comes back as it was, including which price figure was derived.

For the add-on, `/data` is also included in normal Home Assistant backups.

!!! tip
    Export now and then and keep the file outside Home Assistant. It does not depend on the add-on or on any one install.
