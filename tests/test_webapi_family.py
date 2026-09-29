"""Familien-API (/familie/vorlagen, vorschau, drucken, status; Kopiengrenze, Band-Rückfrage)."""

import base64
import json

import pytest

from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith.tape.profiles import list_tapes
from tapesmith.templates import store as template_store
from tapesmith.webapi.access import LanPolicy
from webapi_fakes import close_ctx, make_client, make_token

LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",), hosts=frozenset({"192.0.2.50"}))
LAN_IP = "192.0.2.77"
LAN_URL = "http://192.0.2.50:8712"

VORLAGEN = "/api/v1/familie/vorlagen"
VORSCHAU = "/api/v1/familie/vorschau"
DRUCKEN = "/api/v1/familie/drucken"
STATUS = "/api/v1/familie/status"

DEFAULT_NAMES = ["gefriergut", "geoeffnet-am", "vorratsdose", "schule", "eigentum"]


@pytest.fixture
def made(tmp_path):
    ctxs = []

    def factory(**kw):
        client, ctx = make_client(tmp_path, **kw)
        ctxs.append(ctx)
        return client, ctx

    yield factory
    for ctx in ctxs:
        close_ctx(ctx)


def _family(made, *, role="familie", **kw):
    """LAN-Client (192.0.2.77) mit Familien-Token (API-Token, Quelle immer 'api')."""
    client, ctx = made(client_ip=LAN_IP, lan=LAN, auth=None, base_url=LAN_URL, now=FakeNow(), **kw)
    secret = make_token(ctx, role)
    client.headers["Authorization"] = f"Bearer {secret}"
    return client, ctx


def _write_template(definition: dict) -> None:
    path = template_store.user_dir() / f"{definition['name']}{template_store.SUFFIX}"
    path.write_text(json.dumps(definition, ensure_ascii=False), encoding="utf-8")


NURPLASTIK = {
    "schema_version": 2, "name": "nurplastik",
    "fields": [{"id": "n", "label": "Nummer", "type": "counter"},
              {"id": "name", "label": "Name", "type": "input"}],
    "layout": {"lines": ["Nr {n}", "{name}"]},
    "tapes": ["material:kunststoff"],
}

GEHEIM = {
    "schema_version": 2, "name": "geheim",
    "fields": [{"id": "pin", "label": "PIN", "type": "input", "required": True, "secret": True}],
    "layout": {"lines": ["{pin}"]},
}


# ---------------------------------------------------------------- Vorlagenliste


def test_default_templates(made):
    client, _ctx = _family(made)
    r = client.get(VORLAGEN)
    assert r.status_code == 200
    data = r.json()
    # "freitext" haengt sich als eingebaute Sondervorlage hinten an, family.freetext_enabled
    # ist standardmaessig an.
    assert [t["name"] for t in data["templates"]] == [*DEFAULT_NAMES, "freitext"]
    assert data["max_copies"] == 5
    gefriergut = data["templates"][0]
    fields = {f["id"]: f for f in gefriergut["fields"]}
    assert fields["inhalt"]["required"] is True
    assert all("secret" not in f for f in gefriergut["fields"])


def test_only_configured_templates_are_offered(made):
    client, _ctx = _family(made, config={"family": {"templates": ["eigentum", "gibtsnicht"]}})
    data = client.get(VORLAGEN).json()
    assert [t["name"] for t in data["templates"]] == ["eigentum", "freitext"]


# ---------------------------------------------------------------- Freitext


def test_freitext_wird_angeboten_mit_multiline_feld(made):
    client, _ctx = _family(made)
    data = client.get(VORLAGEN).json()
    freitext = next(t for t in data["templates"] if t["name"] == "freitext")
    assert freitext["fields"] == [{
        "id": "text", "label": "Freitext", "type": "input", "default": "", "required": True,
        "choices": [], "choice_labels": {}, "max_len": 200, "multiline": True,
    }]


