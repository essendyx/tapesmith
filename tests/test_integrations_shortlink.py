"""Client des Kurz-Link-Dienstes. Nur MockTransport."""

import copy
import json

import pytest

from homelab_fakes import mock_transport, token_file
from tapesmith.integrations import settings, shortlink
from tapesmith.integrations.errors import AuthFailed, NotConfigured, TokenMissing, UpstreamError
from tapesmith.integrations.shortlink import ShortLink, ShortlinkClient

ADMIN = "https://l.example.com"


def _link(link_id="HL-0042", target="https://x.example/a", hits=0):
    return {"id": link_id, "target": target, "note": "", "created": "2026-09-28T10:00:00",
            "updated": "2026-09-28T10:00:00", "hits": hits}


def _client(routes, calls=None):
    return ShortlinkClient(ADMIN, "tok-1", transport=mock_transport(routes, calls=calls))


def test_normalize_id():
    assert shortlink.normalize_id(" hl-0042 ") == "HL-0042"
    with pytest.raises(ValueError, match="Ungültige Kurz-ID"):
        shortlink.normalize_id("ä1")
    with pytest.raises(ValueError):
        shortlink.normalize_id("A" * 17)
    with pytest.raises(ValueError):
        shortlink.normalize_id("-A")
    assert shortlink.normalize_id("A" * 16) == "A" * 16


def test_short_url():
    assert shortlink.short_url("https://l.example.com/", "hl-0042") == "HTTPS://L.EXAMPLE.COM/HL-0042"


def test_create_sends_post_with_bearer_and_body():
    calls = []
    client = _client({"POST /api/links": (201, _link())}, calls)
    link = client.create("https://x.example/a", link_id="hl-0042", note="Asset")
    assert link == ShortLink("HL-0042", "https://x.example/a", "", "2026-09-28T10:00:00",
                             "2026-09-28T10:00:00", 0)
    request = calls[0]
    assert request.headers["Authorization"] == "Bearer tok-1"
    assert json.loads(request.content) == {"target": "https://x.example/a", "id": "HL-0042", "note": "Asset"}


def test_create_without_id_and_null_target():
    calls = []
    client = _client({"POST /api/links": (201, _link("X1", None))}, calls)
    assert client.create(None).target is None
    assert json.loads(calls[0].content) == {"target": None}


def test_create_conflict_is_upstream():
    client = _client({"POST /api/links": (409, {"error": "exists"})})
    with pytest.raises(UpstreamError, match="409"):
        client.create("https://x.example", link_id="A1")


def test_upsert_sends_put():
    calls = []
    client = _client({"PUT /api/links/HL-0042": (201, _link())}, calls)
    assert client.upsert("hl-0042", "https://x.example/a", "n").id == "HL-0042"
    assert calls[0].method == "PUT"
    assert json.loads(calls[0].content) == {"target": "https://x.example/a", "note": "n"}


def test_invalid_target_is_rejected_before_sending():
    calls = []
    client = _client({}, calls)
    for target in ("ftp://x", "https://a b", "x"):
        with pytest.raises(ValueError):
            client.upsert("A1", target)
    assert calls == []


def test_get_list_delete():
    client = _client({
        "GET /api/links/HL-0042": _link(hits=3),
        "GET /api/links/NONE": (404, {"error": "nicht gefunden"}),
        "GET /api/links": {"links": [_link(), _link("B")]},
        "DELETE /api/links/HL-0042": (204, None),
        "DELETE /api/links/NONE": (404, {"error": "nicht gefunden"}),
    })
    assert client.get("hl-0042").hits == 3
    assert client.get("none") is None
    assert [link.id for link in client.list()] == ["HL-0042", "B"]
    assert client.delete("HL-0042") is True
    assert client.delete("NONE") is False


def test_401_is_auth_failed():
    client = _client({"GET /api/links": (401, {"error": "token"})})
    with pytest.raises(AuthFailed) as info:
        client.list()
    assert info.value.service == "Kurz-Link-Dienst"


def _data(**shortlink_values):
    data = copy.deepcopy(settings.DEFAULTS)
    data["shortlink"].update(shortlink_values)
    return data


