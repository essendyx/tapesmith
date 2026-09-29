import io
import json
from pathlib import Path

from PIL import Image

from tapesmith import compat, paths
from tapesmith.device.profile import load_profile
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.protocol.raster import place_on_head
from tapesmith.transport.base import MemoryTransport, TransportError

GOLDEN = Path(__file__).parent / "golden"
P = load_profile()


def _decode_hex_lines(text: str) -> bytes:
    data = b""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("b'") or not line.endswith("'"):
            continue
        # Zeile ist die print()-Repr eines bytes-Objekts, z. B. b'a1b2c3'
        data += bytes.fromhex(line[2:-1])
    return data


def test_render_label_main_writes_ascii_pbm_with_hint(monkeypatch):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    out, err = io.StringIO(), io.StringIO()
    assert compat.render_label_main(["Test"], stdout=out, stderr=err) == 0
    text = out.getvalue()
    assert text.startswith("P1\n88 ")
    body_lines = text.split("\n")[2:]
    for line in body_lines:
        assert set(line) <= {"0", "1", " "}
    img = Image.open(io.BytesIO(text.encode()))
    assert img.width == 88
    assert "Kompatibilitätsbefehl" in err.getvalue()


def test_render_label_main_margin_too_large_is_error():
    out, err = io.StringIO(), io.StringIO()
    assert compat.render_label_main(["Test", "--margin", "4"], stdout=out, stderr=err) == 1
    assert "Fehler:" in err.getvalue()


def test_render_label_main_mono_font_differs_from_sans():
    out_sans, err = io.StringIO(), io.StringIO()
    compat.render_label_main(["Test"], stdout=out_sans, stderr=err)
    out_mono, err2 = io.StringIO(), io.StringIO()
    assert compat.render_label_main(["Test", "--font", "DejaVu Sans Mono"], stdout=out_mono, stderr=err2) == 0
    assert out_sans.getvalue() != out_mono.getvalue()
    assert "nicht verfügbar" not in err2.getvalue()


def test_print_p12_main_dummy_pipeline_matches_manual_job(monkeypatch):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    render_out, render_err = io.StringIO(), io.StringIO()
    assert compat.render_label_main(["SSD-1"], stdout=render_out, stderr=render_err) == 0
    pbm_bytes = render_out.getvalue().encode()

    print_err = io.StringIO()
    rc = compat.print_p12_main(["--port", "dummy"], stdin=io.BytesIO(pbm_bytes), stderr=print_err)
    assert rc == 0
    decoded = _decode_hex_lines(print_err.getvalue())

    expected_head = place_on_head(Image.open(io.BytesIO(pbm_bytes)), P)
    expected = job_bytes(build_job(expected_head, P))
    assert decoded == expected


def test_print_p12_main_dummy_with_golden_file_matches_reference():
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "dummy", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 0
    decoded = _decode_hex_lines(err.getvalue())
    assert decoded == (GOLDEN / "ref_stream.bin").read_bytes()
    assert "Kompatibilitätsbefehl" in err.getvalue()


def test_print_p12_main_wrong_dots_is_error():
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "dummy", "--dots", "80", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 1
    assert "Fehler:" in err.getvalue()


def test_print_p12_main_real_port_mocked(monkeypatch):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    transport = MemoryTransport()
    monkeypatch.setattr(compat, "open_transport", lambda port, mac, *a, **k: transport)
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "COM4", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 0
    assert transport.opened and transport.closed
    assert transport.written


def test_print_p12_main_real_port_unreachable_is_exit_5(monkeypatch):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)

    def boom(port, mac, *a, **k):
        raise TransportError("weg")

    monkeypatch.setattr(compat, "open_transport", boom)
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "COM4", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 5
    assert "Fehler:" in err.getvalue()


def test_print_p12_main_uses_connect_timeout_s_from_config(monkeypatch, app_home):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    paths.config_path().write_text(json.dumps({"connect_timeout_s": 2.5}), encoding="utf-8")
    calls = []

    def fake_open_transport(port, mac, *a, **kw):
        calls.append(kw)
        return MemoryTransport()

    monkeypatch.setattr(compat, "open_transport", fake_open_transport)
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "COM4", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 0
    assert calls == [{"open_timeout": 2.5}]


def test_print_p12_main_default_connect_timeout_s_without_config(monkeypatch, app_home):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    calls = []

    def fake_open_transport(port, mac, *a, **kw):
        calls.append(kw)
        return MemoryTransport()

    monkeypatch.setattr(compat, "open_transport", fake_open_transport)
    err = io.StringIO()
    rc = compat.print_p12_main(["--port", "COM4", str(GOLDEN / "ref_label.pbm")], stderr=err)
    assert rc == 0
    assert calls == [{"open_timeout": 5.0}]


class _RecordingStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.reconfigure_calls = []

    def reconfigure(self, **kw):
        self.reconfigure_calls.append(kw)


def test_main_print_reconfigures_stdout_and_stderr_to_utf8(monkeypatch, tmp_path):
    monkeypatch.setattr(compat, "SLEEP", lambda s: None)
    out_stream, err_stream = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr("sys.stdout", out_stream)
    monkeypatch.setattr("sys.stderr", err_stream)
    monkeypatch.setattr("sys.argv", ["phomemo_print_p12", "--port", "dummy", str(GOLDEN / "ref_label.pbm")])
    try:
        compat.main_print()
    except SystemExit:
        pass
    for stream in (out_stream, err_stream):
        assert stream.reconfigure_calls
        assert stream.reconfigure_calls[0]["encoding"] == "utf-8"


def test_main_render_reconfigures_stdout_and_stderr_to_utf8(monkeypatch):
    out_stream, err_stream = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr("sys.stdout", out_stream)
    monkeypatch.setattr("sys.stderr", err_stream)
    monkeypatch.setattr("sys.argv", ["phomemo_render_label", "Test"])
    try:
        compat.main_render()
    except SystemExit:
        pass
    for stream in (out_stream, err_stream):
        assert stream.reconfigure_calls
        assert stream.reconfigure_calls[0]["encoding"] == "utf-8"
