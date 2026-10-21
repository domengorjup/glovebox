# Third-party notices

Glovebox itself is released under the MIT licence (see `LICENSE`). This file lists third-party material that is bundled with it.

## Vendored front-end assets

Located in `src/glovebox/web/static/`. Licence texts sit next to the files (see `VENDORED.md`).

| Asset | Version | Licence | Copyright |
|---|---|---|---|
| Material Design Icons (`icons.svg`, 18 icons from `@mdi/svg`, paths unmodified) | 7.4.47 | Apache-2.0 via the Pictogrammers Free License (`LICENSE-mdi.md`) | No per-icon copyright line in the package |

## Python dependencies

Python dependencies (FastAPI, Uvicorn, SQLAlchemy, Alembic, Jinja2, python-multipart, itsdangerous and their dependencies) are not vendored. They are installed from PyPI at image build time, and each package ships its own licence file in its `*.dist-info` directory inside the image.

## Icons

`addon/glovebox/icon.png` and `addon/glovebox/logo.png` were generated for this project and are covered by the project licence.

## Trademarks

Drivvo, Fuelio, Fuelly and Home Assistant are trademarks of their respective owners. This project is not affiliated with or endorsed by them.
