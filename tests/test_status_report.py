import dataclasses

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.printer import PrinterSession
from tapesmith.status import preflight, read_status, status_from_bytes
from tapesmith.transport.base import FileTransport, MemoryTransport

P = load_profile()


class DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_status_from_bytes_last_message_per_kind_wins():
    buf = bytes.fromhex("1a0599") + bytes.fromhex("1a0598")  # zu, dann spontan offen->zu (invertiert)
    st = status_from_bytes(buf, P)
    assert st.get("lid").value == "zu"


def test_read_status_decodes_all_kinds_and_ignores_missing_queries():
    responses = {
        bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
        bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
        bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
        bytes.fromhex("1f1107"): bytes.fromhex("1a07010000"),
        bytes.fromhex("1f1109"): b"\x1a\x08" + b"A1B2C3D4E5F6G7H",
        bytes.fromhex("1f1119"): bytes.fromhex("1a0c0b"),
        # 1f110e und 1f1120 bewusst ohne Antwort
    }
    session = PrinterSession(MemoryTransport(responses), P, lock=DummyLock(), sleep=lambda s: None)
    st = read_status(session, P)
    assert st.get("battery").value == 75
    assert st.get("lid").value == "zu"
    assert st.get("paper").value == "ok"
    assert st.get("media").value == "endlos"
    assert st.get("firmware").value == "1.0.0"
    assert st.get("serial").value == "A1B2C3D4E5F6G7H"


def test_read_status_with_file_transport_sends_nothing(tmp_path):
    transport = FileTransport(tmp_path / "dryrun.bin")
    session = PrinterSession(transport, P, lock=DummyLock(), sleep=lambda s: None)
    with session:
        st = read_status(session, P)
    assert st.answered is False
    assert (tmp_path / "dryrun.bin").read_bytes() == b""


def test_summary_never_promises_band_ok_and_reports_missing_battery():
    st = status_from_bytes(bytes.fromhex("1a0689") + bytes.fromhex("1a0598"), P)
    text = st.summary()
    assert "Band: eingelegt gemeldet (leere Rolle nicht erkennbar)" in text
    assert "Band ok" not in text
    assert "Akku: nicht verfügbar" in text


def test_summary_without_any_answer():
    st = status_from_bytes(b"", P)
    assert st.summary() == "keine Statusantwort"


def test_preflight_lid_open_verified_no_unbestaetigt():
    st = status_from_bytes(bytes.fromhex("1a0599"), P)  # 99 = offen (invertiert), lid ist verified
    warnings = preflight(st, P)
    assert any("Deckel offen" in w for w in warnings)
    assert not any("unbestätigt" in w for w in warnings)


def test_preflight_lid_open_unverified_profile_adds_unbestaetigt():
    unverified = dataclasses.replace(P, verified=())
    st = status_from_bytes(bytes.fromhex("1a0599"), unverified)
    warnings = preflight(st, unverified)
    assert any("Deckel offen" in w and "unbestätigt" in w for w in warnings)


def test_preflight_battery_critical_low_and_special_code():
    assert any("kritisch" in w for w in preflight(status_from_bytes(bytes.fromhex("1a0408"), P), P))
    assert any("niedrig" in w for w in preflight(status_from_bytes(bytes.fromhex("1a0412"), P), P))
    assert any("kritisch" in w for w in preflight(status_from_bytes(bytes.fromhex("1a04a2"), P), P))


def test_preflight_empty_paper_warns_with_unbestaetigt():
    st = status_from_bytes(bytes.fromhex("1a0688"), P)
    warnings = preflight(st, P)
    assert any("Band leer" in w and "unbestätigt" in w for w in warnings)


def test_preflight_no_answer_warns_but_never_raises():
    st = status_from_bytes(b"", P)
    warnings = preflight(st, P)
    assert warnings == ["Keine Statusantwort. Drucker eingeschlafen? Druck wird trotzdem versucht"]


def test_preflight_all_good_returns_empty_list():
    st = status_from_bytes(bytes.fromhex("1a0598") + bytes.fromhex("1a044b"), P)
    assert preflight(st, P) == []
