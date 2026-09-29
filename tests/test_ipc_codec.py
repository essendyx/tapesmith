"""Übersetzung der Druck-Datentypen in JSON und zurück (verlustfrei für Kopfbilder und Metadaten)."""

import json
from datetime import datetime

import pytest
from PIL import Image

from tapesmith.connection import PrinterOffline
from tapesmith.device.profile import load_profile
from tapesmith.ipc.codec import (
    RemoteError,
    StateInfo,
    StatusReport,
    b64_to_png,
    decode_error,
    decode_outcome,
    decode_report,
    decode_request,
    decode_state,
    decode_status,
    encode_error,
    encode_outcome,
    encode_report,
    encode_request,
    encode_state,
    encode_status,
    png_to_b64,
)
from tapesmith.ipc.protocol import ProtocolError
from tapesmith.jobs import IncompletePrint, JobMeta
from tapesmith.lock import PrinterBusy
from tapesmith.pipeline import PrintLabel, PrintOutcome, PrintPipeline, PrintRequest
from tapesmith.printer import PrintResult
from tapesmith.status import status_from_bytes
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError

P = load_profile()


def pattern(width=96, height=40, seed=1):
    img = Image.new("1", (width, height), 255)
    for y in range(height):
        for x in range(width):
            if (x * seed + y * 3) % 7 == 0:
                img.putpixel((x, y), 0)
    return img


def make_request():
    labels = (PrintLabel(pattern(seed=1), pattern(40, 96, seed=2)), PrintLabel(pattern(seed=5)))
    meta = JobMeta(source="gui", kind="template", template="datentraeger", values={"sn": "274913"},
                   spec={"lines": ["a"]})
    return PrintRequest(labels=labels, meta=meta, copies=2, chain=True, cut_pause_s=0.0)


def test_png_roundtrip_keeps_mode():
    img = pattern()
    back = b64_to_png(png_to_b64(img))
    assert back.mode == "1"
    assert back.size == img.size
    assert back.tobytes() == img.tobytes()
    gray = Image.new("L", (3, 2), 17)
    assert b64_to_png(png_to_b64(gray)).mode == "L"


def test_b64_to_png_rejects_garbage():
    with pytest.raises(ProtocolError):
        b64_to_png("kein png")


def test_request_roundtrip():
    req = make_request()
    data = encode_request(req)
    back = decode_request(json.loads(json.dumps(data)))
    assert len(back.labels) == 2
    for a, b in zip(req.labels, back.labels):
        assert a.head.tobytes() == b.head.tobytes()
        assert b.head.mode == "1"
    assert back.labels[0].landscape.tobytes() == req.labels[0].landscape.tobytes()
    assert back.labels[1].landscape is None
    assert data["labels"][1]["landscape_png"] is None
    assert back.meta == req.meta
    assert (back.copies, back.chain, back.cut_marks, back.confirmed, back.cut_pause_s) == (
        2, True, True, False, 0.0)


def test_decode_request_errors():
    data = encode_request(make_request())
    with pytest.raises(ProtocolError):
        decode_request({**data, "meta": {**data["meta"], "source": "unbekannt"}})
    with pytest.raises(ProtocolError):
        decode_request({k: v for k, v in data.items() if k != "labels"})
    with pytest.raises(ProtocolError):
        decode_request({**data, "meta": {**data["meta"], "zukunft": 1}})


def plan_for(req):
    return PrintPipeline(P, lambda fn: None, preflight=False).plan(req)


