"""Base-path aware URL building (Ingress prefix, ``BASE_PATH`` or root)."""

from __future__ import annotations

import re

from fastapi import Request

INGRESS_HEADER = "X-Ingress-Path"
# The header is client-controlled; only accept plain path characters so it
# cannot inject markup into rendered pages.
_SAFE_PREFIX = re.compile(r"^/[A-Za-z0-9/_.-]*$")


def base_path(request: Request) -> str:
    """
    Return the URL prefix for this request, without trailing slash.

    Order: valid ``X-Ingress-Path`` header, then ``Settings.base_path``,
    then ``""`` (root).
    """
    header = request.headers.get(INGRESS_HEADER, "")
    if header and _SAFE_PREFIX.match(header):
        return header.rstrip("/")
    return request.app.state.settings.base_path


def url(request: Request, path: str = "/") -> str:
    """
    Build an absolute-path URL honouring the base path.

    Parameters
    ----------
    request : Request
        Current request.
    path : str, optional
        Path inside the app, with or without leading slash.

    Returns
    -------
    str
        E.g. ``/api/hassio_ingress/abc/static/app.css`` or ``/static/app.css``.
    """
    return f"{base_path(request)}/{path.lstrip('/')}"
