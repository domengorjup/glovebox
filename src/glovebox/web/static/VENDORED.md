# Vendored front-end assets

Downloaded once from the official npm packages (no CDN at runtime), 2026-10-20.

| File | Package | Version | Licence |
|------|---------|---------|---------|
| `pico.min.css` | `@picocss/pico` (`css/pico.min.css`) | 2.1.1 | MIT, see `LICENSE-pico.md` |
| `chart.umd.min.js` | `chart.js` (`dist/chart.umd.min.js`) | 4.5.1 | MIT, see `LICENSE-chartjs.md` |
| (bundled inside `chart.umd.min.js`) | `@kurkle/color` | 0.3.2 | MIT, see `LICENSE-kurkle-color.md` |

`chart.umd.min.js` is a UMD bundle that includes `@kurkle/color`, a Chart.js
dependency, hence its separate licence file.

The only edit: the trailing `sourceMappingURL` comment was removed from
`chart.umd.min.js`. `app.css` and `app.js` are this project's own files.
