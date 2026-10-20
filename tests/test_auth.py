"""Tests for access control (add-on source check, login, bearer token)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glovebox.app import create_app
from glovebox.auth import INGRESS_PROXY_ADDRESS, SESSION_COOKIE, session_secret
from glovebox.config import Mode, Settings


def make_client(engine, tmp_path: Path, *, host: str = "testclient", **kw) -> TestClient:
    app = create_app(Settings(data_dir=tmp_path, **kw), engine)
    return TestClient(app, client=(host, 50000), follow_redirects=False)


# --- add-on mode -------------------------------------------------------------

def test_addon_rejects_other_addresses(engine, tmp_path):
    c = make_client(engine, tmp_path, mode=Mode.ADDON, host="192.168.1.5")
    assert c.get("/").status_code == 403
    assert c.get("/api/v1/vehicles").status_code == 403
    assert c.get("/static/pico.min.css").status_code == 403


def test_addon_accepts_ingress_proxy_without_login(engine, tmp_path):
    c = make_client(engine, tmp_path, mode=Mode.ADDON, host=INGRESS_PROXY_ADDRESS)
    assert c.get("/").status_code == 200
    assert c.get("/api/v1/vehicles").status_code == 200


def test_addon_ignores_password_and_has_no_login(engine, tmp_path):
    c = make_client(
        engine, tmp_path, mode=Mode.ADDON, host=INGRESS_PROXY_ADDRESS, password="pw"
    )
    assert c.get("/").status_code == 200
    assert c.get("/login").status_code == 404


# --- standalone login --------------------------------------------------------

def test_no_password_open_and_warns(engine, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="glovebox.auth"):
        c = make_client(engine, tmp_path)
    assert "GLOVEBOX_PASSWORD" in caplog.text
    assert c.get("/").status_code == 200
    assert c.get("/api/v1/vehicles").status_code == 200


def test_login_required_redirects(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/login").status_code == 200
    assert c.get("/static/pico.min.css").status_code == 200


def test_redirect_honours_ingress_prefix(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    r = c.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.headers["location"] == "/api/hassio_ingress/abc/login"


def test_wrong_password_denied_no_cookie(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    r = c.post("/login", data={"password": "nope"})
    assert r.status_code == 401
    assert SESSION_COOKIE not in r.cookies
    assert c.get("/").status_code == 303


def test_login_logout_cycle(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    r = c.post("/login", data={"password": "pw"})
    assert r.status_code == 303 and SESSION_COOKIE in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/").status_code == 200
    c.post("/logout")
    assert c.get("/").status_code == 303


def test_forged_cookie_rejected(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    c.cookies.set(SESSION_COOKIE, "forged.value.here")
    assert c.get("/").status_code == 303


def test_cookie_from_other_secret_rejected(engine, tmp_path):
    a = make_client(engine, tmp_path, password="pw", secret="one")
    b = make_client(engine, tmp_path, password="pw", secret="two")
    a.post("/login", data={"password": "pw"})
    b.cookies.set(SESSION_COOKIE, a.cookies[SESSION_COOKIE])
    assert b.get("/").status_code == 303


def test_secret_derived_from_password_when_missing():
    s1 = session_secret(Settings(password="pw"))
    assert s1 == session_secret(Settings(password="pw"))
    assert s1 != session_secret(Settings(password="other"))
    assert session_secret(Settings(password="pw", secret="x")) == "x"
    with pytest.raises(ValueError):
        session_secret(Settings())


# --- standalone API token ----------------------------------------------------

def test_api_missing_token_401(engine, tmp_path):
    c = make_client(engine, tmp_path, api_token="tok")
    r = c.get("/api/v1/vehicles")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert c.get("/").status_code == 200  # HTML unaffected without a password


def test_api_bearer_token(engine, tmp_path):
    c = make_client(engine, tmp_path, api_token="tok")
    ok = c.get("/api/v1/vehicles", headers={"Authorization": "Bearer tok"})
    bad = c.get("/api/v1/vehicles", headers={"Authorization": "Bearer wrong"})
    assert ok.status_code == 200 and bad.status_code == 401


def test_api_accepts_session_when_token_set(engine, tmp_path):
    c = make_client(engine, tmp_path, api_token="tok", password="pw")
    assert c.get("/api/v1/vehicles").status_code == 401
    c.post("/login", data={"password": "pw"})
    assert c.get("/api/v1/vehicles").status_code == 200


def test_api_requires_login_when_only_password_set(engine, tmp_path):
    c = make_client(engine, tmp_path, password="pw")
    assert c.get("/api/v1/vehicles").status_code == 401


# --- add-on API listener (design D9a) ----------------------------------------

TOKEN = "t" * 16


def make_api_client(engine, tmp_path: Path, **kw) -> TestClient:
    from glovebox.app import create_api_app

    settings = Settings(
        data_dir=tmp_path, mode=Mode.ADDON, api_token=TOKEN, api_port=8100, **kw
    )
    main_app = create_app(settings, engine)
    return TestClient(create_api_app(main_app), client=("192.168.1.5", 50000))


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_api_listener_requires_token(engine, tmp_path):
    c = make_api_client(engine, tmp_path)
    response = c.get("/api/v1/vehicles")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_api_listener_wrong_token(engine, tmp_path):
    c = make_api_client(engine, tmp_path)
    assert c.get("/api/v1/vehicles", headers=bearer("x" * 16)).status_code == 401
    assert c.get("/api/v1/vehicles", headers=bearer("")).status_code == 401


def test_api_listener_valid_token_from_any_address(engine, tmp_path):
    c = make_api_client(engine, tmp_path)
    assert c.get("/api/v1/vehicles", headers=bearer()).status_code == 200


@pytest.mark.parametrize("path", ["/", "/static/pico.min.css", "/docs", "/login"])
def test_api_listener_serves_nothing_else(engine, tmp_path, path):
    c = make_api_client(engine, tmp_path)
    assert c.get(path).status_code == 404
    assert c.get(path, headers=bearer()).status_code == 404


def test_ingress_listener_unchanged_with_api_enabled(engine, tmp_path):
    kw = {"mode": Mode.ADDON, "api_token": TOKEN, "api_port": 8100}
    other = make_client(engine, tmp_path, host="192.168.1.5", **kw)
    assert other.get("/api/v1/vehicles", headers=bearer()).status_code == 403
    proxy = make_client(engine, tmp_path, host=INGRESS_PROXY_ADDRESS, **kw)
    assert proxy.get("/").status_code == 200
    assert proxy.get("/api/v1/vehicles").status_code == 200


def test_api_listener_not_started_without_token(tmp_path, caplog):
    from glovebox.app import api_listener_enabled

    settings = Settings(data_dir=tmp_path, mode=Mode.ADDON, api_port=8100)
    with caplog.at_level(logging.WARNING, logger="glovebox.app"):
        assert api_listener_enabled(settings) is False
    assert "api_token" in caplog.text


def test_api_listener_started_with_token(tmp_path):
    from glovebox.app import api_listener_enabled

    settings = Settings(
        data_dir=tmp_path, mode=Mode.ADDON, api_token=TOKEN, api_port=8100
    )
    assert api_listener_enabled(settings) is True


def test_api_listener_never_in_standalone(tmp_path):
    from glovebox.app import api_listener_enabled

    settings = Settings(data_dir=tmp_path, api_token=TOKEN, api_port=8100)
    assert api_listener_enabled(settings) is False


def test_short_addon_token_rejected(tmp_path):
    from glovebox.config import load_settings

    env = {"GLOVEBOX_MODE": "addon", "GLOVEBOX_API_TOKEN": "short"}
    with pytest.raises(ValueError, match="at least 16"):
        load_settings(env, tmp_path / "none.json")


def test_short_token_still_fine_in_standalone(tmp_path):
    from glovebox.config import load_settings

    settings = load_settings({"GLOVEBOX_API_TOKEN": "short"}, tmp_path / "none.json")
    assert settings.api_token == "short"


def test_main_exits_with_message_on_short_token(monkeypatch):
    from glovebox.app import main

    monkeypatch.setenv("GLOVEBOX_MODE", "addon")
    monkeypatch.setenv("GLOVEBOX_API_TOKEN", "short")
    with pytest.raises(SystemExit, match="at least 16"):
        main()
