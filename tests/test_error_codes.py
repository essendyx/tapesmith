"""Stabile Fehlercodes (`errors.ERROR_CODES`, `error_code`, Feld `code` in jeder API-Fehlerantwort)."""

from __future__ import annotations

import pytest

from tapesmith import i18n
from tapesmith.document.model import DocumentError
from tapesmith.errors import ERROR_CODES, Advice, error_code, explain
from tapesmith.fileutil import FileLockTimeout
from tapesmith.integrations.errors import (AuthFailed, IntegrationError, NotConfigured, NotReachable,
                                          TokenMissing, UpstreamError)
from tapesmith.ipc.protocol import IpcError, ProtocolError
from tapesmith.jobs import IncompletePrint
from tapesmith.lock import PrinterBusy
from tapesmith.render.fonts import FontMissing
from tapesmith.secretref import SecretMissing
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.webapi.errors import NotFound, error_body, error_json, http_error_body, validation_body
from tapesmith.webapi.homelab_common import integration_error_response
from tapesmith.webapi.labels import LabelNotPrintable
from webapi_fakes import close_ctx, make_client, make_token

ERROR_KEYS = ["kind", "code", "message", "hint", "exit_code", "details"]

CONTRACT_CODES = (
    "printer.busy", "file.locked", "print.incomplete", "printer.unreachable", "port.busy", "port.missing",
    "bluetooth.lost", "printer.not_paired", "transport.error", "ipc.error", "template.invalid",
    "document.invalid", "protocol.error", "font.missing", "secret.missing", "label.not_printable",
    "value.invalid", "request.invalid", "not_found", "auth.required", "auth.forbidden", "method.not_allowed",
    "conflict", "too_large", "rate_limited", "http.error", "integration.token_missing",
    "integration.not_configured", "integration.unreachable", "integration.auth_failed", "integration.upstream",
    "update.not_installed", "update.no_trusted_key", "update.source_invalid",
    "update.source_unreachable", "update.signature_invalid", "update.checksum_mismatch",
    "update.download_failed", "update.busy", "update.apply_failed", "decoder.unavailable", "module.disabled",
    "aborted", "internal",
)


class _Resolved:
    errors = ["Pflichtfeld fehlt"]
    missing_secrets: list = []


def test_error_codes_liste():
    assert len(ERROR_CODES) == 44
    assert len(set(ERROR_CODES)) == 44
    assert ERROR_CODES == CONTRACT_CODES


@pytest.mark.parametrize("code", CONTRACT_CODES)
def test_jeder_code_hat_titel_und_hinweis_in_beiden_katalogen(code):
    for lang in ("de", "en"):
        node = i18n.catalog(lang)["errors"]
        for part in code.split("."):
            node = node[part]
        assert isinstance(node["title"], str) and node["title"].strip()
        assert isinstance(node["hint"], str) and node["hint"].strip()


def test_katalog_hat_keine_fremden_codes():
    def leaves(node, prefix=""):
        if "title" in node and "hint" in node:
            yield prefix
            return
        for key, value in node.items():
            yield from leaves(value, f"{prefix}.{key}" if prefix else key)

    for lang in ("de", "en"):
        assert sorted(leaves(i18n.catalog(lang)["errors"])) == sorted(CONTRACT_CODES)


def test_deutsche_titel_wie_explain():
    assert i18n.tr("errors.printer.busy.title", "de") == explain(PrinterBusy("x")).title
    assert i18n.tr("errors.print.incomplete.title", "de") == explain(IncompletePrint("x", 1, 2)).title
    assert i18n.tr("errors.port.missing.title", "de") == "COM-Port fehlt"


TRANSPORT_BUSY = TransportError("COM4: could not open port 'COM4': PermissionError(13, 'Zugriff verweigert', None, 5)")
TRANSPORT_MISSING = TransportError(
    "COM7: could not open port 'COM7': "
    "FileNotFoundError(2, 'Das System kann die angegebene Datei nicht finden.', None, 2)")
TRANSPORT_BT = TransportError(
    "COM4: Schreiben fehlgeschlagen: WriteFile failed "
    "(OSError(22, 'Das Zeitlimit für die Semaphore wurde erreicht.', None, 121))")
