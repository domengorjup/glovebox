# Testing

Run everything with `uv run pytest`.

- `tests/conftest.py` provides a migrated in-memory `engine`, a `session` and a `client` fixture.
- `tests/test_e2e.py` drives the real web forms with no monkeypatching.
- API responses are pinned by tests (`test_api_v1.py`), because field names are stable within v1.
- Statistics are tested against hand-computed examples (for example the 6.67 L/100 km segment).

## Fixtures

Files in `tests/fixtures/` are hand-made or fully anonymised.

!!! danger
    Never commit a real export from Drivvo, Fuelio, Fuelly or any other app. They contain personal data such as plates, VINs, locations and names.

When you base a fixture on a real file: randomise station names, offset odometer values, and remove plates, VINs and notes. Name files after the format and the case, for example `fuelio_semicolon_km.csv`.
