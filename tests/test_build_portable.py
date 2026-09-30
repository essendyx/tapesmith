"""Tests für tools/build_portable.py (Portable Onedir-Build)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_portable.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_portable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bp():
    return _load_module()


# ---------- 1. Vollständigkeit der Datendateien ----------

def test_data_files_covers_all_package_data(bp):
    pkg_dir = ROOT / "src" / "tapesmith"
    expected_sources = {
        p for p in pkg_dir.rglob("*")
        if p.is_file()
        and p.suffix not in (".py", ".pyc")
        and "__pycache__" not in p.parts
    }
    result = bp.data_files()
    actual_sources = {source for source, _target in result}
    assert actual_sources == expected_sources

    must_have = {
        "fonts/DejaVuSans.ttf",
        "fonts/DejaVuSans-Bold.ttf",
        "fonts/DejaVuSansMono.ttf",
        "fonts/LICENSE",
        "device/profiles/p12.json",
        "templates/builtin/datentraeger.tapesmith.json",
        "templates/builtin/datentraeger-qr.tapesmith.json",
        "icons/tabler-icons.ttf",
        "icons/tabler-index.json",
        "icons/categories.json",
        "icons/LICENSE-tabler.txt",
        "icons/simple/LICENSE-simple-icons.txt",
        "tape/tapes.json",
        "document/targets.json",
        "templates/builtin/kabelfahne.tapesmith.json",
        "templates/builtin/gefriergut.tapesmith.json",
        "templates/builtin/asn.tapesmith.json",
    }
    have = {str((source.relative_to(pkg_dir)).as_posix()) for source, _target in result}
    assert must_have <= have

    targets = {source: target for source, target in result}
    template_source = pkg_dir / "templates" / "builtin" / "datentraeger.tapesmith.json"
    assert targets[template_source] == "tapesmith/templates/builtin"


def test_data_files_with_temp_package_tree(bp, tmp_path):
    pkg = tmp_path / "tapesmith"
    (pkg / "__pycache__").mkdir(parents=True)
    (pkg / "data").mkdir()
    (pkg / "a.py").write_text("# code", encoding="utf-8")
    (pkg / "__pycache__" / "a.pyc").write_bytes(b"\x00")
    (pkg / "data" / "x.json").write_text("{}", encoding="utf-8")
    (pkg / "y.ttf").write_bytes(b"font")

    result = bp.data_files(pkg)
    assert set(result) == {
        (pkg / "data" / "x.json", "tapesmith/data"),
        (pkg / "y.ttf", "tapesmith"),
    }


# ---------- 3. PyInstaller-Argumente ----------

def test_pyinstaller_args(bp, tmp_path):
    dist = tmp_path / "dist"
    work = tmp_path / "build"
    args = bp.pyinstaller_args(dist=dist, work=work)

    assert "--onedir" in args
    assert "--windowed" in args
    assert "--onefile" not in args

    idx = args.index("--collect-submodules")
    assert args[idx + 1] == "tapesmith"

    for source, target in bp.data_files():
        pair_value = f"{source}{os.pathsep}{target}"
        add_idx = args.index("--add-data")
        assert pair_value in args
        assert args[args.index(pair_value) - 1] == "--add-data"

    assert args[-1] == str(bp.ENTRY)

    # Abhängigkeiten, die PyInstaller nicht sicher selbst findet (Namespace-Paket
    # `ppf`, `openpyxl` nur innerhalb einer Funktion importiert)
    for module in ("ppf.datamatrix", "openpyxl"):
        assert module in args
        assert args[args.index(module) - 1] == "--hidden-import"


def test_pyinstaller_args_dienst_und_tray(bp, tmp_path):
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build",
                               available=lambda name: True)
    for module in ("tapesmith.daemon.instance", "tapesmith.gui.tray", "winrt.windows.devices.bluetooth"):
        assert module in args
        assert args[args.index(module) - 1] == "--hidden-import"
    collected = [args[i + 1] for i, a in enumerate(args) if a == "--collect-submodules"]
    assert collected == ["tapesmith", "bleak", "cryptography"]
    assert args[-1] == str(bp.ENTRY)


WWEB_HIDDEN = ("tapesmith.webui.browser", "tapesmith.webapi.app", "tapesmith.webapi.server", "tapesmith.selftest",
               "uvicorn.loops.auto", "uvicorn.loops.asyncio", "uvicorn.protocols.http.auto",
               "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.off")


def test_pyinstaller_args_web_hidden_imports(bp, tmp_path):
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", available=lambda name: False)
    for module in WWEB_HIDDEN:
        assert module in args, module
        assert args[args.index(module) - 1] == "--hidden-import"


@pytest.mark.parametrize("available", [True, False])
def test_pyinstaller_args_schliessen_das_fruehere_app_fenster_aus(bp, tmp_path, available):
    """Nur Browser plus Tray: pywebview, WebView2 und pythonnet kommen nie in den Build, auch wenn
    sie im venv noch installiert sind."""
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", available=lambda name: available)
    excluded = [args[i + 1] for i, a in enumerate(args) if a == "--exclude-module"]
    assert excluded == ["tkinter", "webview", "clr", "clr_loader", "pythonnet"]
    for flag in ("--collect-submodules", "--collect-data", "--hidden-import"):
        values = [args[i + 1] for i, a in enumerate(args) if a == flag]
        assert not {"webview", "clr", "clr_loader", "pythonnet"} & set(values), flag
    assert "--collect-data" not in args


def test_data_files_enthalten_web_oberflaeche(bp):
    pkg_dir = ROOT / "src" / "tapesmith"
    targets = {source: target for source, target in bp.data_files()}
    index = pkg_dir / "webui" / "static" / "index.html"
    assert targets[index] == "tapesmith/webui/static"
    assets = [s for s in targets if s.parent == pkg_dir / "webui" / "static" / "assets"]
    assert assets
    assert all(targets[s] == "tapesmith/webui/static/assets" for s in assets)


def test_pyinstaller_args_ohne_bleak(bp, tmp_path):
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build",
                               available=lambda name: False)
    assert "bleak" not in args
    assert "winrt.windows.devices.bluetooth" not in args
    # Dienst und Tray gehören immer dazu
    assert "tapesmith.daemon.instance" in args and "tapesmith.gui.tray" in args


def test_module_available(bp):
    assert bp.module_available("json") is True
    assert bp.module_available("gibt_es_nicht_p12") is False
    assert bp.module_available("gibt_es_nicht_p12.unter") is False


# ---------- Icon ----------

def test_pyinstaller_args_ohne_icon_kein_flag(bp, tmp_path):
    pkg = tmp_path / "tapesmith"
    (pkg / "icons").mkdir(parents=True)
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", pkg_dir=pkg)
    assert "--icon" not in args


def test_pyinstaller_args_mit_icon_haengt_flag_an(bp, tmp_path):
    pkg = tmp_path / "tapesmith"
    (pkg / "icons").mkdir(parents=True)
    icon = pkg / "icons" / "app.ico"
    icon.write_bytes(b"icon")
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", pkg_dir=pkg)
    assert "--icon" in args
    assert args[args.index("--icon") + 1] == str(icon)
    assert args[-1] == str(bp.ENTRY)  # Icon vor dem Entry-Skript, das bleibt immer letztes Argument


def test_entry_ist_die_weiche(bp):
    text = bp.ENTRY.read_text(encoding="utf-8")
    assert '"--daemon"' in text and '"--tray"' in text and '"--app"' in text and '"--selftest"' in text
    assert '"--install"' in text and '"--uninstall"' in text and '"--update-apply"' in text


def _load_entry():
    spec = importlib.util.spec_from_file_location("tapesmith_gui_entry_test", ROOT / "tools" / "tapesmith_gui_entry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv, target, rest", [
    (["--daemon", "--foreground"], "daemon", ["--foreground"]),
    (["--tray", "--no-hotkeys"], "tray", ["--no-hotkeys"]),
    (["--app", "--route", "/verlauf"], "browser", ["--route", "/verlauf"]),
    (["--selftest", "--selftest-out", "x.txt"], "selftest", ["--selftest", "--selftest-out", "x.txt"]),
    (["--uri", "tapesmith://text?l=x"], "browser", ["--uri", "tapesmith://text?l=x"]),
    (["--open", "lines", "--path", "C:/a.txt"], "browser", ["--open", "lines", "--path", "C:/a.txt"]),
    (["--install", "--root", "C:/t", "--quiet"], "install", ["--root", "C:/t", "--quiet"]),
    (["--uninstall", "--quiet"], "uninstall", ["--quiet"]),
    ([], "browser", []),
])
def test_entry_weiche(monkeypatch, argv, target, rest):
    from tapesmith import selftest
    from tapesmith.daemon import instance
    from tapesmith.gui import tray
    from tapesmith.install import installer, uninstaller
    from tapesmith.webui import browser

    calls = []
    codes = {"daemon": 3, "tray": 4, "browser": 5, "selftest": 6, "install": 7, "uninstall": 8}
    monkeypatch.setattr(instance, "main", lambda a=None: calls.append(("daemon", a)) or 3)
    monkeypatch.setattr(tray, "main", lambda a=None: calls.append(("tray", a)) or 4)
    def browser_main(a=None, **kw):
        assert kw == {}, "die EXE ruft browser.main ohne Meldungsfenster auf"
        calls.append(("browser", a))
        return 5

    monkeypatch.setattr(browser, "main", browser_main)
    monkeypatch.setattr(selftest, "main", lambda a=None: calls.append(("selftest", a)) or 6)
    monkeypatch.setattr(installer, "main", lambda a=None: calls.append(("install", a)) or 7)
    monkeypatch.setattr(uninstaller, "main", lambda a=None: calls.append(("uninstall", a)) or 8)
    code = _load_entry().main(argv)
    assert calls == [(target, rest)]
    assert code == codes[target]


def test_entry_update_apply_importiert_erst_im_zweig(monkeypatch):
    """`--update-apply` darf `tapesmith.update.apply` erst im eigenen Zweig importieren: das
    Modul wird hier nicht gebraucht. `sys.modules` wird mit einem Fake
    vorbelegt, so wie es die spätere echte Weiche vorfinden würde."""
    import types

    fake_apply = types.ModuleType("tapesmith.update.apply")
    calls = []
    fake_apply.main = lambda a=None: calls.append(("update-apply", a)) or 9
    monkeypatch.setitem(sys.modules, "tapesmith.update.apply", fake_apply)

    code = _load_entry().main(["--update-apply", "--version", "0.2.1"])

    assert calls == [("update-apply", ["--version", "0.2.1"])]
    assert code == 9


def test_entry_importiert_nichts_vorab():
    text = (ROOT / "tools" / "tapesmith_gui_entry.py").read_text(encoding="utf-8")
    top = text.split("def main", 1)[0]
    imports = [line for line in top.splitlines() if line.startswith(("import ", "from "))]
    assert imports == ["import sys"]


def test_python_m_gui_oeffnet_browser():
    text = (ROOT / "src" / "tapesmith" / "gui" / "__main__.py").read_text(encoding="utf-8")
    assert "from tapesmith.webui.browser import main" in text
    assert "sys.exit(main())" in text
    assert "error_box" not in text


# ---------- 4. Nuitka-Argumente ----------

def test_nuitka_args(bp, tmp_path):
    args = bp.nuitka_args(dist=tmp_path / "dist")
    assert "--standalone" in args
    assert "--include-package-data=tapesmith" in args
    assert "--enable-plugin=pyside6" in args
    assert "--onefile" not in args


# ---------- 5. build() mit Fake-run ----------

def test_build_pyinstaller_success(bp, tmp_path):
    dist = tmp_path / "dist"
    work = tmp_path / "build"
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        exe = dist / "Tapesmith" / "Tapesmith.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")
        return subprocess.CompletedProcess(args, 0)

    exe = bp.build(backend="pyinstaller", dist=dist, work=work, run=fake_run)
    assert exe == dist / "Tapesmith" / "Tapesmith.exe"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == [sys.executable, "-m", "PyInstaller"]
    assert kwargs["cwd"] == bp.ROOT
    assert kwargs["timeout"] == 900


def test_build_setzt_pythonpath_auf_diesen_quellbaum(bp, tmp_path, monkeypatch):
    """`--collect-submodules tapesmith` importiert tapesmith in einem Hilfsprozess. Ohne PYTHONPATH
    fände er eine editierbare Installation eines anderen Checkouts (z. B. Worktree-Build)."""
    monkeypatch.setenv("PYTHONPATH", "C:/anders")
    dist = tmp_path / "dist"
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        exe = dist / "Tapesmith" / "Tapesmith.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")
        return subprocess.CompletedProcess(args, 0)

    bp.build(backend="pyinstaller", dist=dist, work=tmp_path / "build", run=fake_run)
    parts = seen["env"]["PYTHONPATH"].split(os.pathsep)
    assert parts == [str(bp.ROOT / "src"), "C:/anders"]


def test_build_pyinstaller_missing_exe(bp, tmp_path):
    dist = tmp_path / "dist"

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0)

    with pytest.raises(RuntimeError):
        bp.build(backend="pyinstaller", dist=dist, work=tmp_path / "build", run=fake_run)


def test_build_timeout(bp, tmp_path):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 900))

    with pytest.raises(RuntimeError, match="15 min"):
        bp.build(backend="pyinstaller", dist=tmp_path / "dist", work=tmp_path / "build", run=fake_run)


def test_build_unknown_backend(bp, tmp_path):
    with pytest.raises(ValueError):
        bp.build(backend="zip", dist=tmp_path / "dist", work=tmp_path / "build", run=lambda *a, **k: None)


# ---------- 6. smoke_test ----------

def test_smoke_test_success(bp, tmp_path):
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"
    captured_env = {}
    captured_args = {}

    def fake_run(args, *, env=None, timeout=None):
        captured_env.update(env or {})
        captured_args["args"] = args
        out.write_text("OK profil: P12\nSelbsttest ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    assert bp.smoke_test(exe, out, run=fake_run) is True
    assert captured_env["QT_QPA_PLATFORM"] == "offscreen"
    assert "--selftest" in captured_args["args"]
    assert "--selftest-out" in captured_args["args"]


def test_smoke_test_failed_selftest(bp, tmp_path):
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"

    def fake_run(args, *, env=None, timeout=None):
        out.write_text("OK profil: P12\nSelbsttest fehlgeschlagen\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    assert bp.smoke_test(exe, out, run=fake_run) is False


def test_smoke_test_nonzero_returncode(bp, tmp_path):
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"

    def fake_run(args, *, env=None, timeout=None):
        out.write_text("Selbsttest ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 1)

    assert bp.smoke_test(exe, out, run=fake_run) is False


def test_smoke_test_missing_file(bp, tmp_path):
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"

    def fake_run(args, *, env=None, timeout=None):
        return subprocess.CompletedProcess(args, 0)

    assert bp.smoke_test(exe, out, run=fake_run) is False


def test_smoke_test_timeout(bp, tmp_path):
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"

    def fake_run(args, *, env=None, timeout=None):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    assert bp.smoke_test(exe, out, run=fake_run) is False


def test_smoke_test_blocked_by_os(bp, tmp_path):
    """WinError 4551 u.ae. (Defender/AppLocker/WDAC blockiert die frische EXE) -> False, kein Crash."""
    exe = tmp_path / "Tapesmith.exe"
    out = tmp_path / "selftest.txt"

    def fake_run(args, *, env=None, timeout=None):
        raise OSError("[WinError 4551] Eine Anwendungssteuerungsrichtlinie hat diese Datei blockiert")

    assert bp.smoke_test(exe, out, run=fake_run) is False


# ---------- 7. make_zip ----------

def test_make_zip(bp, tmp_path):
    app_dir = tmp_path / "dist" / "Tapesmith"
    (app_dir / "_internal" / "tapesmith" / "fonts").mkdir(parents=True)
    (app_dir / "Tapesmith.exe").write_bytes(b"exe")
    (app_dir / "_internal" / "tapesmith" / "fonts" / "x.ttf").write_bytes(b"font")

    zip_path = tmp_path / "out.zip"
    result = bp.make_zip(app_dir, zip_path)
    assert result == zip_path

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "Tapesmith/Tapesmith.exe" in names
    assert "Tapesmith/_internal/tapesmith/fonts/x.ttf" in names


def test_make_zip_installieren_cmd(bp, tmp_path):
    app_dir = tmp_path / "dist" / "Tapesmith"
    app_dir.mkdir(parents=True)
    (app_dir / "Tapesmith.exe").write_bytes(b"exe")

    zip_path = tmp_path / "out.zip"
    bp.make_zip(app_dir, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert "Installieren.cmd" in zf.namelist()
        content = zf.read("Installieren.cmd")
    assert content == b'@echo off\r\n"%~dp0Tapesmith\\Tapesmith.exe" --install\r\n'


# ---------- 8. main --dry-run ----------

def test_main_dry_run(bp, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append((a, k)))

    result = bp.main(["--dry-run"])
    assert result == 0
    out = capsys.readouterr().out
    assert "PyInstaller" in out
    assert "--onedir" in out
    assert called == []


# ---------- 9. main Ablauf ----------

def test_main_success(bp, tmp_path, monkeypatch, capsys):
    exe = tmp_path / "dist" / "Tapesmith" / "Tapesmith.exe"

    def fake_build(**kwargs):
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")
        return exe

    def fake_smoke_test(exe_path, out, **kwargs):
        out.write_text("Selbsttest ok\n", encoding="utf-8")
        return True

    monkeypatch.setattr(bp, "build", fake_build)
    monkeypatch.setattr(bp, "smoke_test", fake_smoke_test)

    result = bp.main(["--dist", str(tmp_path / "dist"), "--skip-smoke"])
    assert result == 0


def test_main_selftest_failure(bp, tmp_path, monkeypatch, capsys):
    exe = tmp_path / "dist" / "Tapesmith" / "Tapesmith.exe"

    def fake_build(**kwargs):
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")
        return exe

    def fake_smoke_test(exe_path, out, **kwargs):
        out.write_text("Selbsttest fehlgeschlagen\n", encoding="utf-8")
        return False

    monkeypatch.setattr(bp, "build", fake_build)
    monkeypatch.setattr(bp, "smoke_test", fake_smoke_test)

    result = bp.main(["--dist", str(tmp_path / "dist")])
    assert result == 1
    err = capsys.readouterr().err
    assert "Selbsttest" in err


def test_pyinstaller_args_zxing_optional(bp, tmp_path):
    """zxing-cpp wird nur noch per importlib geladen (render.zxing), PyInstaller sieht den Import
    nicht: als Hidden-Import mitnehmen, wenn installiert, sonst ohne bauen."""
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", available=lambda name: True)
    assert "zxingcpp" in args
    assert args[args.index("zxingcpp") - 1] == "--hidden-import"
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", available=lambda name: False)
    assert "zxingcpp" not in args


def test_smoke_test_with_retry_zweiter_versuch(bp, tmp_path):
    results = iter([False, True])
    slept = []
    assert bp.smoke_test_with_retry(tmp_path / "x.exe", tmp_path / "o.txt",
                                    test=lambda exe, out: next(results), sleep=slept.append) is True
    assert slept == [5.0]


def test_smoke_test_with_retry_gibt_nach_versuchen_auf(bp, tmp_path):
    calls = []
    ok = bp.smoke_test_with_retry(tmp_path / "x.exe", tmp_path / "o.txt",
                                  test=lambda exe, out: calls.append(1) or False, sleep=lambda s: None)
    assert ok is False and len(calls) == 2


# ---------- Versionsressource (Pflicht für die Signatur über SignPath) ----------

@pytest.mark.parametrize("version, expected", [("0.3.0", (0, 3, 0, 0)), ("1.2", (1, 2, 0, 0)),
                                               ("0.4.0b1", (0, 4, 0, 0)), ("1.2.3.4.5", (1, 2, 3, 4))])
def test_version_tuple(bp, version, expected):
    assert bp.version_tuple(version) == expected


def test_version_tuple_unlesbar(bp):
    with pytest.raises(ValueError):
        bp.version_tuple("x.1")


def test_version_file_text_traegt_produktname_und_version(bp):
    import ast

    text = bp.version_file_text("0.3.0")
    tree = ast.parse(text, mode="eval")
    assert isinstance(tree.body, ast.Call) and tree.body.func.id == "VSVersionInfo"
    strings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "StringStruct":
            key, value = (arg.value for arg in node.args)
            strings[key] = value
    assert strings["ProductName"] == "Tapesmith"
    assert strings["ProductVersion"] == "0.3.0"
    assert strings["FileVersion"] == "0.3.0"
    assert strings["OriginalFilename"] == "Tapesmith.exe"
    assert "filevers=(0, 3, 0, 0)" in text and "prodvers=(0, 3, 0, 0)" in text


def test_version_passt_zur_signpath_konfiguration(bp):
    """Produktname in der Versionsressource und in `.signpath/artifact-configuration.xml` gleich."""
    xml = (ROOT / ".signpath" / "artifact-configuration.xml").read_text(encoding="utf-8")
    assert f'product-name="{bp.PRODUCT_NAME}"' in xml
    assert 'product-version="${version}"' in xml


def test_pyinstaller_args_mit_versionsdatei(bp, tmp_path):
    version_file = tmp_path / "version_info.txt"
    args = bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build", version_file=version_file)
    i = args.index("--version-file")
    assert args[i + 1] == str(version_file)
    assert args[-1] == str(bp.ENTRY)
    assert "--version-file" not in bp.pyinstaller_args(dist=tmp_path / "dist", work=tmp_path / "build")


def test_build_schreibt_versionsdatei(bp, tmp_path):
    dist = tmp_path / "dist"
    work = tmp_path / "build"
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args)
        exe = dist / "Tapesmith" / "Tapesmith.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")
        return subprocess.CompletedProcess(args, 0)

    bp.build(backend="pyinstaller", dist=dist, work=work, run=fake_run)
    version_file = work / "version_info.txt"
    assert seen[0][seen[0].index("--version-file") + 1] == str(version_file)
    assert f"StringStruct('ProductVersion', '{bp._read_version()}')" in version_file.read_text(encoding="utf-8")


# ---------- Zip aus einem fertigen (signierten) Ordner ----------

def test_main_zip_from(bp, tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "build", lambda **kwargs: pytest.fail("darf nicht bauen"))
    app_dir = tmp_path / "signed" / "Tapesmith"
    (app_dir / "_internal").mkdir(parents=True)
    (app_dir / "Tapesmith.exe").write_bytes(b"exe")
    (app_dir / "_internal" / "python311.dll").write_bytes(b"dll")
    out = tmp_path / "out"
    assert bp.main(["--zip-from", str(app_dir), "--dist", str(out)]) == 0
    zip_path = out / f"Tapesmith-portable-{bp._read_version()}.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert names == {"Tapesmith/Tapesmith.exe", "Tapesmith/_internal/python311.dll", "Installieren.cmd"}


def test_main_zip_from_ohne_exe(bp, tmp_path, capsys):
    assert bp.main(["--zip-from", str(tmp_path), "--dist", str(tmp_path / "out")]) == 1
    assert "Tapesmith.exe fehlt" in capsys.readouterr().err
