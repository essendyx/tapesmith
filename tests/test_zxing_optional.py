"""zxing-cpp ist optional (Smart App Control blockiert die .pyd im Build): ohne Decoder laufen
Rendern, Selbsttest und Web-API weiter, das Rücklesen entfällt mit Warnung, der SN-Scan meldet
`decoder.unavailable`."""

import base64
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from tapesmith import cli, selftest, support
from tapesmith.device.profile import load_profile
from tapesmith.doctor import decoder_check
from tapesmith.errors import CODE_STATUS, ERROR_CODES, error_code, explain
from tapesmith.integrations import codescan
from tapesmith.render import zxing
from tapesmith.render.barcode import code128_modules, render_code128
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.render.datamatrix import render_datamatrix
from tapesmith.render.qr import render_qr

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = "import of zxingcpp halted; None in sys.modules"


@pytest.fixture
def no_zxing(monkeypatch):
    """Simuliert eine blockierte zxingcpp-.pyd: jeder Import wirft ImportError."""
    monkeypatch.setitem(sys.modules, "zxingcpp", None)
    zxing.reset()
    yield
    zxing.reset()


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_adapter_mit_zxing():
    pytest.importorskip("zxingcpp")
    zxing.reset()
    assert zxing.available() is True
    assert zxing.reason() == ""
    assert zxing.require() is sys.modules["zxingcpp"]


def test_adapter_ohne_zxing(no_zxing):
    assert zxing.available() is False
    assert BLOCKED in zxing.reason()
    with pytest.raises(zxing.DecoderUnavailable) as info:
        zxing.require()
    assert str(info.value).startswith("Barcode-Decoder nicht verfügbar: ")
    assert info.value.code == "decoder.unavailable"


def test_adapter_faengt_oserror(monkeypatch):
    def boom(name):
        raise OSError("DLL load failed while importing zxingcpp: Anwendungssteuerungsrichtlinie")

    monkeypatch.setattr(zxing.importlib, "import_module", boom)
    zxing.reset()
    try:
        assert zxing.available() is False
        assert "Anwendungssteuerungsrichtlinie" in zxing.reason()
    finally:
        zxing.reset()