def test_freitext_vorschau_und_druck(made):
    client, ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "freitext", "values": {"text": "Zeile 1\nZeile 2"}})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = client.post(DRUCKEN, json={"template": "freitext", "values": {"text": "Hallo"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert ctx.history().last().source == "api"


def test_freitext_laengengrenze(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "freitext", "values": {"text": "x" * 201}})
    assert r.status_code == 422


def test_freitext_unbekanntes_feld_422(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "freitext", "values": {"text": "x", "hack": "y"}})
    assert r.status_code == 422


def test_freitext_abschaltbar(made):
    client, _ctx = _family(made, config={"family": {"freetext_enabled": False}})
    data = client.get(VORLAGEN).json()
    assert "freitext" not in [t["name"] for t in data["templates"]]
    r = client.post(VORSCHAU, json={"template": "freitext", "values": {"text": "Hallo"}})
    assert r.status_code == 404


# ---------------------------------------------------------------- Vorschau


def test_preview_ok_with_design_png(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "gefriergut", "values": {"inhalt": "Suppe"}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    png = base64.b64decode(data["design_png"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert data["width"] and data["height"]


def test_preview_not_allowed_template_404(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "datentraeger", "values": {}})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Vorlage nicht freigegeben"


def test_preview_value_validation(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "gefriergut", "values": {"inhalt": "x", "hack": "y"}})
    assert r.status_code == 422
    r = client.post(VORSCHAU, json={"template": "gefriergut", "values": {"inhalt": "x" * 201}})
    assert r.status_code == 422
    r = client.post(VORSCHAU, json={"template": "gefriergut", "values": {"inhalt": 5}})
    assert r.status_code == 422


def test_preview_missing_required_field_is_ok_false(made):
    client, _ctx = _family(made)
    r = client.post(VORSCHAU, json={"template": "gefriergut", "values": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["errors"]
    assert data["design_png"] is None


# ---------------------------------------------------------------- Drucken


def test_print_eigentum_source_api(made):
    client, ctx = _family(made)
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    entries = ctx.history().search()
    assert len(entries) == 1
    assert entries[0].source == "api"


def test_copy_limit_default_five_is_ok(made):
    client, _ctx = _family(made)
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}, "copies": 5})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_copy_limit_six_rejected(made):
    client, ctx = _family(made)
    transport = ctx.service._test_transport
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}, "copies": 6})
    assert r.status_code == 422
    assert not transport.written


def test_copy_limit_ignores_higher_config(made):
    client, _ctx = _family(made, config={"family": {"max_copies": 20}})
    data = client.get(VORLAGEN).json()
    assert data["max_copies"] == 5
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}, "copies": 6})
    assert r.status_code == 422


def test_copy_limit_lower_config(made):
    client, _ctx = _family(made, config={"family": {"max_copies": 3}})
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}, "copies": 4})
    assert r.status_code == 422


def test_tape_suitability_confirmation(made):
    names = [*DEFAULT_NAMES, "nurplastik"]
    client, ctx = _family(made, config={"family": {"templates": names}})
    transport = ctx.service._test_transport
    paper = next(t for t in list_tapes() if t.material == "papier")
    config_mod.save_config({"tape": {"current": paper.id}})
    _write_template(NURPLASTIK)

    r = client.post(DRUCKEN, json={"template": "nurplastik", "values": {"name": "Anna"}})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "bestätigung_nötig"
    assert "Band passt nicht" in data["message"]
    assert data["reasons"]
    assert not transport.written
    assert ctx.history().search() == []

    r = client.post(DRUCKEN, json={"template": "nurplastik", "values": {"name": "Anna"}, "confirmed": True})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_double_press_rejected(made):
    client, _ctx = _family(made)
    body = {"template": "eigentum", "values": {"name": "Anna"}}
    first = client.post(DRUCKEN, json=body).json()
    assert first["status"] == "ok"
    second = client.post(DRUCKEN, json=body).json()
    assert second["status"] == "abgelehnt"
    assert "Gerade eben schon gedruckt" in second["message"]


def test_print_while_printer_busy_waits(made):
    client, ctx = _family(made)
    ctx.service.lease(object(), 60)
    r = client.post(DRUCKEN, json={"template": "eigentum", "values": {"name": "Anna"}})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "wartet"
    assert "wartet" in data["message"]


def test_sensitive_required_field_hidden_and_not_offered(made):
    names = [*DEFAULT_NAMES, "geheim"]
    client, _ctx = _family(made, config={"family": {"templates": names}})
    _write_template(GEHEIM)

    data = client.get(VORLAGEN).json()
    assert "geheim" not in [t["name"] for t in data["templates"]]

    r = client.post(VORSCHAU, json={"template": "geheim", "values": {}})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Vorlage nicht freigegeben"


# ---------------------------------------------------------------- Status


def test_status_keys(made):
    client, _ctx = _family(made)
    r = client.get(STATUS)
    assert r.status_code == 200
    assert set(r.json()) == {"online", "text", "waiting"}


def test_printing_connecting_text_uses_real_ellipsis():
    from tapesmith.webapi.routes_family import PRINTING_CONNECTING

    assert PRINTING_CONNECTING == "Drucker verbindet…"
    assert "..." not in PRINTING_CONNECTING


# ---------------------------------------------------------------- Rollenbeschränkung


def test_family_token_cannot_reach_other_routes(made):
    client, _ctx = _family(made)
    assert client.get("/api/v1/history").status_code == 403
    assert client.get("/api/v1/settings").status_code == 403
    r = client.post("/api/v1/labels/print", json={"source": {"kind": "text", "lines": ["x"]}})
    assert r.status_code == 403
    assert client.post("/api/v1/print", json={"template": "eigentum"}).status_code == 403
