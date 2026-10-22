## Why

Importing a Drivvo Android export takes too many steps: create the vehicle first in Manage, upload the same file three times (one per section), and no screen says what to do. Service items with a cost of 0 (for example an oil filter bought with the oil change) are dropped. On a phone the mapping page is very long.

## What Changes

- **New vehicle at import:** the vehicle question of the preview gains a "New vehicle..." choice with a name field. The vehicle is created inside the commit transaction (like vehicles created from vehicle names; undo keeps it).
- **Next section without re-upload:** after importing one section of a multi-section file the result offers "Import next section: <section>". The uploaded file is kept on the server until then, the preset of that section is detected, and the vehicle of the previous section is pre-selected.
- **Zero-cost items:** a new preset option `zero_amount = "note"` turns expense rows with an amount of 0 into text on the priced expense of the same visit (same date and odometer): "Also: Oil filter, Air filter". Without a priced expense of the visit they are skipped and counted. The Drivvo services preset uses it.
- **Preset steps:** presets get an optional `steps` list. The mapping page shows it as a short numbered list under the preset select as soon as the preset is selected. The Drivvo presets ship steps. Rule: when importing with a preset needs more than "upload, preview, import", the preset gets `steps`.
- **Shorter mapping page on phones:** the File settings fold into a collapsed block when auto-detection worked, and the per-column rows are more compact. No function is hidden.

## Capabilities

### Modified Capabilities
- `data-import`: vehicle mapping, preset file format; new requirements for multi-section files, zero-amount items and preset steps.
