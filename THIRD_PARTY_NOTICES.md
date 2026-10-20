# Third-party notices

Glovebox itself is released under the MIT licence (see `LICENSE`). This file lists third-party material that is bundled with it or was used as a reference.

## Vendored front-end assets

Located in `src/glovebox/web/static/`. Licence texts sit next to the files (see `VENDORED.md`).

| Asset | Version | Licence | Copyright |
|---|---|---|---|
| Pico.css (`pico.min.css`) | 2.1.1 | MIT (`LICENSE-pico.md`) | Copyright (c) 2019-2024 Pico |
| Chart.js (`chart.umd.min.js`) | 4.5.1 | MIT (`LICENSE-chartjs.md`) | Copyright (c) 2014-2024 Chart.js Contributors |
| @kurkle/color (bundled inside `chart.umd.min.js`) | 0.3.2 | MIT (`LICENSE-kurkle-color.md`) | Copyright (c) 2018-2021 Jukka Kurkela |

## Test data

`tests/test_export_fuelly.py` contains a subset of the import column aliases from LubeLogger (`MapProfile/ImportMappers.cs`, https://github.com/hargata/lubelog), used to check that the Fuelly-compatible export header is accepted by LubeLogger. LubeLogger is MIT licensed, Copyright (c) 2024 Hargata Softworks.

## Format research

- Fuelio CSV format: https://github.com/Programistyk/FuelioImport (MIT, Copyright (c) 2022 Programistyk Kamil Kamiński).
- Fuelio CSV format: https://github.com/songsit2017/Fuel-log. Only facts about the file format were used. The repository carries no licence and no code was copied.

## Python dependencies

Python dependencies (FastAPI, Uvicorn, SQLAlchemy, Alembic, Jinja2, python-multipart, itsdangerous and their dependencies) are not vendored. They are installed from PyPI at image build time, and each package ships its own licence file in its `*.dist-info` directory inside the image.

## Icons

`addon/glovebox/icon.png` and `addon/glovebox/logo.png` were generated for this project and are covered by the project licence.

## Trademarks

Drivvo, Fuelio, Fuelly and Home Assistant are trademarks of their respective owners. This project is not affiliated with or endorsed by them.
