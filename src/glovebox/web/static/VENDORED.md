# Vendored front-end assets

No CDN is used at runtime.

| File | Source | Version | Licence |
|------|--------|---------|---------|
| `icons.svg` | Material Design Icons (`@mdi/svg`, Pictogrammers) | 7.4.47 | Apache-2.0 via the Pictogrammers Free License, see `LICENSE-mdi.md` |

Only the 18 icons used are included; paths are unmodified (taken from `svg/<name>.svg` of the package and wrapped in `<symbol>` elements).

Charts are drawn by the project's own inline-SVG JavaScript. `app.css`, `app.js` and `theme.js` are project files.