TRANSPORT_PAIR = TransportError("Kein ausgehender Bluetooth-COM-Port für 001122334455, Drucker gekoppelt?")


@pytest.mark.parametrize("exc, code", [
    (PrinterBusy("x"), "printer.busy"),
    (FileLockTimeout("x"), "file.locked"),
    (IncompletePrint("x", 1, 2), "print.incomplete"),
    (ConnectTimeout("x"), "printer.unreachable"),
    (TRANSPORT_BUSY, "port.busy"),
    (TRANSPORT_MISSING, "port.missing"),
    (TRANSPORT_BT, "bluetooth.lost"),
    (TRANSPORT_PAIR, "printer.not_paired"),
    (TransportError("sonst etwas"), "transport.error"),
    (IpcError("Druckdienst antwortet nicht"), "ipc.error"),
    (TemplateError("x"), "template.invalid"),
    (DocumentError("x"), "document.invalid"),
    (ProtocolError("x"), "protocol.error"),
    (FontMissing("x"), "font.missing"),
    (SecretMissing("x"), "secret.missing"),
    (LabelNotPrintable(_Resolved()), "label.not_printable"),
    (ValueError("x"), "value.invalid"),
    (KeyError("x"), "value.invalid"),
    (NotFound("x"), "not_found"),
    (TokenMissing("Proxmox", "keyring:tapesmith/proxmox"), "integration.token_missing"),
    (NotConfigured("Paperless", "fehlt"), "integration.not_configured"),
    (NotReachable("Paperless", "weg"), "integration.unreachable"),
    (AuthFailed("Paperless", "401"), "integration.auth_failed"),
    (UpstreamError("Paperless", "500"), "integration.upstream"),
    (IntegrationError("Paperless", "x"), "integration.upstream"),
    (KeyboardInterrupt(), "aborted"),
    (EOFError(), "aborted"),
    (RuntimeError("x"), "internal"),
])
def test_ausnahme_zu_code(exc, code):
    assert error_code(exc) == code
    assert code in ERROR_CODES


def test_eigenes_code_attribut_gewinnt():
    class UpdateError(RuntimeError):
        code = "update.busy"

    class Instanz(ValueError):
        def __init__(self, code):
            super().__init__("x")
            self.code = code

    assert error_code(UpdateError("x")) == "update.busy"
    assert error_code(Instanz("update.source_invalid")) == "update.source_invalid"
    assert error_code(Instanz(42)) == "value.invalid"          # kein Text: Tabelle


def test_request_validation_error_code():
    from fastapi.exceptions import RequestValidationError

    assert error_code(RequestValidationError([])) == "request.invalid"


def test_explain_setzt_den_code():
    assert explain(PrinterBusy("x")).code == "printer.busy"
    assert explain(TRANSPORT_BUSY).code == "port.busy"
    assert explain(TRANSPORT_PAIR).code == "printer.not_paired"
    assert explain(IpcError("x")).code == "ipc.error"
    assert explain(ValueError("x")).code == "value.invalid"
    assert explain(KeyboardInterrupt()).code == "aborted"
    assert explain(RuntimeError("x")).code == "internal"
    assert all(explain(e).code in ERROR_CODES for e in (FontMissing("x"), TemplateError("x"),
                                                         ConnectTimeout("x"), IncompletePrint("x", 1, 2)))
    assert Advice("a", "b", 1, "internal").code == "internal"


def test_error_json_schluesselreihenfolge():
    body = error_json("X", "m", code="conflict")
    assert list(body["error"]) == ERROR_KEYS
    assert body["error"]["code"] == "conflict"


@pytest.mark.parametrize("kind, code", [
    ("Label", "label.not_printable"), ("SSH", "integration.upstream"), ("Validierung", "value.invalid"),
    ("Conflict", "conflict"), ("Dienst läuft", "conflict"), ("TemplateError", "template.invalid"),
    ("Unauthorized", "auth.required"), ("Unbekannt", "internal"),
])
def test_error_json_code_aus_kind(kind, code):
    assert error_json(kind, "m")["error"]["code"] == code


