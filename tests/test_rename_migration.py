"""Umbenennung "P12 Label" -> Tapesmith (0.3.0): Rückfall der Umgebungsvariablen, einmalige
Datenübernahme, alte Vorlagen-Endung, URI-Alias und Ablösung der alten Installation.

Ausschließlich `tmp_path` und Fakes: nie das echte %APPDATA%, %LOCALAPPDATA%, Startmenü oder die
echte Registry, keine laufenden Prozesse."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime

import pytest

import tapesmith
from tapesmith import integration as intg
from tapesmith import migrate, modules
from tapesmith.install import installer, legacy
from tapesmith.install.registry import FakeUninstallRegistry
from tapesmith.install.shortcuts import FakeShortcuts
from tapesmith.templates import gallery, store
from tapesmith.transport import btports

FIXED_NOW = lambda: datetime(2026, 9, 29, 12, 0, 0)  # noqa: E731


# ---------- Umgebungsvariablen ----------

def test_alte_umgebungsvariable_gilt_als_rueckfall():
    env = {"P12LABEL_HOME": r"C:\alt", "P12LABEL_NO_DAEMON": "1", "TAPESMITH_NO_DAEMON": "0"}
    taken = tapesmith.apply_legacy_env(env)
    assert env["TAPESMITH_HOME"] == r"C:\alt"
    assert env["TAPESMITH_NO_DAEMON"] == "0"  # neuer Name hat Vorrang
    assert taken == ["TAPESMITH_HOME"]


def test_ohne_alte_variablen_passiert_nichts():
    env = {"PATH": "x"}
    assert tapesmith.apply_legacy_env(env) == []
    assert env == {"PATH": "x"}


# ---------- Datenübernahme ----------

def _legacy_data(appdata):
    old = appdata / "P12Label"
    (old / "templates").mkdir(parents=True)
    (old / "config.json").write_text('{"transport": "auto"}', encoding="utf-8")
    (old / "templates" / "meine.p12label.json").write_text('{"name": "meine"}', encoding="utf-8")
    (old / "history.sqlite3").write_bytes(b"sqlite")
    return old


def test_datenuebernahme_kopiert_und_laesst_original_stehen(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy_data(appdata)
    new = appdata / "Tapesmith"

    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True

    # Die Übernahme ergänzt die Modulliste; die kaputte Verlaufsdatei lässt im Zweifel alle Module an.
    migrated = json.loads((new / "config.json").read_text(encoding="utf-8"))
    assert migrated["transport"] == "auto"
    assert migrated["modules"]["enabled"] == list(modules.MODULE_IDS)
    assert (new / "history.sqlite3").read_bytes() == b"sqlite"
    assert (new / "templates" / "meine.tapesmith.json").is_file()
    assert not (new / "templates" / "meine.p12label.json").exists()
    # Original unverändert (kopieren, nie verschieben)
    assert (old / "templates" / "meine.p12label.json").is_file()
    assert (old / "config.json").is_file()
    log = (new / "logs" / "migration.log").read_text(encoding="utf-8")
    assert "2026-09-29 12:00:00" in log and "übernommen" in log
    assert not list(appdata.glob("Tapesmith.migrating-*"))


def test_datenuebernahme_nur_wenn_neuer_ordner_fehlt(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy_data(appdata)
    new = appdata / "Tapesmith"
    new.mkdir()
    (new / "config.json").write_text("{}", encoding="utf-8")

    assert migrate.migrate_legacy_data(old, new) is False
    assert (new / "config.json").read_text(encoding="utf-8") == "{}"
    assert not (new / "templates").exists()


def test_datenuebernahme_ohne_alten_ordner(tmp_path):
    assert migrate.migrate_legacy_data(tmp_path / "P12Label", tmp_path / "Tapesmith") is False
    assert not (tmp_path / "Tapesmith").exists()


def test_datenuebernahme_nur_einmal_pro_prozess(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "_done", False)
    appdata = tmp_path / "appdata"
    _legacy_data(appdata)
    assert migrate.migrate_once(appdata) is True
    (appdata / "Tapesmith").rename(appdata / "weg")
    assert migrate.migrate_once(appdata) is False
    assert not (appdata / "Tapesmith").exists()


def test_datenuebernahme_wettlauf_verwirft_eigene_kopie(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    old = _legacy_data(appdata)
    new = appdata / "Tapesmith"
    real_rename = migrate._rename_templates

    def other_process_wins(folder):
        new.mkdir()  # ein zweiter Prozess war schneller
        return real_rename(folder)

    monkeypatch.setattr(migrate, "_rename_templates", other_process_wins)
    assert migrate.migrate_legacy_data(old, new) is False
    assert list(new.iterdir()) == []
    assert not list(appdata.glob("Tapesmith.migrating-*"))


def test_app_dir_mit_home_uebernimmt_nichts(tmp_path, monkeypatch):
    from tapesmith import paths

    called = []
    monkeypatch.setattr(migrate, "migrate_once", lambda appdata: called.append(appdata))
    monkeypatch.setenv("TAPESMITH_HOME", str(tmp_path / "home"))
    assert paths.app_dir() == tmp_path / "home"
    assert called == []


# ---------- Vorlagen mit alter Endung ----------

def test_alte_vorlagen_endung_wird_gelesen_neue_gewinnt(app_home):
    tdir = store.user_dir()
    base = {"schema_version": 2, "fields": [], "layout": {"lines": ["x"]}}
    (tdir / "alt.p12label.json").write_text(json.dumps({**base, "name": "alt"}), encoding="utf-8")
    (tdir / "beide.p12label.json").write_text(
        json.dumps({**base, "name": "beide", "description": "alt"}), encoding="utf-8")
    (tdir / "beide.tapesmith.json").write_text(
        json.dumps({**base, "name": "beide", "description": "neu"}), encoding="utf-8")

    names = {t.name: t for t in store.list_templates()}
    assert "alt" in names
    assert names["beide"].description == "neu"
    assert store.find_template("alt").name == "alt"
    assert store.strip_suffix("x.p12label.json") == "x"
    assert store.is_template_file("x.tapesmith.json")


def test_altes_vorlagenpaket_laesst_sich_importieren(tmp_path):
    pkg = tmp_path / "alt.zip"
    data = {"schema_version": 2, "name": "paket", "fields": [],
            "layout": {"lines": ["x"]}}
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "p12label-paket", "version": 1,
                                                 "templates": ["paket"]}))
        zf.writestr("paket.p12label.json", json.dumps(data))
    imported = gallery.import_package(pkg, tmp_path / "ziel")
    assert imported == ["paket"]
    assert (tmp_path / "ziel" / "paket.tapesmith.json").is_file()


# ---------- URI-Schema ----------

def test_uri_alias_p12label_wird_verstanden():
    action = intg.parse_uri("p12label://print?template=gefriergut")
    assert action.kind == "template" and action.template == "gefriergut"
    assert intg.parse_uri("tapesmith://print?template=gefriergut").template == "gefriergut"
    with pytest.raises(ValueError):
        intg.parse_uri("anders://print?template=x")


def test_uri_registrierung_beider_schemata_und_entfernen():
    reg = intg.FakeRegistry()
    intg.install(reg, ("uri",), command=lambda *a: "cmd " + " ".join(a), icon="icon")
    for scheme in ("tapesmith", "p12label"):
        assert reg.get(rf"Software\Classes\{scheme}", intg.MARKER) == "1"
        assert reg.get(rf"Software\Classes\{scheme}\shell\open\command") == "cmd gui --uri"
    intg.uninstall(reg, ("uri",))
    assert not reg.exists(r"Software\Classes\tapesmith")
    assert not reg.exists(r"Software\Classes\p12label")


# ---------- Drucker ohne gespeicherte MAC ----------

def test_ohne_mac_der_einzige_ausgehende_port():
    one = lambda: [("b&1&0&001122334455_C00000000", "COM7"),  # noqa: E731
                   ("b&2&0&000000000000_C00000000", "COM8")]
    assert btports.find_outgoing_port(None, one) == "COM7"
    two = lambda: [("b&1&0&001122334455_C00000000", "COM7"),  # noqa: E731
                   ("b&1&0&00AABBCCDDEE_C00000000", "COM9")]
    assert btports.find_outgoing_port(None, two) is None


# ---------- Ablösung der alten Installation ----------

def _legacy_install(tmp_path):
    root = tmp_path / "Programs" / "P12Label"
    (root / "versions" / "0.2.1").mkdir(parents=True)
    (root / "versions" / "0.2.1" / "P12Label.exe").write_bytes(b"alt")
    (root / "install.json").write_text('{"schema": 1, "current": "0.2.1"}', encoding="utf-8")
    return root


def _legacy_registry():
    reg = intg.FakeRegistry()
    reg.set(intg.RUN_KEY, "P12Label", r'"C:\alt\P12Label.exe" --tray')
    reg.set(intg.RUN_KEY, "Fremd", "fremd.exe")
    for verb in intg.CONTEXT_VERBS:
        old = "P12Label." + verb.key.split(".", 1)[1]
        for target in verb.targets:
            path = rf"Software\Classes\{target}\shell\{old}"
            reg.set(path, "MUIVerb", "alt")
            reg.set(path, "P12LabelManaged", "1")
    reg.set(r"Software\Classes\p12label", "P12LabelManaged", "1")
    reg.set(r"Software\Classes\p12label\shell\open\command", "", r'"C:\alt\P12Label.exe" --uri')
    return reg


def test_installation_loest_alte_installation_ab(tmp_path, monkeypatch):
    menu_root = tmp_path / "start_menu"
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu_root / "Tapesmith"))
    legacy_menu = menu_root / "P12 Label"
    legacy_menu.mkdir(parents=True)
    shortcuts = FakeShortcuts()
    for name in legacy.LEGACY_SHORTCUTS:
        shortcuts.create(legacy_menu / name, tmp_path / "alt.exe")
    legacy_root = _legacy_install(tmp_path)
    user_data = tmp_path / "appdata" / "P12Label"
    user_data.mkdir(parents=True)
    (user_data / "config.json").write_text("{}", encoding="utf-8")
    old_uninstall = FakeUninstallRegistry()
    old_uninstall.set_str("DisplayName", "P12 Label")
    registry = _legacy_registry()
    source = tmp_path / "source"
    source.mkdir()
    (source / "Tapesmith.exe").write_bytes(b"neu")
    stopped = []

    result = installer.install(
        source, version="0.3.0", root=tmp_path / "Programs" / "Tapesmith", shortcuts=shortcuts,
        uninstall_registry=FakeUninstallRegistry(), registry=registry, start=False,
        legacy_root=legacy_root, legacy_menu_dir=legacy_menu,
        legacy_uninstall_registry=old_uninstall,
        legacy_stopper=lambda root: stopped.append(root) or True)

    assert stopped == [legacy_root]
    assert not legacy_root.exists()
    assert not legacy_menu.exists()
    assert old_uninstall.values == {}
    assert registry.get(intg.RUN_KEY, "P12Label") is None
    assert registry.get(intg.RUN_KEY, "Fremd") == "fremd.exe"
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) is not None
    assert not any("P12Label." in path for path in registry.data)
    uri = r"Software\Classes\p12label"
    assert registry.get(uri, "P12LabelManaged") is None
    assert registry.get(uri, intg.MARKER) == "1"
    assert "Tapesmith.exe" in registry.get(uri + r"\shell\open\command")
    # Nutzerdaten bleiben unberührt
    assert (user_data / "config.json").read_text(encoding="utf-8") == "{}"
    assert any("Alter Programmordner entfernt" in line for line in result.lines)


def test_alte_installation_bleibt_wenn_prozesse_nicht_enden(tmp_path):
    root = _legacy_install(tmp_path)
    lines = legacy.remove_legacy(root=root, stopper=lambda r: False)
    assert root.exists()
    assert any("Prozesse" in line for line in lines)


def test_alte_installation_nur_mit_passendem_ordner(tmp_path):
    other = tmp_path / "Anders"
    (other / "versions").mkdir(parents=True)
    lines = legacy.remove_legacy(root=other, stopper=lambda r: True)
    assert other.exists()
    assert any("unerwarteter Ordnername" in line for line in lines)


def test_ordner_ohne_installation_bleibt(tmp_path):
    root = tmp_path / "P12Label"
    root.mkdir()
    (root / "notiz.txt").write_text("x", encoding="utf-8")
    assert legacy.remove_legacy(root=root, stopper=lambda r: True) == []
    assert (root / "notiz.txt").is_file()


def test_gesperrter_ordner_wird_spaeter_geloescht(tmp_path, monkeypatch):
    root = _legacy_install(tmp_path)
    scheduled = []

    def locked(path):
        raise PermissionError("gesperrt")

    monkeypatch.setattr(legacy.shutil, "rmtree", locked)
    lines = legacy.remove_legacy(root=root, stopper=lambda r: True, schedule_delete=scheduled.append)
    assert scheduled == [root]
    assert any("wird entfernt" in line for line in lines)


def test_legacy_standardpfad_unter_pytest_gesperrt(monkeypatch):
    monkeypatch.delenv("TAPESMITH_LEGACY_INSTALL_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="TAPESMITH_LEGACY_INSTALL_ROOT"):
        legacy.default_root()