def test_kernmodule_importieren_ohne_zxing():
    code = ("import sys\nsys.modules['zxingcpp'] = None\n"
            "import tapesmith.selftest, tapesmith.clipboard, tapesmith.document.render, tapesmith.cli\n"
            "import tapesmith.render.barcode, tapesmith.render.codes, tapesmith.render.qr\n"
            "import tapesmith.render.datamatrix, tapesmith.integrations.codescan\n"
            "import tapesmith.webapi.app, tapesmith.webapi.routes_codescan, tapesmith.cli_cmds.sn_scan\n"
            "from tapesmith.render import zxing\n"
            "assert not zxing.available(), zxing.reason()\n"
            "assert 'zxingcpp' not in [m for m, v in sys.modules.items() if v is not None]\n"
            "print('ok')\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_code128_rendert_ohne_zxing_mit_warnung(no_zxing):
    result = render_code128("ASN00042", 3, 88)
    assert result.decodes is False
    assert zxing.NOT_READ_WARNING in result.warnings
    assert len(code128_modules("ASN00042")) * 3 == result.image.width


def test_code128_ohne_zxing_bildgleich_zu_mit_zxing(monkeypatch):
    pytest.importorskip("zxingcpp")
    zxing.reset()
    with_decoder = render_code128("S4EWNX0R123456", 3, 88)
    monkeypatch.setitem(sys.modules, "zxingcpp", None)
    zxing.reset()
    try:
        without = render_code128("S4EWNX0R123456", 3, 88)
    finally:
        zxing.reset()
    assert with_decoder.decodes is True and zxing.NOT_READ_WARNING not in with_decoder.warnings
    assert without.image.tobytes() == with_decoder.image.tobytes()


def test_qr_rendert_ohne_zxing_mit_warnung(no_zxing):
    result = render_qr("HTTP://L.LAN/D7", 88)
    assert result.decodes is False
    assert zxing.NOT_READ_WARNING in result.warnings


def test_qr_label_rendert_ohne_zxing(no_zxing):
    result = render_label(LabelSpec(lines=("Test",), qr="HTTP://L.LAN/D7"), load_profile())
    assert result.head.width > 0


def test_datamatrix_rendert_ohne_zxing_mit_warnung(no_zxing):
    result = render_datamatrix("S4EWNX0R123456", 88)
    assert result.decodes is False
    assert zxing.NOT_READ_WARNING in result.warnings


def test_codescan_ohne_zxing_meldet_fehlercode(no_zxing):
    data = _png(Image.new("L", (40, 40), 255))
    with pytest.raises(zxing.DecoderUnavailable) as info:
        codescan.scan(data)
    exc = info.value
    assert error_code(exc) == "decoder.unavailable"
    assert explain(exc).title == "Barcode-Decoder nicht verfügbar"
    assert "decoder.unavailable" in ERROR_CODES
    assert CODE_STATUS["decoder.unavailable"] == 503


def test_cli_sn_scan_ohne_zxing(no_zxing, tmp_path, capsys):
    img = tmp_path / "aufkleber.png"
    Image.new("RGB", (40, 40), (255, 255, 255)).save(img)
    assert cli.main(["sn-scan", str(img)]) == 1
    err = capsys.readouterr().err
    assert "Barcode-Decoder nicht verfügbar" in err
    assert "Traceback" not in err


def test_route_codescan_ohne_zxing(no_zxing, tmp_path):
    from homelab_fakes import router_client
    from tapesmith.webapi import routes_codescan
    from webapi_fakes import close_ctx

    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        image_b64 = base64.b64encode(_png(Image.new("RGB", (40, 40), (255, 255, 255)))).decode("ascii")
        response = client.post("/api/v1/homelab/codescan", json={"image_b64": image_b64})
    finally:
        close_ctx(ctx)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "decoder.unavailable"


def test_selbsttest_ok_mit_warnung_ohne_zxing(no_zxing):
    out = io.StringIO()
    assert selftest.run_selftest(out) is True, out.getvalue()
    lines = out.getvalue().rstrip().splitlines()
    assert lines[-1] == "Selbsttest ok"
    assert "FEHLER" not in out.getvalue()
    warn = [line for line in lines if line.startswith("WARNUNG Barcode-Decoder:")]
    assert len(warn) == 1 and BLOCKED in warn[0]


def test_selbsttest_decoder_schritt_ok_mit_zxing(tmp_path):
    pytest.importorskip("zxingcpp")
    zxing.reset()
    step = dict(selftest._steps(tmp_path))["Barcode-Decoder"]
    assert step().startswith("zxing-cpp")


def test_doctor_zeigt_decoder(no_zxing):
    check = decoder_check()
    assert check.name == "Barcode-Decoder"
    assert check.ok is True
    assert "nicht verfügbar" in check.detail and BLOCKED in check.detail


def test_support_bericht_zeigt_decoder(no_zxing):
    text = support.decoder_line()
    assert text.startswith("Barcode-Decoder: nicht verfügbar")


def test_kernmodule_laden_zxing_nicht_beim_import():
    """Lazy: auch mit vorhandenem zxing-cpp lädt kein Kernmodul die .pyd schon beim Import."""
    code = ("import sys\n"
            "import tapesmith.selftest, tapesmith.document.render, tapesmith.integrations.codescan\n"
            "import tapesmith.webapi.app, tapesmith.cli\n"
            "print('zxingcpp' in sys.modules)\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_route_render_qr_ohne_zxing_meldet_checked_false(no_zxing, tmp_path):
    """W: Web-API meldet `checked=False`, damit die Oberfläche keinen roten Fehlerzustand zeigt,
    wenn der Code nur mangels Decoder nicht rückgelesen wurde."""
    from daemon_fakes import FakeNow
    from webapi_fakes import close_ctx, make_client

    client, ctx = make_client(tmp_path, now=FakeNow())
    try:
        r = client.post("/api/v1/labels/render",
                         json={"source": {"kind": "text", "lines": ["Doku"], "qr": "HTTP://L.LAN/D7"}})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["qr"]["decodes"] is False
        assert data["qr"]["checked"] is False
        assert zxing.NOT_READ_WARNING in data["qr"]["warnings"]
    finally:
        close_ctx(ctx)


def test_route_render_editor_codes_ohne_zxing_meldet_checked_false(no_zxing, tmp_path):
    from daemon_fakes import FakeNow
    from webapi_fakes import close_ctx, make_client

    doc = {"version": 1, "objects": [
        {"kind": "qr", "id": "q1", "x": 0, "y": 0, "w": 64, "h": 64, "data": "HTTP://L.LAN/D7"},
    ]}
    client, ctx = make_client(tmp_path, now=FakeNow())
    try:
        r = client.post("/api/v1/labels/render", json={"source": {"kind": "document", "document": doc}})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True, data["errors"]
        codes = data["editor"]["codes"]
        assert codes["q1"]["decodes"] is False
        assert codes["q1"]["checked"] is False
    finally:
        close_ctx(ctx)


def test_qr_kapazitaet_text_ohne_zxing(no_zxing):
    from tapesmith.render.qrcontent import capacity_report, url_content

    report = capacity_report(url_content("HTTP://L.LAN/D7"), load_profile())
    assert "nicht rückgelesen" in report.text()