@pytest.mark.parametrize("status, code", [
    (401, "auth.required"), (403, "auth.forbidden"), (404, "not_found"), (405, "method.not_allowed"),
    (409, "conflict"), (413, "too_large"), (422, "request.invalid"), (429, "rate_limited"),
    (400, "http.error"), (418, "http.error"),
])
def test_http_error_body_code(status, code):
    body = http_error_body(status, "m")
    assert body["error"]["code"] == code
    assert list(body["error"]) == ERROR_KEYS


def test_validation_body_code():
    body = validation_body([{"loc": ("body", "x"), "type": "missing"}])
    assert body["error"]["code"] == "request.invalid"


@pytest.mark.parametrize("exc, status, code", [
    (PrinterBusy("x"), 409, "printer.busy"),
    (NotFound("x"), 404, "not_found"),
    (SecretMissing("x"), 422, "secret.missing"),
    (ProtocolError("x"), 422, "protocol.error"),
    (IpcError("x"), 503, "ipc.error"),
    (RuntimeError("x"), 500, "internal"),
])
def test_error_body_code(exc, status, code):
    got_status, body = error_body(exc)
    assert got_status == status
    assert body["error"]["code"] == code
    assert list(body["error"]) == ERROR_KEYS


def test_error_body_nutzt_http_status_eigener_ausnahmen():
    class UpdateError(RuntimeError):
        code = "update.busy"

    class Bereits(RuntimeError):
        code = "update.source_invalid"
        http_status = 418

    assert error_body(UpdateError("x"))[0] == 409
    assert error_body(Bereits("x"))[0] == 418
    assert error_body(NotReachable("Paperless", "weg"))[0] == 503


def test_integration_error_response_code():
    response = integration_error_response(TokenMissing("Proxmox", "keyring:tapesmith/proxmox"))
    assert response.status_code == 424
    import json

    assert json.loads(response.body)["error"]["code"] == "integration.token_missing"


# ---------- über die API ----------

@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _err(response) -> dict:
    err = response.json()["error"]
    assert list(err) == ERROR_KEYS
    return err


def test_api_404(api):
    client, _ctx = api
    assert _err(client.get("/api/v1/gibtesnicht"))["code"] == "not_found"
    assert _err(client.post("/api/v1/gibtesnicht", json={}))["code"] == "not_found"


def test_api_401_ohne_token(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        r = client.get("/api/v1/app")
        assert r.status_code == 401
        assert _err(r)["code"] == "auth.required"
    finally:
        close_ctx(ctx)


def test_api_403_rolle(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        secret = make_token(ctx, "familie")
        r = client.get("/api/v1/settings", headers={"Authorization": f"Bearer {secret}"})
        assert r.status_code == 403
        assert _err(r)["code"] == "auth.forbidden"
    finally:
        close_ctx(ctx)


def test_api_405(api):
    client, _ctx = api
    r = client.delete("/api/v1/app")
    assert r.status_code in (404, 405)
    assert _err(r)["code"] in ("not_found", "method.not_allowed")


def test_api_validierung(api):
    client, _ctx = api
    r = client.post("/api/v1/print/cancel", json={})
    assert r.status_code == 422
    assert _err(r)["code"] == "request.invalid"


def test_api_printer_busy(api, monkeypatch):
    client, ctx = api

    def busy(**kw):
        raise PrinterBusy("belegt")

    monkeypatch.setattr(ctx.service, "status", busy)
    r = client.post("/api/v1/status/refresh", json={})
    assert r.status_code == 409
    err = _err(r)
    assert err["code"] == "printer.busy" and err["kind"] == "PrinterBusy"


def test_api_homelab_token_missing(api, monkeypatch):
    client, ctx = api

    def missing(**kw):
        raise TokenMissing("Proxmox pmx10", "keyring:tapesmith/proxmox")

    monkeypatch.setattr(ctx.service, "status", missing)
    r = client.get("/api/v1/status")
    assert r.status_code == 424
    assert _err(r)["code"] == "integration.token_missing"


def test_api_unerwartet_500(api, monkeypatch):
    client, ctx = api

    def crash(**kw):
        raise RuntimeError("geheim innen")

    monkeypatch.setattr(ctx.service, "status", crash)
    r = client.get("/api/v1/status")
    assert r.status_code == 500
    assert _err(r)["code"] == "internal"
    assert "Traceback" not in r.text
