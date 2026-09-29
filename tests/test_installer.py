"""Tests für `tapesmith.install.installer` (Installation ohne Adminrechte).

Ausschließlich Fakes/Temp-Ordner: nie die echte Registry, das echte Startmenü, echtes
`%LOCALAPPDATA%` oder laufende Prozesse."""

from __future__ import annotations

import pytest

from tapesmith import integration as intg
from tapesmith.install import installer, junction, layout, processes
from tapesmith.install.registry import FakeUninstallRegistry
from tapesmith.install.shortcuts import FakeShortcuts


def _make_source(tmp_path, name="source", content=b"exe-bytes"):
    src = tmp_path / name
    src.mkdir()
    (src / "Tapesmith.exe").write_bytes(content)
    return src


def _start_menu(tmp_path, monkeypatch):
    menu = tmp_path / "start_menu"
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    return menu


# ---------- 7. Quelle ohne Tapesmith.exe ----------

def test_install_ohne_exe_wirft_und_legt_nichts_an(tmp_path):
    source = tmp_path / "leer"
    source.mkdir()
    root = tmp_path / "root"

    with pytest.raises(ValueError, match="Tapesmith.exe"):
        installer.install(source, version="0.2.0", root=root)

    assert not root.exists()


# ---------- 2. Erstinstallation ----------

def test_install_erstinstallation_komplett(tmp_path, monkeypatch):
    menu = _start_menu(tmp_path, monkeypatch)
    root = tmp_path / "root"
    source = _make_source(tmp_path)
    shortcuts = FakeShortcuts()
    uninstall_registry = FakeUninstallRegistry()
    registry = intg.FakeRegistry()
    spawned = []

    def spawn(argv):
        spawned.append(list(argv))
        return 4242

    result = installer.install(source, version="0.2.0", root=root, shortcuts=shortcuts,
                               uninstall_registry=uninstall_registry, registry=registry, spawn=spawn)

    exe = root / "versions" / "0.2.0" / "Tapesmith.exe"
    assert exe.is_file()
    assert exe.read_bytes() == b"exe-bytes"

    target = junction.read_junction(layout.current_link(root))
    assert target is not None and target.name == "0.2.0"

    state = layout.read_state(root)
    assert state.current == "0.2.0"
    assert state.previous is None
    assert state.versions == ["0.2.0"]
    assert state.installed_at

    exe_current = layout.current_exe(root)
    app_lnk = shortcuts.items[menu / "Tapesmith.lnk"]
    assert app_lnk["target"] == exe_current
    uninstall_lnk = shortcuts.items[menu / "Tapesmith deinstallieren.lnk"]
    assert uninstall_lnk["target"] == exe_current
    assert uninstall_lnk["arguments"] == "--uninstall"

    assert uninstall_registry.values["DisplayVersion"] == "0.2.0"
    assert isinstance(uninstall_registry.values["NoModify"], int)
    assert isinstance(uninstall_registry.values["EstimatedSize"], int)

    exe_str = str(exe_current)
    run_value = registry.get(intg.RUN_KEY, intg.RUN_VALUE)
    assert run_value is not None
    assert exe_str in run_value and "--tray" in run_value

    uri_cmd = registry.get(f"{intg.HKCU_CLASSES}\\tapesmith\\shell\\open\\command", "")
    assert exe_str in uri_cmd

    assert spawned == [[exe_str, "--tray"]]

    assert result.root == root
    assert result.version == "0.2.0"
    assert any("Installiert" in line for line in result.lines)
    assert any("%APPDATA%\\Tapesmith" in line for line in result.lines)


# ---------- 3. Zweite Version ----------

def test_install_zweite_version_setzt_previous(tmp_path, monkeypatch):
    _start_menu(tmp_path, monkeypatch)
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1", b"v1"), version="0.2.0", root=root, start=False)

    installer.install(_make_source(tmp_path, "s2", b"v2"), version="0.2.1", root=root, start=False)

    state = layout.read_state(root)
    assert state.current == "0.2.1"
    assert state.previous == "0.2.0"
    assert set(state.versions) == {"0.2.0", "0.2.1"}
    assert (root / "versions" / "0.2.0" / "Tapesmith.exe").exists()
    target = junction.read_junction(layout.current_link(root))
    assert target.name == "0.2.1"


