# Import

Go to **Manage → Import**.

![Import preview](../assets/screenshots/import-preview-desktop-light.png)

## Supported formats

| Format | File | Status |
|---|---|---|
| Fuelio | Backup CSV, or a ZIP with one CSV per vehicle | Based on public descriptions of the format |
| Fuelly | Import-format and export-format CSV | Based on public descriptions of the format |
| Drivvo | CSV for refuelling, service and expenses | **Provisional.** Not yet checked against a real export |
| Glovebox native | ZIP made by Glovebox export | Full round trip |

!!! warning "Drivvo is provisional"
    The English Drivvo column names are a best guess. If your file is not recognised, the preview lists the headers it found and the ones it expected, and imports nothing. Please report such a case (without personal data) so the mapping can be fixed.

## How to get a file from each app

Menus change between app versions, so treat these as pointers.

- **Fuelio**: use the app's backup or CSV export function and copy the file to your computer. Fuelio writes one file per vehicle; you can upload a ZIP of them.
- **Fuelly**: use the export function of your Fuelly account on the website. Glovebox also reads the CSV format that Fuelly accepts for its own import.
- **Drivvo**: the app exports a CSV per vehicle from the History tab, following the active filter. It needs a paid plan. Headers are in the app language.

## Steps

1. Choose the file. Glovebox detects the format; you can override it.
2. Read the **preview**. It shows record counts, vehicles found, duplicates, warnings and errors. Nothing is written yet.
3. Answer any questions (see below).
4. Click confirm. All records are added together as one **import batch**.

### Questions you may be asked

- **Vehicle**: the file's vehicle names can be mapped to an existing vehicle or to a new one. Files with no vehicle name (Drivvo, Fuelly import format) ask which vehicle to use.
- **Dates**: if every date fits both day-first and month-first (like `03/04/2024`), you choose the order.
- **Units**: if a file does not say whether it uses miles and gallons or km and litres, you choose. Miles and gallons are converted to km and litres.

## Good to know

- **Re-importing is safe.** Records matching an existing one (same vehicle, date, odometer and litres for refuellings; same vehicle, date, category and amount for expenses) are skipped and counted.
- **Undo.** Every import appears in the batch list and can be undone. That deletes the records it added, and any stations only that import created.
- **Fuelly stations.** The `tags` cell becomes the station name (the whole cell). No brand is set.
- **Brands** are never guessed on import. Set them under [Gas stations](stations.md).
- Fuelio rows marked as template or income, and costs of zero or less, are skipped.
