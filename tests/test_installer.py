"""Tests für `tapesmith.install.installer` (Installation ohne Adminrechte, je Version eine
Python-Umgebung, Start immer über `pythonw.exe -m`).

Ausschließlich Fakes/Temp-Ordner: nie die echte Registry, das echte Startmenü, echtes
`%LOCALAPPDATA%`, echtes pip oder laufende Prozesse."""

from __future__ import annotations

import json

import pytest

from tapesmith import integration as intg
from tapesmith.install import installer, junction, layout, processes
from tapesmith.install.registry import FakeUninstallRegistry
from tapesmith.install.shortcuts import FakeShortcuts
from update_fakes import PYTHON, FakeVenvRun, make_frozen_version, make_version


def _install(**kw):
    kw.setdefault("python", PYTHON)
    kw.setdefault("run", FakeVenvRun())
    kw.setdefault("start", False)
    return installer.install(**kw)


def _start_menu(tmp_path, monkeypatch):
    menu = tmp_path / "start_menu"
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    return menu


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    """Keine echten Prozesse auflisten; Tests, die Prozesse brauchen, setzen es selbst."""
    monkeypatch.setattr(installer.processes, "processes_under", lambda root, **kw: [])


# ---------- Erstinstallation ----------

def test_install_erstinstallation_komplett(tmp_path, monkeypatch):
    menu = _start_menu(tmp_path, monkeypatch)
    root = tmp_path / "root"
    shortcuts = FakeShortcuts()
    uninstall_registry = FakeUninstallRegistry()
    registry = intg.FakeRegistry()
    run = FakeVenvRun()
    spawned = []

    def spawn(argv):
        spawned.append(list(argv))
        return 4242

    result = installer.install(version="0.2.0", root=root, python=PYTHON, run=run, shortcuts=shortcuts,
                               uninstall_registry=uninstall_registry, registry=registry, spawn=spawn,
                               source_stopper=lambda env: True)

    target = root / "versions" / "0.2.0"
    assert layout.is_complete_version(target)
    assert run.kinds() == ["venv", "pip", "selftest"]
    assert run.calls[0][0] == [str(PYTHON), "-m", "venv", str(target)]
    pip_argv = run.calls[1][0]
    assert pip_argv[0] == str(target / "Scripts" / "python.exe")
    assert "--only-binary=:all:" in pip_argv and pip_argv[-1] == "tapesmith==0.2.0"

    assert junction.read_junction(layout.current_link(root)).name == "0.2.0"
    state = layout.read_state(root)
    assert state.current == "0.2.0" and state.previous is None and state.versions == ["0.2.0"]
    assert state.installed_at and state.python == str(PYTHON)

    pythonw = layout.current_pythonw(root)
    icon = installer.current_icon(root)
    app_lnk = shortcuts.items[menu / "Tapesmith.lnk"]
    assert app_lnk["target"] == pythonw and app_lnk["arguments"] == "-m tapesmith.webui.browser"
    assert app_lnk["icon"] == icon and app_lnk["workdir"] == root
    uninstall_lnk = shortcuts.items[menu / "Tapesmith deinstallieren.lnk"]
    assert uninstall_lnk["target"] == pythonw and uninstall_lnk["arguments"] == "-m tapesmith uninstall"

    assert uninstall_registry.values["DisplayVersion"] == "0.2.0"
    assert "pythonw.exe\" -m tapesmith uninstall" in uninstall_registry.values["UninstallString"]
    assert isinstance(uninstall_registry.values["EstimatedSize"], int)

    run_value = registry.get(intg.RUN_KEY, intg.RUN_VALUE)
    assert run_value == f'{pythonw} -m tapesmith.gui.tray'
    for scheme in ("tapesmith", "p12label"):
        uri_cmd = registry.get(f"{intg.HKCU_CLASSES}\\{scheme}\\shell\\open\\command", "")
        assert uri_cmd == f'{pythonw} -m tapesmith.webui.browser --uri "%1"'
        assert registry.get(f"{intg.HKCU_CLASSES}\\{scheme}\\DefaultIcon", "") == str(icon)
    # nirgends eine eigene EXE
    assert not any("Tapesmith.exe" in v for values in registry.data.values() for v in values.values())

    assert spawned == [[str(pythonw), "-m", "tapesmith.gui.tray"]]
    assert result.root == root and result.version == "0.2.0"
    assert any("Installiert" in line for line in result.lines)
    assert any("%APPDATA%\\Tapesmith" in line for line in result.lines)


def test_install_ohne_autostart_entfernt_eigenen_run_wert(tmp_path):
    root = tmp_path / "root"
    registry = intg.FakeRegistry()
    registry.set(intg.RUN_KEY, intg.RUN_VALUE, '"C:\\alt\\pythonw.exe" -m tapesmith.gui.tray')
    _install(version="0.2.0", root=root, registry=registry, autostart=False, source_stopper=lambda env: True)
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) is None