def test_install_laufende_prozesse_loesen_stopper_aus(tmp_path, monkeypatch):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1"), version="0.2.0", root=root, start=False)

    fake_proc = processes.ProcessInfo(pid=123456, exe=str(root / "current" / "Tapesmith.exe"))
    monkeypatch.setattr(installer.processes, "processes_under", lambda r, **kw: [fake_proc])
    calls = []

    def stopper(r):
        calls.append(r)
        return True

    installer.install(_make_source(tmp_path, "s2"), version="0.2.1", root=root, start=False, stopper=stopper)

    assert calls == [root]
    assert layout.read_state(root).current == "0.2.1"


def test_install_stopper_scheitert_bricht_ab_ohne_aenderung(tmp_path, monkeypatch):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1"), version="0.2.0", root=root, start=False)

    fake_proc = processes.ProcessInfo(pid=123456, exe=str(root / "current" / "Tapesmith.exe"))
    monkeypatch.setattr(installer.processes, "processes_under", lambda r, **kw: [fake_proc])

    with pytest.raises(RuntimeError):
        installer.install(_make_source(tmp_path, "s2"), version="0.2.1", root=root, start=False,
                          stopper=lambda r: False)

    assert layout.read_state(root).current == "0.2.0"
    assert not (root / "versions" / "0.2.1").exists()


# ---------- 4. Neuinstallation derselben Version aus dem installierten Ordner ----------

def test_install_reinstall_aus_installiertem_ordner_kopiert_nichts_und_ist_idempotent(tmp_path, monkeypatch):
    _start_menu(tmp_path, monkeypatch)
    root = tmp_path / "root"
    registry = intg.FakeRegistry()
    uninstall_registry = FakeUninstallRegistry()
    installer.install(_make_source(tmp_path, "s1"), version="0.2.0", root=root, registry=registry,
                      uninstall_registry=uninstall_registry, start=False)

    installed_dir = root / "versions" / "0.2.0"
    marker = installed_dir / "marker.txt"
    marker.write_text("nicht überschrieben", encoding="utf-8")

    result = installer.install(installed_dir, version="0.2.0", root=root, registry=registry,
                               uninstall_registry=uninstall_registry, start=False)

    assert marker.exists()  # nichts kopiert/gelöscht
    assert not any("Registry: Kontextmenü" in line for line in result.lines)  # zweites Mal: leer
    state = layout.read_state(root)
    assert state.current == "0.2.0"
    assert state.versions == ["0.2.0"]



def test_install_gleiche_version_aus_neuem_build_ersetzt_den_ordner(tmp_path, monkeypatch):
    # Ein neuer Build mit unveränderter Versionsnummer muss die installierten Dateien ersetzen.
    # Früher blieb die aktive Version unverändert: alle Neuinstallationen von 0.2.1 am 29.09.2026
    # waren wirkungslos, installiert blieb ein alter Stand.
    _start_menu(tmp_path, monkeypatch)
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "alt", b"alter-build"), version="0.2.1", root=root, start=False)
    installed_exe = root / "versions" / "0.2.1" / "Tapesmith.exe"
    assert installed_exe.read_bytes() == b"alter-build"

    installer.install(_make_source(tmp_path, "neu", b"neuer-build"), version="0.2.1", root=root, start=False)

    assert installed_exe.read_bytes() == b"neuer-build"
    assert layout.read_state(root).current == "0.2.1"

# ---------- 5. --no-registry --no-shortcuts --no-start ----------

def test_install_ohne_backends_beruehrt_nichts(tmp_path):
    root = tmp_path / "root"
    spawned = []

    result = installer.install(_make_source(tmp_path), version="0.2.0", root=root,
                               shortcuts=None, uninstall_registry=None, registry=None,
                               start=False, spawn=lambda a: spawned.append(a))

    assert spawned == []
    assert not any("Registry" in line or "Startmenü" in line or "Gestartet" in line for line in result.lines)
    state = layout.read_state(root)
    assert state.current == "0.2.0"


# ---------- 6. prune / remove_version ----------

def test_prune_behaelt_current_previous_entfernt_rest(tmp_path):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1"), version="0.1.0", root=root, start=False)
    installer.install(_make_source(tmp_path, "s2"), version="0.2.0", root=root, start=False)
    installer.install(_make_source(tmp_path, "s3"), version="0.2.1", root=root, start=False)

    state = layout.read_state(root)
    assert state.current == "0.2.1" and state.previous == "0.2.0"

    removed = installer.prune(1, root=root)

    assert removed == ["0.1.0"]
    assert not (root / "versions" / "0.1.0").exists()
    assert (root / "versions" / "0.2.0").exists()
    assert (root / "versions" / "0.2.1").exists()
    state = layout.read_state(root)
    assert set(state.versions) == {"0.2.0", "0.2.1"}


