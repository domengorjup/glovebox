# Changelog

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
