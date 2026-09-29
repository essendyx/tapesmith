"""Protokoll v1 zwischen Clients und Druckdienst p12d: JSON-Lines, eine Nachricht je Zeile.

Nachrichtentypen: `hello`/`welcome` (Handshake mit Protokollversion und home_key), `error`
(Handshake abgelehnt), `request`/`response` (mit `id`) und `event` (an alle Clients).
Unbekannte Felder werden ignoriert, fehlende Pflichtfelder ergeben `ProtocolError`.
"""

from __future__ import annotations

import json
import os

import tapesmith
from tapesmith.transport.base import TransportError
from tapesmith import i18n
from tapesmith.i18n import _t

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 64 * 1024 * 1024
CLIENT_KINDS = ("cli", "gui", "tray", "test")
METHODS = frozenset({"ping", "print", "cancel", "continue_cut", "preconnect", "disconnect", "state",
                     "status", "lease", "release", "reload", "queue.list", "queue.cancel",
                     "queue.duplicate", "queue.move", "queue.retry", "queue.pause", "queue.resume",
                     "shutdown"})
EVENTS = frozenset({"state", "status", "progress", "warning", "cut_pause", "job", "queue"})
MESSAGE_TYPES = ("hello", "welcome", "error", "request", "response", "event")


class IpcError(TransportError):
    """Fehler in der Verbindung zum Druckdienst (errors.explain: nicht erreichbar, Exit 5)."""


class ProtocolError(IpcError):
    """Nachricht verletzt Protokoll v1."""


def encode_line(msg: dict) -> bytes:
    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError(_t("Nachricht zu groß ({count} Bytes, höchstens {max_line_bytes})", count=len(data), max_line_bytes=MAX_LINE_BYTES))
    return data


def decode_line(line: bytes) -> dict:
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(_t("Nachricht zu groß ({count} Bytes, höchstens {max_line_bytes})", count=len(line), max_line_bytes=MAX_LINE_BYTES))
    try:
        msg = json.loads(bytes(line).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(_t("Ungültige Nachricht: {exc}", exc=exc)) from exc
    if not isinstance(msg, dict):
        raise ProtocolError(_t("Ungültige Nachricht: kein JSON-Objekt"))
    kind = msg.get("type")
    if kind not in MESSAGE_TYPES:
        raise ProtocolError(_t("Unbekannter Nachrichtentyp {kind!r}", kind=kind))
    return msg


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(msg: dict, name: str, check, what: str) -> None:
    if name not in msg:
        raise ProtocolError(_t("Pflichtfeld '{name}' fehlt in {get}-Nachricht", name=name, get=msg.get('type')))
    if not check(msg[name]):
        raise ProtocolError(_t("Feld '{name}' in {get}-Nachricht muss {what} sein", name=name, get=msg.get('type'), what=what))


def _is_str(value) -> bool:
    return isinstance(value, str)


def _is_dict(value) -> bool:
    return isinstance(value, dict)


def check_message(msg: dict) -> dict:
    """Prüft die Pflichtfelder je Nachrichtentyp und gibt die Nachricht unverändert zurück."""
    if not isinstance(msg, dict):
        raise ProtocolError(_t("Ungültige Nachricht: kein JSON-Objekt"))
    kind = msg.get("type")
    if kind == "hello":
        _require(msg, "protocol", _is_int, _t("eine Zahl"))
        _require(msg, "client", _is_str, _t("ein Text"))
        _require(msg, "home", _is_str, _t("ein Text"))
    elif kind == "welcome":
        _require(msg, "protocol", _is_int, _t("eine Zahl"))
        _require(msg, "version", _is_str, _t("ein Text"))
        _require(msg, "pid", _is_int, _t("eine Zahl"))
        _require(msg, "home", _is_str, _t("ein Text"))
    elif kind == "error":
        _require(msg, "code", _is_str, _t("ein Text"))
        _require(msg, "message", _is_str, _t("ein Text"))
    elif kind == "request":
        _require(msg, "id", lambda v: _is_int(v) and v >= 1, _t("eine Zahl ≥ 1"))
        _require(msg, "method", lambda v: v in METHODS, _t("eine bekannte Methode"))
        _require(msg, "params", _is_dict, _t("ein Objekt"))
    elif kind == "response":
        _require(msg, "id", _is_int, _t("eine Zahl"))
        _require(msg, "ok", lambda v: isinstance(v, bool), _t("true oder false"))
        if msg["ok"]:
            _require(msg, "result", _is_dict, _t("ein Objekt"))
        else:
            _require(msg, "error", _is_dict, _t("ein Objekt"))
    elif kind == "event":
        _require(msg, "event", lambda v: v in EVENTS, _t("ein bekanntes Ereignis"))
        _require(msg, "data", _is_dict, _t("ein Objekt"))
    else:
        raise ProtocolError(_t("Unbekannter Nachrichtentyp {kind!r}", kind=kind))
    return msg


def hello(client: str, home: str, *, pid: int | None = None, version: str | None = None) -> dict:
    if client not in CLIENT_KINDS:
        raise ProtocolError(_t("Unbekannte Client-Art '{client}' (erlaubt: {items})", client=client, items=', '.join(CLIENT_KINDS)))
    return {"type": "hello", "protocol": PROTOCOL_VERSION, "client": client,
            "pid": os.getpid() if pid is None else pid,
            "version": tapesmith.__version__ if version is None else version, "home": home}


def welcome(home: str, *, pid: int | None = None, version: str | None = None) -> dict:
    return {"type": "welcome", "protocol": PROTOCOL_VERSION,
            "version": tapesmith.__version__ if version is None else version,
            "pid": os.getpid() if pid is None else pid, "home": home}


def error_message(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}


def request(msg_id: int, method: str, params: dict | None = None) -> dict:
    if method not in METHODS:
        raise ProtocolError(_t("Unbekannte Methode '{method}'", method=method))
    if not _is_int(msg_id) or msg_id < 1:
        raise ProtocolError(_t("Ungültige Anfrage-ID {msg_id!r}", msg_id=msg_id))
    # `lang`: Sprache des Clients für Meldungen des Dienstes (ältere Dienste ignorieren das Feld).
    return {"type": "request", "id": msg_id, "method": method, "params": dict(params or {}),
            "lang": i18n.language()}


def response_ok(msg_id: int, result: dict | None = None) -> dict:
    return {"type": "response", "id": msg_id, "ok": True, "result": dict(result or {})}


def response_error(msg_id: int, error: dict) -> dict:
    return {"type": "response", "id": msg_id, "ok": False, "error": error}


def event(name: str, data: dict | None = None) -> dict:
    if name not in EVENTS:
        raise ProtocolError(_t("Unbekanntes Ereignis '{name}'", name=name))
    return {"type": "event", "event": name, "data": dict(data or {})}
