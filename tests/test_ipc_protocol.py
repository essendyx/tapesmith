"""Protokoll v1 des Druckdienstes: Zeilenrahmen, Nachrichtenbau und Pflichtfeld-Prüfung."""

import json
import os

import pytest

import tapesmith
from tapesmith.errors import explain
from tapesmith.ipc import protocol
from tapesmith.ipc.protocol import (
    EVENTS,
    METHODS,
    PROTOCOL_VERSION,
    IpcError,
    ProtocolError,
    check_message,
    decode_line,
    encode_line,
    error_message,
    event,
    hello,
    request,
    response_error,
    response_ok,
    welcome,
)
from tapesmith.transport.base import TransportError


def test_roundtrip_line_keeps_umlauts():
    msg = request(1, "ping")
    line = encode_line(msg)
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert decode_line(line) == msg
    ev = event("warning", {"job_key": "k", "text": "Deckel offen, bitte schließen"})
    line = encode_line(ev)
    assert "schließen".encode("utf-8") in line
    assert decode_line(line) == ev
    assert decode_line(line.rstrip(b"\n")) == ev


def test_compact_separators():
    assert encode_line(response_ok(3, {"a": 1})) == b'{"type":"response","id":3,"ok":true,"result":{"a":1}}\n'


@pytest.mark.parametrize("line", [b"{kaputt", b"[]", b'{"type":"x"}', b"{}", b"\xff\xfe", b'"text"'])
def test_decode_line_rejects_garbage(line):
    with pytest.raises(ProtocolError):
        decode_line(line)


def test_unknown_method_and_event():
    with pytest.raises(ProtocolError):
        request(1, "gibtsnicht")
    with pytest.raises(ProtocolError):
        event("gibtsnicht")


def test_check_message_reports_missing_fields():
    with pytest.raises(ProtocolError, match="id"):
        check_message({"type": "request", "method": "ping", "params": {}})
    with pytest.raises(ProtocolError, match="ok"):
        check_message({"type": "response", "id": 1, "result": {}})
    with pytest.raises(ProtocolError):
        check_message({"type": "request", "id": 0, "method": "ping", "params": {}})
    with pytest.raises(ProtocolError):
        check_message({"type": "request", "id": True, "method": "ping", "params": {}})
    with pytest.raises(ProtocolError):
        check_message({"type": "request", "id": 1, "method": "ping", "params": []})
    with pytest.raises(ProtocolError):
        check_message({"type": "response", "id": 1, "ok": True})
    with pytest.raises(ProtocolError):
        check_message({"type": "response", "id": 1, "ok": False, "result": {}})
    with pytest.raises(ProtocolError):
        check_message({"type": "event", "event": "state"})
    with pytest.raises(ProtocolError):
        check_message({"type": "hello", "protocol": "1", "client": "gui", "home": "x"})
    with pytest.raises(ProtocolError):
        check_message({"type": "error", "code": "home"})
    with pytest.raises(ProtocolError):
        check_message({"type": "welcome", "protocol": 1, "version": "1", "pid": 1})


def test_check_message_accepts_valid_and_ignores_unknown_fields():
    msgs = [
        hello("gui", "abc"),
        welcome("abc"),
        error_message("home", "falsch"),
        request(2, "status", {"quick": True, "fresh": False}),
        response_ok(2),
        response_error(2, {"kind": "ValueError", "message": "x", "exit_code": 1,
                           "rows_sent": None, "rows_total": None}),
        event("queue"),
    ]
    for msg in msgs:
        extended = {**msg, "zukunft": 42}
        assert check_message(extended) is extended
        assert decode_line(encode_line(extended)) == extended


def test_size_limit(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_LINE_BYTES", 100)
    with pytest.raises(ProtocolError, match="zu groß"):
        encode_line(event("warning", {"job_key": "k", "text": "x" * 200}))
    with pytest.raises(ProtocolError):
        decode_line(b'{"type":"event","event":"queue","data":{"x":"' + b"y" * 200 + b'"}}')


def test_hello_defaults():
    msg = hello("gui", "abc")
    assert msg == {"type": "hello", "protocol": 1, "client": "gui", "pid": os.getpid(),
                   "version": tapesmith.__version__, "home": "abc"}
    assert PROTOCOL_VERSION == 1
    with pytest.raises(ProtocolError):
        hello("browser", "abc")
    w = welcome("abc", pid=7, version="9")
    assert w == {"type": "welcome", "protocol": 1, "version": "9", "pid": 7, "home": "abc"}


def test_builders():
    assert request(5, "queue.move", {"id": 3, "position": 0}) == {
        "type": "request", "id": 5, "method": "queue.move", "params": {"id": 3, "position": 0}, "lang": "de"}
    assert request(1, "ping")["params"] == {}
    assert response_ok(1)["result"] == {}
    err = {"kind": "X", "message": "m", "exit_code": 1, "rows_sent": None, "rows_total": None}
    assert response_error(1, err) == {"type": "response", "id": 1, "ok": False, "error": err}
    assert event("state", {"state": "verbunden"}) == {"type": "event", "event": "state",
                                                      "data": {"state": "verbunden"}}
    assert error_message("protocol", "m") == {"type": "error", "code": "protocol", "message": "m"}
    json.dumps(sorted(METHODS))
    assert "queue.resume" in METHODS and len(METHODS) == 19
    assert EVENTS == {"state", "status", "progress", "warning", "cut_pause", "job", "queue"}


def test_errors_map_to_unreachable():
    assert issubclass(ProtocolError, IpcError)
    assert issubclass(IpcError, TransportError)
    assert explain(ProtocolError("x")).exit_code == 5


def test_ipc_imports_no_qt_and_no_pywin32():
    import subprocess
    import sys
    from pathlib import Path

    code = ("import sys, tapesmith.ipc.protocol, tapesmith.ipc.codec, tapesmith.ipc.pipe; "
            "bad = [m for m in sys.modules if m.split('.')[0] in "
            "('PySide6', 'shiboken6', 'win32api', 'win32file', 'win32pipe', 'pywintypes', 'tapesmith.daemon')"
            " or m.startswith(('tapesmith.gui', 'tapesmith.daemon'))]; "
            "print(bad); sys.exit(1 if bad else 0)")
    src = Path(__file__).resolve().parent.parent / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
