## Why

The Drivvo presets were written without a real export. A real Drivvo Android export is now available, and it differs from the guess: single-`#` section lines, `%uXXXX` escapes, spaces after delimiters, and several equal service items on one day.

## What Changes

- **Drivvo presets:** rewritten for the real Android layout and marked verified ("Tested with Drivvo Android exports, October 2026"). The Drivvo web export holds the same records and gets no preset of its own.
- **Engine:** accepts section lines with a single `#`, decodes `%uXXXX` escapes, and skips spaces after a delimiter before a quoted field.
- **Duplicate detection:** expenses are matched one to one by count, so equal expenses inside one file are all kept and a re-import still skips them.
- **Preset detection:** on a tie between shipped presets, "Drivvo refuelling" is preferred (as "Fuelio fill-ups" already was).
- **Preset convention:** every shipped preset has an `# Export:` header comment saying how to produce the file. Presets not checked against a real export say "Never tested against a real export" and stay unverified. A test enforces the comment.

## Capabilities

### Modified Capabilities
- `data-import`: duplicate detection, shipped presets, section reading and detection tie-break; new requirement for the preset documentation convention.
