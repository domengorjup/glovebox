# Export and backup

Go to **Manage → Export**.

| Export | Content |
|---|---|
| **Standard CSV** | One `records.csv`-style file with all refuellings and expenses, in the documented [standard format](standard-format.md). |
| **Fuelly-compatible CSV** | Refuellings only, one CSV per vehicle (zipped if there is more than one). Expenses are left out. The station goes into the `tags` column. |
| **Custom CSV** | Your own layout: pick the columns and their headers, the delimiter, the decimal separator, the date pattern and the units. Save it as a preset to reuse it (and to import files in that layout). |
| **Full backup** | A ZIP with `records.csv`, `vehicles.csv`, `stations.csv` and `datapackage.json`. Everything, including stations without refuellings. |

Tick vehicles to export only those; with none ticked, all vehicles are exported. The page also offers the description of the standard format as a Data Package descriptor.

If two vehicles share a name (an archived one and an active one), the archived one is written as `Name (archived)` so that the files stay unambiguous. The page tells you when this happens.

## Backup and restore

The full backup is your portable backup.

To restore: start Glovebox on an empty data folder, then import the ZIP on the Import page. It goes straight to the preview. Vehicles with their details, stations, refuellings and expenses come back as they were, including which price figure was derived and where each record came from.

The same ZIP, without `datapackage.json`, is also a normal import with vehicle and station details; see [Import](import.md).

For the add-on, `/data` is also included in normal Home Assistant backups.

!!! tip
    Make a backup now and then and keep the file outside Home Assistant. It does not depend on the add-on or on any one install.