def test_outcome_roundtrip_with_status():
    status = status_from_bytes(bytes.fromhex("1a044b1a0599"), P)
    req = PrintRequest(labels=(PrintLabel(pattern(width=P.head_dots, height=120)),), meta=JobMeta())
    plan = plan_for(req)
    outcome = PrintOutcome(status="unvollständig", plan=plan,
                           results=[PrintResult(rows=120, responses=[(b"a", b"b")], waited_s=1.5,
                                                status="ok", rows_sent=60)],
                           warnings=["Deckel offen gemeldet, bitte schließen"],
                           printer_status=status, history_id=12,
                           error=IncompletePrint("abgebrochen", 60, 120),
                           reasons=("r1",), consumed_mm=15.25)
    data = encode_outcome(outcome)
    json.dumps(data)
    assert data["queue_id"] is None
    assert data["printer_status"] == status.to_dict()
    back = decode_outcome(json.loads(json.dumps(data)), plan)
    assert back.plan is plan
    assert back.status == "unvollständig"
    assert back.warnings == outcome.warnings
    assert back.reasons == ("r1",)
    assert back.history_id == 12
    assert back.consumed_mm == 15.25
    assert len(back.results) == 1
    r = back.results[0]
    assert (r.rows, r.rows_sent, r.waited_s, r.status, r.responses) == (120, 60, 1.5, "ok", [])
    battery = back.printer_status.get("battery")
    assert battery.value == 75 and battery.verified
    assert back.printer_status.get("lid").value == "offen"
    assert back.printer_status.to_dict() == status.to_dict()
    assert back.printer_status.raw == status.raw
    assert isinstance(back.error, IncompletePrint)
    assert (back.error.rows_sent, back.error.rows_total) == (60, 120)
    assert getattr(back, "queue_id", "fehlt") is None


def test_outcome_queue_id_passthrough():
    req = PrintRequest(labels=(PrintLabel(pattern(width=P.head_dots, height=80)),), meta=JobMeta())
    plan = plan_for(req)
    outcome = PrintOutcome(status="ok", plan=plan)
    outcome.queue_id = 4
    data = encode_outcome(outcome)
    assert data["queue_id"] == 4
    assert data["printer_status"] is None and data["error"] is None
    back = decode_outcome(data, plan)
    assert back.queue_id == 4
    assert back.printer_status is None and back.error is None


@pytest.mark.parametrize("exc, cls, exit_code", [
    (IncompletePrint("x", 10, 40), IncompletePrint, 5),
    (PrinterOffline("offline"), PrinterOffline, 5),
    (ConnectTimeout("zeit"), ConnectTimeout, 5),
    (PrinterBusy("belegt"), PrinterBusy, 7),
    (TemplateError("vorlage"), TemplateError, 6),
    (TransportError("weg"), TransportError, 5),
    (ValueError("x"), ValueError, 1),
    (ProtocolError("p"), ProtocolError, 5),
])
def test_error_roundtrip(exc, cls, exit_code):
    data = encode_error(exc)
    json.dumps(data)
    assert data["kind"] == cls.__name__
    assert data["exit_code"] == exit_code
    assert data["message"] == str(exc)
    back = decode_error(data)
    assert type(back) is cls
    assert str(back) == str(exc)


def test_incomplete_rows():
    data = encode_error(IncompletePrint("x", 10, 40))
    assert data["rows_sent"] == 10 and data["rows_total"] == 40
    back = decode_error(data)
    assert (back.rows_sent, back.rows_total) == (10, 40)
    assert encode_error(ValueError("y"))["rows_sent"] is None


def test_unknown_error_kind():
    data = encode_error(KeyError("x"))
    assert data["kind"] == "KeyError"
    assert data["exit_code"] == 1
    back = decode_error(data)
    assert isinstance(back, RemoteError)
    assert back.kind == "KeyError" and back.exit_code == 1
    assert "x" in str(back)


def test_state_and_report_roundtrip():
    info = StateInfo(state="verbunden", transport="COM4", last_error=None, leased=True)
    assert decode_state(json.loads(json.dumps(encode_state(info)))) == info
    assert encode_state(StateInfo("getrennt")) == {"state": "getrennt", "transport": None,
                                                   "last_error": None, "leased": False}
    status = status_from_bytes(bytes.fromhex("1a044b1a0599"), P)
    when = datetime(2026, 9, 27, 14, 3, 5)
    report = StatusReport(state=info, status=status, checked_at=when)
    data = encode_report(report)
    assert data["checked_at"] == "2026-09-27T14:03:05"
    back = decode_report(json.loads(json.dumps(data)))
    assert back.state == info
    assert back.checked_at == when
    assert back.status.to_dict() == status.to_dict()
    empty = StatusReport(state=StateInfo("offline", last_error="weg"), status=None, checked_at=None)
    assert decode_report(encode_report(empty)) == empty


def test_status_none():
    assert encode_status(None) is None
    assert decode_status(None) is None
