"""HTTP-Client mit Fehlerabbildung. Nur MockTransport, nie Netz."""

import httpx
import pytest

from homelab_fakes import connect_error_transport, mock_transport
from tapesmith.integrations.errors import AuthFailed, NotReachable, UpstreamError
from tapesmith.integrations.httpclient import make_client, request_json, request_raw

BASE = "http://paperless.test:8010"
SERVICE = "Paperless"


def _client(routes, calls=None, **kw):
    return make_client(BASE, service=SERVICE, headers={"Authorization": "Token geheim"},
                       transport=mock_transport(routes, calls=calls), **kw)


def test_200_json_and_headers():
    calls = []
    with _client({"GET /api/x/": {"a": 1}}, calls) as client:
        assert request_json(client, "GET", "/api/x/", service=SERVICE) == {"a": 1}
    request = calls[0]
    assert request.headers["Authorization"] == "Token geheim"
    assert request.headers["User-Agent"].startswith("tapesmith")


def test_client_settings():
    with make_client(BASE, service=SERVICE, timeout_s=3.5, verify=False) as client:
        assert client.timeout.read == 3.5
        assert client.follow_redirects is False
        assert str(client.base_url).startswith(BASE)


def test_query_key_is_matched_exactly():
    with _client({"GET /api/x/?page=2": [2], "GET /api/x/": [1]}) as client:
        assert request_json(client, "GET", "/api/x/", service=SERVICE, params={"page": 2}) == [2]
        assert request_json(client, "GET", "/api/x/", service=SERVICE) == [1]


def test_204_is_none():
    with _client({"DELETE /api/x/1": (204, None)}) as client:
        assert request_json(client, "DELETE", "/api/x/1", service=SERVICE, ok=(204,)) is None


def test_401_is_auth_failed():
    with _client({"GET /api/x/": (401, {"detail": "nein"})}) as client:
        with pytest.raises(AuthFailed) as info:
            request_json(client, "GET", "/api/x/", service=SERVICE)
    exc = info.value
    assert exc.exit_code == 1
    assert str(exc) == "Paperless: Zugriff abgelehnt (HTTP 401)"
    assert exc.hint == "Token und Rechte prüfen"
    assert "geheim" not in str(exc) and "geheim" not in exc.hint


def test_404_is_upstream_with_path():
    with _client({"GET /api/x/": (404, {"detail": "weg"})}) as client:
        with pytest.raises(UpstreamError, match="Nicht gefunden: /api/x/"):
            request_json(client, "GET", "/api/x/", service=SERVICE)


def test_500_with_text_is_upstream():
    with _client({"GET /api/x/": (500, "Interner Fehler " + "x" * 400)}) as client:
        with pytest.raises(UpstreamError) as info:
            request_json(client, "GET", "/api/x/", service=SERVICE)
    message = str(info.value)
    assert "HTTP 500" in message and "Interner Fehler" in message
    assert len(message) < 260
    assert "geheim" not in message


def test_text_instead_of_json_is_upstream():
    with _client({"GET /api/x/": (200, "<html>")}) as client:
        with pytest.raises(UpstreamError, match="kein JSON"):
            request_json(client, "GET", "/api/x/", service=SERVICE)


def test_connect_error_is_not_reachable():
    with make_client(BASE, service=SERVICE, headers={"Authorization": "Token geheim"},
                     transport=connect_error_transport()) as client:
        with pytest.raises(NotReachable) as info:
            request_json(client, "GET", "/api/x/", service=SERVICE)
    exc = info.value
    assert exc.exit_code == 5
    assert BASE in str(exc)
    assert exc.hint == "Adresse und Netz prüfen"
    assert "geheim" not in str(exc)


def test_timeout_is_not_reachable():
    def boom(request):
        raise httpx.ReadTimeout("zu langsam", request=request)

    with make_client(BASE, service=SERVICE, transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(NotReachable):
            request_raw(client, "GET", "/api/x/", service=SERVICE)


def test_request_raw_returns_response_and_maps_errors():
    with _client({"GET /f.png": (200, b"\x89PNG"), "GET /no": (403, "nein")}) as client:
        response = request_raw(client, "GET", "/f.png", service=SERVICE)
        assert response.content == b"\x89PNG"
        with pytest.raises(AuthFailed, match="HTTP 403"):
            request_raw(client, "GET", "/no", service=SERVICE)


def test_unknown_route_of_mock_is_visible():
    with _client({}) as client:
        with pytest.raises(UpstreamError, match="HTTP 599: unerwartete Anfrage GET"):
            request_json(client, "GET", "/api/y/", service=SERVICE)