def test_install_mit_eigenem_wheel_und_lock(tmp_path):
    root = tmp_path / "root"
    run = FakeVenvRun()
    wheel = tmp_path / "tapesmith-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"w")
    lock = tmp_path / "lock.txt"
    lock.write_text("tapesmith==0.2.0 \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    args = installer._parser().parse_args(["--wheel", str(wheel), "--find-links", str(tmp_path), "--no-index",
                                           "--lock", str(lock)])
    spec = installer.spec_from_args(args, "0.2.0")
    _install(version="0.2.0", root=root, spec=spec, run=run)
    pip_argv = run.calls[1][0]
    assert "--no-index" in pip_argv and pip_argv[pip_argv.index("--find-links") + 1] == str(tmp_path.resolve())
    assert pip_argv[pip_argv.index("-r") + 1] == str(lock) and "--require-hashes" in pip_argv
    assert pip_argv[-1] == str(wheel.resolve())


# ---------- Zweite Version, Wiederverwendung, Fehler ----------

def test_install_zweite_version_setzt_previous(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root)
    _install(version="0.2.1", root=root)
    state = layout.read_state(root)
    assert state.current == "0.2.1" and state.previous == "0.2.0"
    assert set(state.versions) == {"0.2.0", "0.2.1"}
    assert layout.is_complete_version(root / "versions" / "0.2.0")
    assert junction.read_junction(layout.current_link(root)).name == "0.2.1"


def test_install_gleiche_version_wird_wiederverwendet_ausser_mit_force(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root)
    marker = root / "versions" / "0.2.0" / "marker.txt"
    marker.write_text("bleibt", encoding="utf-8")
    run = FakeVenvRun()
    result = _install(version="0.2.0", root=root, run=run)
    assert run.calls == [] and marker.exists()
    assert any("schon bereitgestellt" in line for line in result.lines)
    run = FakeVenvRun()
    _install(version="0.2.0", root=root, run=run, force=True)
    assert run.kinds() == ["venv", "pip", "selftest"] and not marker.exists()
    assert layout.read_state(root).current == "0.2.0"


def test_install_scheitert_ohne_halbe_umgebung(tmp_path):
    root = tmp_path / "root"
    with pytest.raises(RuntimeError, match="pip install fehlgeschlagen"):
        _install(version="0.2.0", root=root, run=FakeVenvRun(pip_rc=1))
    assert not (root / "versions" / "0.2.0").exists()
    assert layout.read_state(root) is None
    with pytest.raises(RuntimeError, match="Selbsttest"):
        _install(version="0.2.0", root=root, run=FakeVenvRun(selftest_ok=False))
    assert not (root / "versions" / "0.2.0").exists()


def test_install_laufende_prozesse_loesen_stopper_aus(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root)
    fake_proc = processes.ProcessInfo(pid=123456, exe=str(root / "current" / "Scripts" / "pythonw.exe"))
    monkeypatch.setattr(installer.processes, "processes_under", lambda r, **kw: [fake_proc])
    calls = []

    def stopper(r):
        calls.append(r)
        return True

    _install(version="0.2.1", root=root, stopper=stopper)
    assert calls == [root]
    assert layout.read_state(root).current == "0.2.1"


def test_install_stopper_scheitert_bricht_ab_ohne_umschalten(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root)
    fake_proc = processes.ProcessInfo(pid=123456, exe=str(root / "current" / "Scripts" / "pythonw.exe"))
    monkeypatch.setattr(installer.processes, "processes_under", lambda r, **kw: [fake_proc])
    with pytest.raises(RuntimeError, match="läuft noch"):
        _install(version="0.2.1", root=root, stopper=lambda r: False)
    assert layout.read_state(root).current == "0.2.0"
    assert junction.read_junction(layout.current_link(root)).name == "0.2.0"


def test_install_schliesst_eigenen_prozess_und_starter_aus(tmp_path, monkeypatch):
    root = tmp_path / "root"
    seen = {}

    def under(r, **kw):
        seen["exclude"] = tuple(kw.get("exclude_pids") or ())
        return []

    monkeypatch.setattr(installer.processes, "processes_under", under)
    _install(version="0.2.0", root=root)
    assert seen["exclude"] == processes.own_pids()


def test_install_ohne_backends_beruehrt_nichts(tmp_path):
    root = tmp_path / "root"
    spawned = []
    result = _install(version="0.2.0", root=root, shortcuts=None, uninstall_registry=None, registry=None,
                      spawn=lambda a: spawned.append(a))
    assert spawned == []
    assert not any("Registry" in line or "Startmenü" in line or "Gestartet" in line for line in result.lines)
    assert layout.read_state(root).current == "0.2.0"