def test_prune_entfernt_failed_zuerst(tmp_path):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1"), version="0.1.0", root=root, start=False)
    installer.install(_make_source(tmp_path, "s2"), version="0.1.5", root=root, start=False)
    installer.install(_make_source(tmp_path, "s3"), version="0.2.0", root=root, start=False)
    state = layout.read_state(root)
    state.failed = ["0.1.5"]
    layout.write_state(state, root)

    removed = installer.prune(1, root=root)

    # failed wird immer entfernt, obwohl neuer als 0.1.0; 0.1.0 bleibt (neueste nicht-failed
    # Version, innerhalb des keep-Budgets von 1).
    assert removed == ["0.1.5"]
    assert (root / "versions" / "0.1.0").exists()
    assert not (root / "versions" / "0.1.5").exists()


def test_remove_version_aktive_version_wirft(tmp_path):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, start=False)

    with pytest.raises(ValueError):
        installer.remove_version("0.2.0", root=root)


def test_remove_version_entfernt_ordner_und_aus_state(tmp_path):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "s1"), version="0.1.0", root=root, start=False)
    installer.install(_make_source(tmp_path, "s2"), version="0.2.0", root=root, start=False)

    installer.remove_version("0.1.0", root=root)

    assert not (root / "versions" / "0.1.0").exists()
    assert "0.1.0" not in layout.read_state(root).versions


# ---------- activate ----------

def test_activate_unbekannte_version_wirft(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        installer.activate("9.9.9", root=root)


# ---------- 10. installer.main() (EXE-Weiche) ----------

def _install_log():
    from tapesmith import paths

    path = paths.log_dir() / "install.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_installer_main_erfolg_ohne_backends_nur_log(tmp_path):
    source = _make_source(tmp_path)
    root = tmp_path / "root"

    code = installer.main(["--root", str(root), "--no-shortcuts", "--no-registry", "--no-start"],
                          source_dir=source)

    assert code == 0
    log = _install_log()
    assert " OK " in log and "Installiert" in log
    assert layout.read_state(root).current == installer._app_version()


def test_installer_hat_kein_meldungsfenster():
    assert not hasattr(installer, "show_message")
    assert not hasattr(installer, "HELP_TEXT_TITLE")


def test_installer_main_startet_tray_und_oeffnet_browser(tmp_path, monkeypatch):
    source = _make_source(tmp_path)
    root = tmp_path / "root"
    spawned = []
    monkeypatch.setattr(installer.launch, "spawn_detached", lambda argv: spawned.append(list(argv)) or 1)

    code = installer.main(["--root", str(root), "--no-shortcuts", "--no-registry"], source_dir=source)

    exe = str(layout.current_exe(root))
    assert code == 0
    assert spawned == [[exe, "--tray"], [exe, "--app"]]
    assert "Web-Oberfläche im Standardbrowser" in _install_log()


@pytest.mark.parametrize("flag", ["--no-open", "--quiet"])
def test_installer_main_ohne_browser(tmp_path, monkeypatch, flag):
    source = _make_source(tmp_path)
    root = tmp_path / "root"
    spawned = []
    monkeypatch.setattr(installer.launch, "spawn_detached", lambda argv: spawned.append(list(argv)) or 1)

    code = installer.main(["--root", str(root), "--no-shortcuts", "--no-registry", flag], source_dir=source)

    assert code == 0
    assert spawned == [[str(layout.current_exe(root)), "--tray"]]


def test_installer_main_fehler_gibt_exit_1_und_protokolliert(tmp_path):
    leer = tmp_path / "leer"
    leer.mkdir()
    root = tmp_path / "root"

    code = installer.main(["--root", str(root), "--no-shortcuts", "--no-registry", "--no-start"],
                          source_dir=leer)

    assert code == 1
    log = _install_log()
    assert "FEHLER" in log and "fehlgeschlagen" in log
    assert not root.exists()


def test_installer_main_unerwarteter_fehler_wird_protokolliert(tmp_path, monkeypatch):
    def kaputt(*a, **kw):
        raise KeyError("unerwartet")

    monkeypatch.setattr(installer, "install", kaputt)
    code = installer.main(["--root", str(tmp_path / "root"), "--no-shortcuts", "--no-registry",
                           "--no-start", "--quiet"], source_dir=tmp_path)
    assert code == 1
    log = _install_log()
    assert "Installation fehlgeschlagen" in log and "KeyError" in log
