# Test fixtures

Only hand-made or fully anonymised files belong here.

- Never commit a real export from Drivvo, Fuelio, Fuelly or any other app: they
  contain personal data (plates, VINs, locations, names).
- Anonymise before use: randomise station names, offset odometer values, and
  remove plates, VINs and notes.
- Name files after the format and the case they cover, e.g.
  `fuelio_semicolon_km.csv`.
- Fixtures belong to presets: each `fuelio_*`, `fuelly_*` and `drivvo_*` file
  is the sample for the shipped preset of that name, and `standard_*` files are
  samples of the standard format (see `tests/test_presets_shipped.py`).
- `drivvo_web_sections.csv` is a sample of Drivvo's web export, which no
  shipped preset covers; it tests the engine's handling of `#Section` lines,
  `%uXXXX` escapes and quoted headers after spaces.
