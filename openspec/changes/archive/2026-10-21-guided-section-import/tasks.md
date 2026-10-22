## 1. Mockup
- [x] 1.1 Living mockup: import mapping page (steps, collapsed File block, compact rows) and the next-section state, logged in NOTES.md

## 2. Implementation
- [x] 2.1 Presets: `steps` and `zero_amount` keys (parse, write, key table, docs generator)
- [x] 2.2 Engine: fold zero-amount expense rows into the note of the visit's priced expense, count the rest as skipped
- [x] 2.3 Pipeline: new default vehicle created in the commit transaction, with name validation; section-aware preset detection
- [x] 2.4 Web: "New vehicle..." choice in the preview; keep the upload after a multi-section import and offer "Import next section"; carry the vehicle between sections
- [x] 2.5 Web: steps list under the preset select; collapsed File block and compact rows on the mapping page
- [x] 2.6 Drivvo presets: steps, short notes, `zero_amount`

## 3. Tests and docs
- [x] 3.1 Tests: presets, engine, pipeline, web UI, e2e (upload, new vehicle, import, next section twice)
- [x] 3.2 Docs: user import page, "Writing a preset", contributing, design.md, generated presets page
- [x] 3.3 Screenshots of the mapping page and the next-section state
