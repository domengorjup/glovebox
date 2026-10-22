## Why

A real Drivvo import was confusing: the first page after the upload was the column mapping (many fields and options), the vehicle could only be chosen after pressing Preview, and the Preview button sat below all the options.

## What Changes

- **Review first:** the upload goes straight to one review page: preset select with its steps, vehicle choice (existing or "New vehicle..."), what will happen, and the Import button near the top. Changing the preset, vehicle or an answer updates the page in place.
- **Mapping on demand:** the column mapping is behind an outlined "Adjust mapping" button. It is shown directly only when no preset fits or the preset reads the file with errors. Its primary button "Back to review" is at the top and at the bottom.
- **Clearer mapping rows:** a human label first, the standard field key as small secondary text; options stay folded.
- **Next section** lands on the review page of that section.

## Capabilities

### Modified Capabilities
- `data-import`: the import steps, multi-section continuation, preset steps and the compact mapping page.