# ---------- Ablösung des früheren portablen Builds ----------

def test_install_loest_portable_installation_ab(tmp_path, monkeypatch):
    root = tmp_path / "root"
    make_frozen_version(root, "0.2.9")
    make_frozen_version(root, "0.3.0")
    installer.activate("0.2.9", root=root)
    installer.activate("0.3.0", root=root)
    (root / "versions" / "0.3.1.staging").mkdir()
    (root / "downloads").mkdir()
    fake_proc = processes.ProcessInfo(pid=4711, exe=str(root / "current" / layout.APP_EXE))
    stopped = []
    monkeypatch.setattr(installer.processes, "processes_under", lambda r, **kw: [] if stopped else [fake_proc])

    def stopper(r):
        stopped.append(r)
        return True

    registry = intg.FakeRegistry()
    registry.set(intg.RUN_KEY, intg.RUN_VALUE, f'"{root}\\current\\Tapesmith.exe" --tray')
    result = _install(version="0.3.0", root=root, stopper=stopper, registry=registry,
                      source_stopper=lambda env: pytest.fail("kein Quellcode-Start"))

    assert stopped == [root]  # gleiche Versionsnummer: erst beenden, dann ersetzen
    state = layout.read_state(root)
    assert state.current == "0.3.0" and state.versions == ["0.3.0"] and state.previous is None
    assert layout.is_complete_version(root / "versions" / "0.3.0")
    assert not (root / "versions" / "0.2.9").exists()
    assert not (root / "versions" / "0.3.1.staging").exists() and not (root / "downloads").exists()
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) == f"{layout.current_pythonw(root)} -m tapesmith.gui.tray"
    assert any("Portable Version abgelöst: 0.2.9" in line for line in result.lines)


def test_install_loest_quellcode_start_ab(tmp_path, app_home):
    root = tmp_path / "root"
    source_env = tmp_path / "src" / "tapesmith" / ".venv"
    registry = intg.FakeRegistry()
    registry.set(intg.RUN_KEY, intg.RUN_VALUE, f'"{source_env}\\Scripts\\pythonw.exe" -m tapesmith.gui.tray')
    stopped = []
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "config.json").write_text("{}", encoding="utf-8")
    result = _install(version="0.3.0", root=root, registry=registry,
                      source_stopper=lambda env: stopped.append(env) or True)
    assert stopped == [source_env]
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) == f"{layout.current_pythonw(root)} -m tapesmith.gui.tray"
    assert any("Quellcode-Umgebung abgelöst" in line for line in result.lines)
    assert (app_home / "config.json").read_text(encoding="utf-8") == "{}"  # Nutzerdaten unberührt


# ---------- prune / remove_version / activate / register_version ----------

def test_prune_behaelt_current_previous_entfernt_rest(tmp_path):
    root = tmp_path / "root"
    for version in ("0.1.0", "0.2.0", "0.2.1"):
        _install(version=version, root=root)
    state = layout.read_state(root)
    assert state.current == "0.2.1" and state.previous == "0.2.0"
    removed = installer.prune(1, root=root)
    assert removed == ["0.1.0"]
    assert not (root / "versions" / "0.1.0").exists()
    assert (root / "versions" / "0.2.0").exists() and (root / "versions" / "0.2.1").exists()
    assert set(layout.read_state(root).versions) == {"0.2.0", "0.2.1"}


def test_prune_entfernt_failed_zuerst(tmp_path):
    root = tmp_path / "root"
    for version in ("0.1.0", "0.1.5", "0.2.0"):
        _install(version=version, root=root)
    state = layout.read_state(root)
    state.failed = ["0.1.5"]
    layout.write_state(state, root)
    removed = installer.prune(1, root=root)
    assert removed == ["0.1.5"]
    assert (root / "versions" / "0.1.0").exists()
    assert not (root / "versions" / "0.1.5").exists()


def test_remove_version_aktive_version_wirft(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root)
    with pytest.raises(ValueError):
        installer.remove_version("0.2.0", root=root)


def test_remove_version_entfernt_ordner_und_aus_state(tmp_path):
    root = tmp_path / "root"
    _install(version="0.1.0", root=root)
    _install(version="0.2.0", root=root)
    installer.remove_version("0.1.0", root=root)
    assert not (root / "versions" / "0.1.0").exists()
    state = layout.read_state(root)
    assert "0.1.0" not in state.versions and state.previous is None


