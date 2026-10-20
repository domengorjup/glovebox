"""Application settings read from environment variables and add-on options."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

OPTIONS_FILE = Path("/data/options.json")


class Mode(StrEnum):
    """Deployment mode of the app."""

    STANDALONE = "standalone"
    ADDON = "addon"


@dataclass(frozen=True)
class Settings:
    """
    Immutable application settings.

    Attributes
    ----------
    mode : Mode
        ``standalone`` (default) or ``addon`` (behind HA Ingress).
    base_path : str
        URL prefix used when no ``X-Ingress-Path`` header is sent. ``""`` is root.
    data_dir : Path
        Directory holding the SQLite database.
    password : str | None
        Standalone login password; ``None`` disables the login.
    api_token : str | None
        Bearer token for ``/api/v1`` in standalone mode; ``None`` disables it.
    secret : str | None
        Key used to sign session cookies.
    currency : str
        Display currency code.
    host, port : str, int
        Bind address used by the ``autotracker`` command.
    """

    mode: Mode = Mode.STANDALONE
    base_path: str = ""
    data_dir: Path = Path("./data")
    password: str | None = None
    api_token: str | None = None
    secret: str | None = None
    currency: str = "EUR"
    host: str = "0.0.0.0"
    port: int = 8080


# Environment variable -> (Settings field, add-on options.json key)
_ENV_NAMES = {
    "AUTOTRACKER_MODE": "mode",
    "BASE_PATH": "base_path",
    "DATA_DIR": "data_dir",
    "AUTOTRACKER_PASSWORD": "password",
    "AUTOTRACKER_API_TOKEN": "api_token",
    "AUTOTRACKER_SECRET": "secret",
    "CURRENCY": "currency",
    "AUTOTRACKER_HOST": "host",
    "AUTOTRACKER_PORT": "port",
}


def _normalise_base_path(value: str) -> str:
    """Return ``value`` with a leading slash and no trailing slash ('' = root)."""
    stripped = value.strip().strip("/")
    return f"/{stripped}" if stripped else ""


def load_settings(
    env: Mapping[str, str] | None = None,
    options_file: Path = OPTIONS_FILE,
) -> Settings:
    """
    Build settings from add-on options and environment variables.

    Values in ``options_file`` (keys are the lower-case field names, e.g.
    ``api_token``) are read first when the file exists and the mode is
    ``addon``. Environment variables override them. Empty strings count as
    unset.

    Parameters
    ----------
    env : Mapping[str, str] | None, optional
        Environment to read. Default is ``os.environ``.
    options_file : Path, optional
        Add-on options file. Default is ``/data/options.json``.

    Returns
    -------
    Settings
        The resolved settings.

    Raises
    ------
    ValueError
        If the mode or port is invalid, or ``options_file`` is not valid JSON.
    """
    env = os.environ if env is None else env
    raw: dict[str, str] = {}
    if env.get("AUTOTRACKER_MODE", "") == Mode.ADDON and options_file.is_file():
        options = json.loads(options_file.read_text(encoding="utf-8"))
        raw.update({k: str(v) for k, v in options.items() if k in _ENV_NAMES.values()})
    raw.update({field: env[name] for name, field in _ENV_NAMES.items() if env.get(name)})
    return _build_settings({k: v for k, v in raw.items() if v != ""})


def _build_settings(raw: dict[str, str]) -> Settings:
    """Convert string values to typed ``Settings``."""
    mode = Mode(raw.get("mode", Mode.STANDALONE))  # ValueError if invalid
    default_dir = "/data" if mode is Mode.ADDON else "./data"
    return Settings(
        mode=mode,
        base_path=_normalise_base_path(raw.get("base_path", "")),
        data_dir=Path(raw.get("data_dir", default_dir)),
        password=raw.get("password"),
        api_token=raw.get("api_token"),
        secret=raw.get("secret"),
        currency=raw.get("currency", "EUR"),
        host=raw.get("host", "0.0.0.0"),
        port=int(raw.get("port", 8080)),
    )
