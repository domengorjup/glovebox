# Contributing

Contributions are welcome. Open an issue first for anything larger than a small fix, so we can agree on the approach.

## A good first contribution: an import preset

If you use a fuel or car-cost app that Glovebox has no preset for, or one whose preset is marked *never tested against a real export*, a preset is the easiest way to help. It is a short TOML file, needs no Python, and makes Glovebox useful to everyone moving from that app.

1. Export your data from the app and note exactly how you did it (platform, menu path, options).
2. In Glovebox, import the file, adjust the column mapping until the preview is clean, and save it as a preset. Download it from **Manage → Presets**.
3. Follow [Writing a preset](importers.md#writing-a-preset): add the `# Export:` comment, a one-line note saying what it was tested with, `steps` if the import needs more than upload, review, import (short, phone-friendly: about 8 words each, at most 5), and put the file in `src/glovebox/presets/`.
4. Add a small **made-up** fixture with the same layout (real column names, invented values) and a test, as the existing presets do. Never commit your real export: it contains personal data.
5. Run the checks below and open a pull request.

Confirming that an existing untested preset works with a real export is just as useful: report it in an issue, or send the fixes and set `verified = true`.

## Other contributions

- Bugs and ideas: open an issue with steps to reproduce.
- Code: see [Local development](development.md) and [Testing](testing.md). UI changes follow the [design language](design.md).

## Checks before a pull request

```sh
uv run pytest
uv run python -m glovebox.formatdocs --check
uv run --group docs mkdocs build --strict
```
