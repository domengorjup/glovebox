# Project layout

```text
src/glovebox/
  app.py            create_app() factory and main() entry point
  config.py         settings from env vars and add-on options
  db.py, models.py  engine, session, SQLAlchemy models
  auth.py           add-on source check, login, Bearer token
  urls.py           url(request, path) base-path helper
  migrations/       Alembic
  services/         records.py, stats.py
  standard.py       the standard CSV format (fields, descriptor)
  formatdocs.py     generates docs/user/standard-format.md and presets.md
  presets/          shipped presets (*.toml)
  importers/        base.py, presets.py, engine.py, pipeline.py
  exporters/        csv_export.py, backup.py
  api/v1.py         stats API
  web/              routes, templating.py, templates/, static/
addon/glovebox/     config.yaml, Dockerfile, DOCS.md, CHANGELOG.md, icons
repository.yaml     add-on repository descriptor
Dockerfile          standalone image
docker/entrypoint.sh
tests/              pytest suite; fixtures/ holds anonymised samples
docs/               this documentation (assets/screenshots/ holds the images)
mkdocs.yml
.github/workflows/  tests.yml (pytest), docs.yml (GitHub Pages)
.dev/               local helper scripts and demo data (make_demo_data.py)
```