def test_configured():
    assert shortlink.configured(_data()) is False
    assert shortlink.configured(_data(base_url="https://l.example.com")) is True


def test_link_for_without_service_returns_target():
    assert shortlink.link_for(_data(), "HL-0042", "https://x.example/a") == "https://x.example/a"
    with pytest.raises(NotConfigured):
        shortlink.link_for(_data(), "HL-0042", None)


def test_link_for_with_service_upserts():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def upsert(self, link_id, target, note=""):
            self.calls.append((link_id, target, note))
            return ShortLink(link_id, target, note, "", "", 0)

    fake = FakeClient()
    url = shortlink.link_for(_data(base_url="https://l.example.com"), "hl-0042", "https://x.example/a",
                             note="n", client=fake)
    assert url == "HTTPS://L.EXAMPLE.COM/HL-0042"
    assert fake.calls == [("hl-0042", "https://x.example/a", "n")]


def test_link_for_with_transport(tmp_path):
    calls = []
    data = _data(base_url="https://l.example.com", token_ref=token_file(tmp_path, "sl", "tok-2"))
    url = shortlink.link_for(data, "A1", None,
                             transport=mock_transport({"GET /api/links/A1": (404, {"error": "x"}),
                                                       "PUT /api/links/A1": (201, _link("A1", None))}, calls=calls))
    assert url == "HTTPS://L.EXAMPLE.COM/A1"
    assert [c.method for c in calls] == ["GET", "PUT"]
    assert calls[0].headers["Authorization"] == "Bearer tok-2"


def test_from_settings_uses_admin_url(tmp_path):
    calls = []
    data = _data(base_url="https://l.example.com", admin_url="http://192.0.2.12:8095",
                 token_ref=token_file(tmp_path, "sl"))
    client = ShortlinkClient.from_settings(data, transport=mock_transport(
        {"GET /api/links": {"links": []}}, calls=calls))
    assert client.list() == []
    assert str(calls[0].url).startswith("http://192.0.2.12:8095/api/links")


def test_from_settings_without_token_file(tmp_path):
    data = _data(base_url="https://l.example.com", token_ref=f"file:{tmp_path / 'fehlt'}")
    with pytest.raises(TokenMissing):
        ShortlinkClient.from_settings(data)


def test_from_settings_not_configured():
    with pytest.raises(NotConfigured):
        ShortlinkClient.from_settings(_data())


# ---------- Vorschau ohne Netz, vorhandenes Ziel nie mit None überschreiben ----------

def _sl_data(tmp_path, **extra):
    return _data(base_url="https://l.example.com", token_ref=token_file(tmp_path, "sl"), **extra)


def test_link_for_without_sync_makes_no_request_and_needs_no_token(tmp_path):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    data = _data(base_url="https://l.example.com", token_ref=f"file:{tmp_path / 'fehlt'}")
    url = shortlink.link_for(data, "hl-0001", None, sync=False, transport=service.transport)
    assert url == "HTTPS://L.EXAMPLE.COM/HL-0001"
    assert service.calls == []


def test_link_for_none_target_keeps_existing_target(tmp_path):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    service.links["HL-0001"] = {"id": "HL-0001", "target": "https://ziel.example", "note": "",
                                "created": "", "updated": "", "hits": 0}
    shortlink.link_for(_sl_data(tmp_path), "HL-0001", None, transport=service.transport)
    assert service.links["HL-0001"]["target"] == "https://ziel.example"
    assert service.writes() == []


def test_link_for_none_target_creates_missing_link(tmp_path):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    shortlink.link_for(_sl_data(tmp_path), "HL-0002", None, note="NAS", transport=service.transport)
    assert service.links["HL-0002"]["target"] is None
    assert service.links["HL-0002"]["note"] == "NAS"


def test_link_for_with_target_sets_it(tmp_path):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    service.links["HL-0003"] = {"id": "HL-0003", "target": "https://alt.example", "note": "",
                                "created": "", "updated": "", "hits": 0}
    shortlink.link_for(_sl_data(tmp_path), "HL-0003", "https://neu.example", transport=service.transport)
    assert service.links["HL-0003"]["target"] == "https://neu.example"