def test_activate_unbekannte_version_wirft(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        installer.activate("9.9.9", root=root)


def test_register_version_traegt_ein_ohne_umzuschalten(tmp_path):
    root = tmp_path / "root"
    _install(version="0.1.0", root=root)
    make_version(root, "0.2.0")
    state = installer.register_version("0.2.0", root)
    assert state.current == "0.1.0" and state.versions == ["0.1.0", "0.2.0"]


# ---------- status ----------

def test_status_dict_und_text(tmp_path):
    root = tmp_path / "root"
    assert installer.status_dict(root) == {"installed": False, "root": str(root)}
    _install(version="0.2.0", root=root)
    data = installer.status_dict(root)
    assert data["installed"] is True and data["current"] == "0.2.0" and data["kind"] == "python"
    assert data["python"] == str(PYTHON)
    text = "\n".join(installer.status_text(data))
    assert "Aktiv: 0.2.0" in text and "Art: python" in text


# ---------- main(): `python -m tapesmith install` ----------

def _install_log():
    from tapesmith import paths

    path = paths.log_dir() / "install.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_installer_main_erfolg_ohne_backends(tmp_path, capsys):
    root = tmp_path / "root"
    code = installer.main(["--root", str(root), "--python", str(PYTHON), "--no-shortcuts", "--no-registry",
                           "--no-start"], run=FakeVenvRun())
    assert code == 0
    log = _install_log()
    assert " OK " in log and "Installiert" in log
    assert layout.read_state(root).current == installer._app_version()
    out = capsys.readouterr().out
    assert "Lege Python-Umgebung an" in out and "Installiert" in out


def test_installer_main_status_json(tmp_path, capsys):
    root = tmp_path / "root"
    assert installer.main(["--root", str(root), "--status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"installed": False, "root": str(root)}


def test_installer_main_startet_tray_und_oeffnet_browser(tmp_path, monkeypatch):
    root = tmp_path / "root"
    spawned = []
    monkeypatch.setattr(installer.launch, "spawn_detached", lambda argv: spawned.append(list(argv)) or 1)
    code = installer.main(["--root", str(root), "--python", str(PYTHON), "--no-shortcuts", "--no-registry"],
                          run=FakeVenvRun())
    pythonw = str(layout.current_pythonw(root))
    assert code == 0
    assert spawned == [[pythonw, "-m", "tapesmith.gui.tray"], [pythonw, "-m", "tapesmith.webui.browser"]]
    assert "Web-Oberfläche im Standardbrowser" in _install_log()


@pytest.mark.parametrize("flag", ["--no-open", "--quiet"])
def test_installer_main_ohne_browser(tmp_path, monkeypatch, flag):
    root = tmp_path / "root"
    spawned = []
    monkeypatch.setattr(installer.launch, "spawn_detached", lambda argv: spawned.append(list(argv)) or 1)
    code = installer.main(["--root", str(root), "--python", str(PYTHON), "--no-shortcuts", "--no-registry", flag],
                          run=FakeVenvRun())
    assert code == 0
    assert spawned == [[str(layout.current_pythonw(root)), "-m", "tapesmith.gui.tray"]]


def test_installer_main_fehler_gibt_exit_1_und_protokolliert(tmp_path, capsys):
    root = tmp_path / "root"
    code = installer.main(["--root", str(root), "--python", str(PYTHON), "--no-shortcuts", "--no-registry",
                           "--no-start"], run=FakeVenvRun(venv_rc=1))
    assert code == 1
    log = _install_log()
    assert "FEHLER" in log and "fehlgeschlagen" in log
    assert "venv kaputt" in capsys.readouterr().err
    assert not (root / "versions" / "0.3.0").exists()


def test_installer_main_unerwarteter_fehler_wird_protokolliert(tmp_path, monkeypatch):
    def kaputt(*a, **kw):
        raise KeyError("unerwartet")

    monkeypatch.setattr(installer, "install", kaputt)
    code = installer.main(["--root", str(tmp_path / "root"), "--no-shortcuts", "--no-registry",
                           "--no-start", "--quiet"])
    assert code == 1
    log = _install_log()
    assert "Installation fehlgeschlagen" in log and "KeyError" in log


def test_installer_hat_kein_meldungsfenster():
    assert not hasattr(installer, "show_message")
    assert not hasattr(installer, "HELP_TEXT_TITLE")


def test_python_m_tapesmith_leitet_install_und_uninstall_weiter(monkeypatch):
    from tapesmith import __main__ as entry
    from tapesmith.install import uninstaller

    calls = []
    monkeypatch.setattr(installer, "main", lambda argv: calls.append(("install", argv)) or 0)
    monkeypatch.setattr(uninstaller, "main", lambda argv: calls.append(("uninstall", argv)) or 0)
    assert entry.main(["install", "--status"]) == 0
    assert entry.main(["uninstall", "--quiet"]) == 0
    assert calls == [("install", ["--status"]), ("uninstall", ["--quiet"])]
