"""Update-Routen mit Fake-Quelle im Temp-Ordner, Fake-Spawn, synchronem Runner."""

from __future__ import annotations

import sys
from datetime import datetime

import pytest

from tapesmith.update.service import UpdateService
from update_fakes import FakeVenvRun, install_layout, make_test_key, publish_dir
from webapi_fakes import close_ctx, make_client, make_token


@pytest.fixture
def env(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx, tmp_path
    close_ctx(ctx)


def _svc(tmp_path, *, installed: bool):
    private, keys = make_test_key()
    feed = tmp_path / "feed"
    publish_dir(feed, "0.2.1", private)
    root = tmp_path / "root"
    exe = str(sys.executable)
    if installed:
        install_layout(root)
        exe = str(root / "versions" / "0.1.0" / "Scripts" / "pythonw.exe")
    spawned = []
    cfg = {"update": {"source": f"file:{feed}"}}
    svc = UpdateService(lambda: cfg, keys_loader=lambda: keys, root=root, spawn=spawned.append, run=FakeVenvRun(),
                        now=lambda: datetime(2026, 10, 2, 8, 0), executable=exe, app_version=lambda: "0.1.0")
    return svc, spawned, root


def test_status_ohne_installation(env):
    client, _ctx, _tmp = env
    r = client.get("/api/v1/update/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["installed"] is False
    assert set(data) == {"installed", "current", "previous", "root", "enabled", "source", "channel",
                         "auto_install", "last_check", "available", "state", "error", "can_rollback", "idle_ok",
                         "consent_needed", "installed_elsewhere"}
    assert data["enabled"] is False and data["consent_needed"] is False
    assert data["source"] == "github:essendyx/tapesmith"


def test_check_mit_fake_quelle(env):
    client, ctx, tmp = env
    svc, _spawned, _root = _svc(tmp, installed=False)
    ctx.extras["update_service"] = svc
    r = client.post("/api/v1/update/check")
    assert r.status_code == 200, r.text
    assert r.json()["available"]["version"] == "0.2.1"


def test_check_fehler_traegt_code(env):
    client, ctx, tmp = env
    svc, _spawned, _root = _svc(tmp, installed=False)
    svc.keys_loader = lambda: []
    ctx.extras["update_service"] = svc
    r = client.post("/api/v1/update/check")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "update.no_trusted_key"
    assert err["kind"] == "UpdateError"
    assert "Signaturschlüssel" in err["message"]


def test_install_nicht_installiert_409(env):
    client, ctx, tmp = env
    svc, spawned, _root = _svc(tmp, installed=False)
    ctx.extras["update_service"] = svc
    r = client.post("/api/v1/update/install", json={"version": "0.2.1", "reopen_route": None})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "update.not_installed"
    assert spawned == []


def test_install_bei_belegtem_dienst_409_busy(env, monkeypatch):
    client, ctx, tmp = env
    svc, spawned, _root = _svc(tmp, installed=True)
    ctx.extras["update_service"] = svc
    monkeypatch.setattr(ctx.service, "busy", lambda: True)
    r = client.post("/api/v1/update/install", json={"version": "0.2.1", "reopen_route": "/"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "update.busy"
    assert spawned == []


def test_install_202_bereitet_vor_und_startet(env):
    client, ctx, tmp = env
    svc, spawned, root = _svc(tmp, installed=True)
    ctx.extras["update_service"] = svc
    ctx.extras["update_runner"] = lambda fn: fn()
    r = client.post("/api/v1/update/install", json={"version": "0.2.1", "reopen_route": "/einstellungen"})
    assert r.status_code == 202, r.text
    assert r.json() == {"started": True}
    assert (root / "versions" / "0.2.1" / "Scripts" / "pythonw.exe").is_file()
    assert spawned and spawned[0][1:5] == ["-m", "tapesmith.update.apply", "--version", "0.2.1"]
    assert spawned[0][-2:] == ["--reopen-route", "/einstellungen"]
    assert client.get("/api/v1/update/status").json()["state"] == "installing"


def test_install_laeuft_schon_409(env):
    client, ctx, tmp = env
    svc, spawned, _root = _svc(tmp, installed=True)
    ctx.extras["update_service"] = svc
    pending = []
    ctx.extras["update_runner"] = pending.append
    assert client.post("/api/v1/update/install", json={"version": "0.2.1"}).status_code == 202
    r = client.post("/api/v1/update/install", json={"version": "0.2.1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "update.busy"
    pending[0]()
    assert spawned
    ctx.extras["update_runner"] = lambda fn: fn()
    assert client.post("/api/v1/update/install", json={"version": "0.2.1"}).status_code == 202


def test_install_fehler_im_hintergrund_landet_im_status(env):
    client, ctx, tmp = env
    svc, spawned, _root = _svc(tmp, installed=True)
    ctx.extras["update_service"] = svc
    ctx.extras["update_runner"] = lambda fn: fn()
    r = client.post("/api/v1/update/install", json={"version": "9.9.9"})
    assert r.status_code == 202
    status = client.get("/api/v1/update/status").json()
    assert status["state"] == "failed" and status["error"]["code"] == "update.download_failed"
    assert spawned == []


def test_rollback_ohne_vorige_und_mit(env):
    client, ctx, tmp = env
    svc, spawned, root = _svc(tmp, installed=True)
    ctx.extras["update_service"] = svc
    r = client.post("/api/v1/update/rollback", json={})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "update.apply_failed"
    install_layout(root, versions=("0.1.0", "0.2.0"), current="0.2.0")
    svc.executable = str(root / "versions" / "0.2.0" / "Scripts" / "pythonw.exe")
    r = client.post("/api/v1/update/rollback")
    assert r.status_code == 202, r.text
    assert "--rollback" in spawned[-1]


def test_safe_route():
    from tapesmith.webapi.routes_update import safe_route

    assert safe_route("/einstellungen?abschnitt=updates") == "/einstellungen?abschnitt=updates"
    for bad in (None, "", "einstellungen", "//evil.example/x", "/a b", "/" + "x" * 600, "--help"):
        assert safe_route(bad) is None


def test_install_body_pruefung(env):
    client, _ctx, _tmp = env
    r = client.post("/api/v1/update/install", json={"version": 3})
    assert r.status_code == 422


def test_rolle_drucken_403(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        secret = make_token(ctx, "drucken")
        for method, path in (("get", "/api/v1/update/status"), ("post", "/api/v1/update/check"),
                             ("post", "/api/v1/update/consent"), ("post", "/api/v1/update/install"), ("post", "/api/v1/update/rollback")):
            r = getattr(client, method)(path, headers={"Authorization": f"Bearer {secret}"})
            assert r.status_code == 403, path
            assert r.json()["error"]["code"] == "auth.forbidden"
    finally:
        close_ctx(ctx)


@pytest.mark.parametrize("enabled", [True, False])
def test_rueckfrage_speichert_entscheidung(env, enabled):
    from tapesmith import config as config_mod

    client, ctx, tmp = env
    svc, _spawned, _root = _svc(tmp, installed=True)
    svc.cfg_loader = config_mod.load_config
    ctx.extras["update_service"] = svc
    assert client.get("/api/v1/update/status").json()["consent_needed"] is True
    r = client.post("/api/v1/update/consent", json={"enabled": enabled})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is enabled and r.json()["consent_needed"] is False
    saved = config_mod.load_config()["update"]
    assert saved["enabled"] is enabled and saved["asked"] is True


def test_rueckfrage_verlangt_wahrheitswert(env):
    client, _ctx, _tmp = env
    assert client.post("/api/v1/update/consent", json={"enabled": "ja"}).status_code == 422
    assert client.post("/api/v1/update/consent", json={}).status_code == 422



def test_schalter_in_den_einstellungen_beantwortet_die_rueckfrage(env):
    from tapesmith import config as config_mod

    client, _ctx, _tmp = env
    r = client.patch("/api/v1/settings", json={"changes": {"update.enabled": False}})
    assert r.status_code == 200, r.text
    assert config_mod.load_config()["update"] == {"enabled": False, "asked": True}
