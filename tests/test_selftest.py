"""Qt-freier Selbsttest (`tapesmith.selftest`) für `Tapesmith.exe --selftest` und
`tapesmith gui --selftest`. Kein Port, kein Fenster, keine Nutzerdaten, druckt nie."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tapesmith import selftest, webui

ROOT = Path(__file__).resolve().parents[1]

CORE_STEPS = ("OK profil", "OK schriften", "OK vorlagen", "OK qr", "OK Dokument", "OK Codes", "OK Icons",
              "OK Invertierung", "OK Vorlagen-Lint", "OK IPC", "OK Dienst", "OK Warteschlange", "OK Zwischenablage")
WEB_STEPS = ("OK Web-API", "OK Oberfläche", "OK Webserver", "OK Browserstart")
EXTRA_STEPS = ("OK Übersetzungen", "OK Update-Signatur", "OK Installationslayout")


def _lines(out: io.StringIO) -> list[str]:
    return out.getvalue().rstrip().splitlines()


def test_selbsttest_ok(app_home, monkeypatch):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    home_before = os.environ.get("TAPESMITH_HOME")
    out = io.StringIO()
    assert selftest.run_selftest(out) is True, out.getvalue()
    text = out.getvalue()
    for name in CORE_STEPS + WEB_STEPS + EXTRA_STEPS:
        assert name in text, name
    lines = _lines(out)
    names = [line.split(":", 1)[0] for line in lines[:-1]]
    assert names[-3:] == list(EXTRA_STEPS), "die zusätzlichen Schritte laufen nach den bestehenden"
    assert _lines(out)[-1] == "Selbsttest ok"
    assert "FEHLER" not in text
    assert os.environ.get("TAPESMITH_HOME") == home_before
    assert "TAPESMITH_NO_DAEMON" not in os.environ
    assert not app_home.exists() or not any(app_home.iterdir())


def test_fehlende_index_html(tmp_path, monkeypatch):
    empty = tmp_path / "leer"
    empty.mkdir()
    monkeypatch.setattr(webui, "static_dir", lambda: empty)
    out = io.StringIO()
    assert selftest.run_selftest(out) is False
    lines = _lines(out)
    assert any(line.startswith("FEHLER Oberfläche") and "index.html" in line for line in lines)
    assert lines[-1] == "Selbsttest fehlgeschlagen"


def test_fehlende_asset_datei(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "da.js").write_text("//", encoding="utf-8")
    (static / "index.html").write_text(
        '<script type="module" src="/assets/da.js"></script><link href="/assets/fehlt.css">',
        encoding="utf-8")
    with pytest.raises(RuntimeError, match="fehlt.css"):
        selftest.check_static(static)


def test_statische_dateien_ok(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "a.js").write_text("//", encoding="utf-8")
    (static / "index.html").write_text('<script src="/assets/a.js"></script>', encoding="utf-8")
    assert "1 Datei" in selftest.check_static(static)


def test_fehler_eines_schritts_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(selftest, "list_templates", lambda: [])
    out = io.StringIO()
    assert selftest.run_selftest(out) is False
    lines = _lines(out)
    assert any(line.startswith("FEHLER vorlagen") for line in lines)
    assert lines[-1] == "Selbsttest fehlgeschlagen"


def test_browserstart_baut_adresse_ohne_browser(monkeypatch):
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: pytest.fail("kein echter Browser"))
    assert selftest.check_browser_start(frozen=False) == "Adresse mit Token ok, kein App-Fenster"


def test_browserstart_im_build_meldet_altes_app_fenster(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: object() if name == "webview" else real(name, *a))
    with pytest.raises(RuntimeError, match="altes App-Fenster im Build: webview"):
        selftest.check_browser_start(frozen=True)


def test_browserstart_im_build_ohne_app_fenster_ok(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    old = {"webview", "clr", "clr_loader", "pythonnet"}
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name in old else real(name, *a))
    assert selftest.check_browser_start(frozen=True).startswith("Adresse mit Token ok")


def test_browserstart_im_build_meldet_tray_fenster(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: object() if name == "tapesmith.gui.quick_popup" else real(name, *a))
    with pytest.raises(RuntimeError, match="tapesmith.gui.quick_popup"):
        selftest.check_browser_start(frozen=True)


def test_setzt_umgebung_zurueck(monkeypatch):
    monkeypatch.setenv("TAPESMITH_NO_DAEMON", "0")
    seen = []
    monkeypatch.setattr(selftest, "_steps",
                        lambda tmp: [("probe", lambda: seen.append(os.environ.get("TAPESMITH_NO_DAEMON")) or "x")])
    assert selftest.run_selftest(io.StringIO()) is True
    assert seen == ["1"]
    assert os.environ["TAPESMITH_NO_DAEMON"] == "0"


def test_main_mit_ausgabedatei(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest, "_steps", lambda tmp: [("probe", lambda: "x")])
    target = tmp_path / "s.txt"
    assert selftest.main(["--selftest-out", str(target)]) == 0
    assert target.read_text(encoding="utf-8").rstrip().splitlines()[-1] == "Selbsttest ok"


def test_main_fehler_exit_1(tmp_path, monkeypatch):
    def boom() -> str:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(selftest, "_steps", lambda tmp: [("probe", boom)])
    target = tmp_path / "s.txt"
    assert selftest.main(["--selftest", "--selftest-out", str(target)]) == 1
    text = target.read_text(encoding="utf-8")
    assert "FEHLER probe: kaputt" in text
    assert text.rstrip().endswith("Selbsttest fehlgeschlagen")


def test_main_stdout(monkeypatch, capsys):
    monkeypatch.setattr(selftest, "_steps", lambda tmp: [("probe", lambda: "x")])
    assert selftest.main([]) == 0
    assert capsys.readouterr().out.rstrip().endswith("Selbsttest ok")


def test_selbsttest_importiert_kein_qt(tmp_path):
    code = ("import io, sys\nfrom tapesmith import selftest\nout = io.StringIO()\n"
            "ok = selftest.run_selftest(out)\n"
            "print(ok, 'PySide6' in sys.modules)\nprint(out.getvalue(), file=sys.stderr)\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["TAPESMITH_HOME"] = str(tmp_path / "home")
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                            timeout=180, check=True)
    assert result.stdout.strip() == "True False", result.stderr


def test_web_api_fehler_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(selftest, "WEB_REQUESTS", (("GET", "/api/v1/gibt-es-nicht", None),))
    out = io.StringIO()
    assert selftest.run_selftest(out) is False
    assert any(line.startswith("FEHLER Web-API") and "gibt-es-nicht (404)" in line for line in _lines(out))


def test_asgi_anfrage_ohne_token_wird_abgelehnt(tmp_path):
    from tapesmith.webapi.app import create_app
    from webapi_fakes import close_ctx, make_ctx

    ctx = make_ctx(tmp_path)
    try:
        app = create_app(ctx)
        assert selftest.asgi_request(app, "GET", "/api/v1/settings", token="falsch", port=ctx.port)[0] == 401
        assert selftest.asgi_request(app, "GET", "/health", token="", port=ctx.port)[0] == 200
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- Übersetzungen, Update-Signatur, Installationslayout


def _step(name: str, tmp_path):
    return dict(selftest._steps(tmp_path))[name]


def test_uebersetzungen_de_en_gleiche_schluessel(tmp_path):
    detail = _step("Übersetzungen", tmp_path)()
    assert detail.startswith("de/en, ")
    assert detail.endswith(" Meldungen")
    assert int(detail.split(", ")[1].split()[0]) > 50
    assert int(detail.split(", ")[2].split()[0]) > 1000     # Meldungskatalog en geladen


def test_uebersetzungen_fehlender_schluessel_wird_gemeldet(tmp_path, monkeypatch):
    real = selftest.i18n.catalog

    def catalog(lang):
        data = real(lang)
        if lang == "en":
            data = {**data, "common": {}}
        return data

    monkeypatch.setattr(selftest.i18n, "catalog", catalog)
    with pytest.raises(RuntimeError, match="nur in de"):
        _step("Übersetzungen", tmp_path)()


def test_uebersetzungen_leerer_katalog(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest.i18n, "catalog", lambda lang: {})
    with pytest.raises(RuntimeError, match="leer"):
        _step("Übersetzungen", tmp_path)()


def test_update_signatur_nennt_anzahl_schluessel(tmp_path, monkeypatch):
    keys = tmp_path / "trusted_keys.json"
    keys.write_text('{"keys": []}', encoding="utf-8")
    monkeypatch.setattr(selftest.signing, "TRUSTED_KEYS_PATH", keys)
    assert _step("Update-Signatur", tmp_path)() == "Ed25519 ok, 0 hinterlegte Schlüssel"


def test_update_signatur_unlesbare_schluesseldatei(tmp_path, monkeypatch):
    keys = tmp_path / "trusted_keys.json"
    keys.write_text("kaputt", encoding="utf-8")
    monkeypatch.setattr(selftest.signing, "TRUSTED_KEYS_PATH", keys)
    with pytest.raises(Exception, match="unlesbar"):
        _step("Update-Signatur", tmp_path)()


def test_update_signatur_fehlende_schluesseldatei(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest.signing, "TRUSTED_KEYS_PATH", tmp_path / "fehlt.json")
    with pytest.raises(RuntimeError, match="trusted_keys.json fehlt"):
        _step("Update-Signatur", tmp_path)()


def test_installationslayout_legt_junction_an_und_raeumt_auf(tmp_path):
    assert _step("Installationslayout", tmp_path)() == "Junction anlegen, umstellen, entfernen ok"
    probe = tmp_path / "installationsprobe"
    assert not probe.exists()
