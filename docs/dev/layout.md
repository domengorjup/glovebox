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
  importers/        base.py, pipeline.py, drivvo.py, fuelio.py,
                    fuelly.py, native.py, aliases/*.toml
  exporters/        native.py, fuelly.py
  api/v1.py         stats API
  web/              routes, templating.py, templates/, static/
addon/glovebox/     config.yaml, Dockerfile, DOCS.md, CHANGELOG.md, icons
repository.yaml     add-on repository descriptor
Dockerfile          standalone image
docker/entrypoint.sh
tests/              pytest suite; fixtures/ holds anonymised samples
docs/               this documentation
mkdocs.yml
```
