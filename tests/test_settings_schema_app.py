"""Einstellungsabschnitte `oberflaeche` und `updates`, `/api/v1/app` mit Sprache und Farbschema."""

from __future__ import annotations

import pytest

from tapesmith import config as config_mod
from tapesmith import paths
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _sections(body: dict) -> dict:
    return {s["id"]: s for s in body["sections"]}


def test_oberflaeche_und_updates_mit_genau_den_sichtbaren_feldern(api):
    client, _ctx = api
    body = client.get("/api/v1/settings").json()
    sections = _sections(body)

    ui = sections["oberflaeche"]
    assert ui["title"] == "Oberfläche"
    assert [f["key"] for f in ui["fields"]] == ["app.language", "app.theme"]
    lang, theme = ui["fields"]
    assert lang["label"] == "Sprache" and lang["type"] == "choice" and lang["value"] == "auto"
    assert lang["choices"] == [{"value": "auto", "label": "wie Windows"},
                               {"value": "de", "label": "Deutsch"}, {"value": "en", "label": "English"}]
    assert theme["label"] == "Farbschema" and theme["value"] == "system"
    assert theme["choices"] == [{"value": "system", "label": "wie Windows"}, {"value": "hell", "label": "Hell"},
                                {"value": "dunkel", "label": "Dunkel"}]

    upd = sections["updates"]
    assert upd["title"] == "Updates"
    fields = {f["key"]: f for f in upd["fields"]}
    # Quelle, Prüfabstand, Leerlauf und ältere Versionen stehen nur in config.json, das Token entfällt.
    assert list(fields) == ["update.enabled", "update.auto_install", "update.channel"]
    assert fields["update.enabled"]["label"] == "Nach Updates suchen"
    assert fields["update.enabled"]["type"] == "bool"
    assert fields["update.auto_install"]["label"] == "Automatisch installieren"
    assert fields["update.channel"]["choices"] == [{"value": "stable", "label": "Stabil"},
                                                   {"value": "beta", "label": "Beta"}]


def test_app_info_liefert_sprache_und_farbschema(api):
    client, _ctx = api
    body = client.get("/api/v1/app").json()
    assert body["language"] == "auto"
    assert body["theme"] == "system"


def test_patch_sprache_speichert_und_app_liefert_sie(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"app.language": "en", "app.theme": "dunkel"}})
    assert r.status_code == 200, r.text
    body = client.get("/api/v1/app").json()
    assert body["language"] == "en"
    assert body["theme"] == "dunkel"


def test_patch_ungueltige_quelle_422_und_nichts_gespeichert(api):
    client, _ctx = api
    before = paths.config_path().read_text(encoding="utf-8")
    r = client.patch("/api/v1/settings",
                     json={"changes": {"app.language": "en", "update.source": "ftp://x"}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "value.invalid"
    assert "update.source" in err["message"]
    assert paths.config_path().read_text(encoding="utf-8") == before
    assert config_mod.setting(config_mod.load_config(), "app.language") == "auto"


def test_patch_intervall_ausserhalb_422(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"update.check_interval_h": 721}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "value.invalid"
