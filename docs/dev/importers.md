# Importers

Every import goes through one pipeline in `importers/pipeline.py`:

```text
detect -> parse -> map vehicles -> dedupe -> preview -> commit (one transaction, one batch)
```

The web UI calls only the pipeline. Each format is an adapter with:

- `detect(head_bytes)` returning a confidence score,
- `parse(file, options)` returning an `ImportResult` (records, warnings, errors, vehicle names found).

Adapters are listed in `_ADAPTERS` in `pipeline.py`. Shared helpers in `importers/base.py` handle encoding (UTF-8 with or without BOM, then cp1252), delimiter sniffing (`,` `;` tab), decimal separators per column, and date formats (ambiguous dates make the preview ask).

## Alias files

Header names live in `importers/aliases/<format>.toml`: a canonical field maps to a list of header strings. Matching ignores case and surrounding whitespace.

```toml
[refuel]
date = ["Date"]
litres = ["Volume", "Liters", "Litres"]
```

## Add a language or locale

Add the translated header strings to the lists in the alias file. No code change. Add an anonymised fixture to `tests/fixtures/` and a test.

## Add a format

1. Write `importers/<name>.py` with an adapter and `aliases/<name>.toml`.
2. Register it in `_ADAPTERS`.
3. Add fixtures and tests. Unknown required headers must fail the preview with the found and expected lists. Never guess.
4. Mark mappings `provisional = true` in the alias file until checked against a real export.

Notes: stations are created by name; a brand is only set when the file provides one. Duplicate keys are (vehicle, date, odometer, litres to 0.01) for refuels and (vehicle, date, category, amount) for expenses.
