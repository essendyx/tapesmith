"""Sicherung (`/backups`) und Konfiguration als Code (`/config/export`,
`/config/import`)."""

import json

import pytest

from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


# ---------- Sicherung ----------

def test_backups_create_and_list(api):
    client, ctx = api
    r = client.post("/api/v1/backups", json={})
    assert r.status_code == 200
    created = r.json()
    assert created["name"].startswith("tapesmith-backup-")
    assert created["size_bytes"] > 0

    r = client.get("/api/v1/backups")
    assert r.status_code == 200
    body = r.json()
    assert body["dir"]
    names = [b["name"] for b in body["backups"]]
    assert created["name"] in names


def test_backups_restore_dry_run(api):
    client, _ = api
    created = client.post("/api/v1/backups", json={}).json()
    r = client.post("/api/v1/backups/restore", json={"name": created["name"], "dry_run": True})
    assert r.status_code == 200
    assert r.json()["lines"]


def test_backups_restore_ohne_dry_run_ist_409(api):
    client, _ = api
    created = client.post("/api/v1/backups", json={}).json()
    r = client.post("/api/v1/backups/restore", json={"name": created["name"], "dry_run": False})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["kind"] == "Dienst läuft"
    assert "tapesmith daemon stop" in err["message"]
    assert "tapesmith backup restore" in err["message"]
    assert created["name"] in err["message"]


def test_backups_restore_unbekannter_name_404(api):
    client, _ = api
    r = client.post("/api/v1/backups/restore", json={"name": "unbekannt.zip", "dry_run": True})
    assert r.status_code == 404


# ---------- Konfiguration als Code ----------

def test_config_export_erzeugt_manifest(api, tmp_path):
    client, _ = api
    target = tmp_path / "export"
    r = client.post("/api/v1/config/export",
                    json={"dir": str(target), "include_templates": True, "strip_secrets": False})
    assert r.status_code == 200
    files = r.json()["files"]
    assert any(f.endswith("MANIFEST.json") for f in files)
    assert (target / "MANIFEST.json").exists()


def test_config_import_dry_run_ohne_ereignis(api, tmp_path, monkeypatch):
    client, ctx = api
    target = tmp_path / "export"
    client.post("/api/v1/config/export", json={"dir": str(target), "include_templates": True,
                                               "strip_secrets": False})

    called = []
    monkeypatch.setattr(ctx.service, "request_reload", lambda: called.append(True))
    sub = ctx.broker.subscribe()

    r = client.post("/api/v1/config/import",
                    json={"dir": str(target), "dry_run": True, "include_templates": True})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["changes"], list)
    assert body["backup_dir"] is None
    assert called == []
    assert sub.get(0.05) is None


def test_config_import_loest_reload_und_ereignis_aus(api, tmp_path, monkeypatch):
    client, ctx = api
    target = tmp_path / "export"
    client.post("/api/v1/config/export", json={"dir": str(target), "include_templates": True,
                                               "strip_secrets": False})

    called = []
    monkeypatch.setattr(ctx.service, "request_reload", lambda: called.append(True))
    sub = ctx.broker.subscribe()

    r = client.post("/api/v1/config/import",
                    json={"dir": str(target), "dry_run": False, "include_templates": True})
    assert r.status_code == 200
    assert called == [True]
    event = sub.get(1.0)
    assert event is not None
    name, data = event
    assert name == "config"
    assert data == {"keys": ["*"]}


def test_config_import_fehlender_ordner_422(api, tmp_path):
    client, _ = api
    r = client.post("/api/v1/config/import",
                    json={"dir": str(tmp_path / "nichts"), "dry_run": True, "include_templates": True})
    assert r.status_code == 422


def test_config_export_secrets_ohne_strip_422(api, tmp_path):
    client, ctx = api
    from tapesmith import config as config_mod

    config_mod.save_config({"api_token": "geheim123"})
    target = tmp_path / "export2"
    r = client.post("/api/v1/config/export",
                    json={"dir": str(target), "include_templates": False, "strip_secrets": False})
    assert r.status_code == 422
