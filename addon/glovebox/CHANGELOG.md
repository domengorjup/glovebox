# Changelog

## 0.2.5

- Quick add for refuelling, service and expense: phone-first forms (station suggestions, recent titles, Regular service) opened from + or directly from an HA shortcut (/quick, /quick-service, /quick-expense), saved with an Undo snackbar. Odometer in service and expense add forms is a suggestion; left empty, the last reading is saved as an estimate. Groundwork for reminders (not visible yet); the add-on now requests Home Assistant API access for the coming calendar sync.

## 0.2.4

- Import opens a short review page (preset steps, vehicle choice, Import now); column mapping only when needed. Timeline summaries: period picker per vehicle (this month, 30 days, this year, 12 months, all time, custom) with fair comparisons. Vehicle details (VIN, year, engine, tyres, insurance and registration dates) in a folded section. Presets: full notes, editable notes, lock and duplicate. Vehicle delete offers a backup download. Version shown in the app bar.

## 0.2.3

- Import: preset steps, new vehicle while importing, next section without re-upload, zero-cost service items kept as notes, shorter mapping page on phones. Delete a gas station and move its refuels to another. Customise opens as a bottom sheet on phones. Fix: average price per litre card was 1000x too small.

## 0.2.2

- Drivvo presets verified against real Android exports; equal expenses in one file are no longer merged as duplicates; contributing guide.

## 0.2.1

- Expenses and services: the form shows the last recorded odometer; if left empty, that reading is used, marked as estimated and kept out of distance statistics.

## 0.2.0

- First public release.
- Redesigned interface that follows Home Assistant's look and theme: Timeline with configurable summaries, Stats, Manage, a + button for new entries.
- Configurable CSV import with presets and a mapping step; documented standard CSV format; Fuelly-compatible export; full backup.
- v1 backup ZIPs can no longer be imported: make a new full backup after upgrading.

## 0.1.3

- Import and export now use presets with a mapping step instead of per-app importers; any CSV can be mapped, and mappings can be saved as presets.
- New documented standard CSV format; ZIPs may carry vehicles.csv and stations.csv.
- Full backup is now the standard format plus vehicle and station tables. v1 backup ZIPs can no longer be imported: make a new full backup after upgrading.
- Fuelio files are imported once per section (fill-ups, then costs).
- Stats: monthly average consumption line.

## 0.1.2

- Redesigned interface that follows the Home Assistant look: Timeline, Stats and Manage tabs, configurable summaries, a + button for new entries, and full vehicle management.

## 0.1.1

- Fix: the add-on failed to start (entrypoint not executable).
- Each add-on version now builds from its own git tag.

## 0.1.0

- First release: vehicles, refuelling, maintenance and insurance records, statistics, CSV import (Drivvo, Fuelio, Fuelly) and export (native, Fuelly).
