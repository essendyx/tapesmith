"""Tests für `integration.py`: Explorer-Kontextmenü, URI-Schema, Autostart.

Ausschließlich `FakeRegistry`; die echte Registry wird nie angefasst (siehe `WinRegBackend`-Test)."""

import os
from pathlib import Path

import pytest

from tapesmith import integration as intg
from tapesmith import launch


def _fresh_backend() -> intg.FakeRegistry:
    return intg.FakeRegistry()


# ---------- install/uninstall/status: context + uri ----------

def test_install_context_und_uri_setzt_alle_ziele_und_marker():
    backend = _fresh_backend()
    lines = intg.install(backend)
    assert lines

    for verb in intg.CONTEXT_VERBS:
        for target in verb.targets:
            path = f"{intg.HKCU_CLASSES}\\{target}\\shell\\{verb.key}"
            assert backend.get(path, intg.MARKER) == "1"
            cmd = backend.get(f"{path}\\command", "")
            assert cmd is not None and "--open" in cmd and verb.action in cmd
            if verb.applies_to is not None:
                assert backend.get(path, "AppliesTo") == verb.applies_to
            else:
                assert backend.get(path, "AppliesTo") is None

    uri_path = f"{intg.HKCU_CLASSES}\\tapesmith"
    assert backend.get(uri_path, intg.MARKER) == "1"
    assert backend.get(uri_path, "URL Protocol") == ""
    assert "--uri" in backend.get(f"{uri_path}\\shell\\open\\command", "")


def test_install_appliesto_nur_bei_json_verb():
    backend = _fresh_backend()
    intg.install(backend)
    for verb in intg.CONTEXT_VERBS:
        path_first = f"{intg.HKCU_CLASSES}\\{verb.targets[0]}\\shell\\{verb.key}"
        has_applies = backend.get(path_first, "AppliesTo") is not None
        assert has_applies == (verb.applies_to is not None)


def test_install_ist_idempotent():
    backend = _fresh_backend()
    intg.install(backend)
    second = intg.install(backend)
    assert second == []


def test_install_dry_run_schreibt_nicht():
    backend = _fresh_backend()
    lines = intg.install(backend, dry_run=True)
    assert lines
    assert backend.data == {}


def test_status_installiert_veraltet_teilweise_nicht_installiert():
    backend = _fresh_backend()
    intg.install(backend)
    assert intg.status(backend)["context"] == "installiert"
    assert intg.status(backend)["uri"] == "installiert"

    other_command = lambda kind, *extra, **kw: launch.registry_command(  # noqa: E731
        kind, *extra, frozen=True, executable=r"C:\Anders\Tapesmith.exe")
    st = intg.status(backend, command=other_command)
    assert st["context"] == "veraltet"
    assert st["uri"] == "veraltet"

    verb = intg.CONTEXT_VERBS[0]
    path = f"{intg.HKCU_CLASSES}\\{verb.targets[0]}\\shell\\{verb.key}"
    backend.delete_tree(path)
    st2 = intg.status(backend)
    assert st2["context"] == "teilweise"

    empty = _fresh_backend()
    st3 = intg.status(empty)
    assert st3["context"] == "nicht installiert"
    assert st3["uri"] == "nicht installiert"
    assert st3["autostart"] == "nicht installiert"


def test_uninstall_entfernt_eigenes_laesst_fremdes():
    backend = _fresh_backend()
    intg.install(backend)

    fremd_path = r"SystemFileAssociations\.csv\shell\Fremd"
    backend.set(f"{intg.HKCU_CLASSES}\\{fremd_path}", "", "Fremdes Menü")
    backend.set(intg.RUN_KEY, "AndereApp", r"C:\andere\app.exe")

    lines = intg.uninstall(backend)
    assert lines

    for verb in intg.CONTEXT_VERBS:
        for target in verb.targets:
            path = f"{intg.HKCU_CLASSES}\\{target}\\shell\\{verb.key}"
            assert not backend.exists(path)
    assert not backend.exists(f"{intg.HKCU_CLASSES}\\tapesmith")

    assert backend.get(f"{intg.HKCU_CLASSES}\\{fremd_path}", "") == "Fremdes Menü"
    assert backend.get(intg.RUN_KEY, "AndereApp") == r"C:\andere\app.exe"


def test_uninstall_ohne_marker_loescht_tapesmith_nicht():
    backend = _fresh_backend()
    path = f"{intg.HKCU_CLASSES}\\tapesmith"
    backend.set(path, "", "Fremdes Protokoll")  # kein MARKER gesetzt
    intg.uninstall(backend, parts=("uri",))
    assert backend.exists(path)
    assert backend.get(path, "") == "Fremdes Protokoll"


def test_uninstall_dry_run_schreibt_nicht():
    backend = _fresh_backend()
    intg.install(backend)
    snapshot = {k: dict(v) for k, v in backend.data.items()}
    lines = intg.uninstall(backend, dry_run=True)
    assert lines
    assert backend.data == snapshot


# ---------- autostart ----------

def test_install_autostart_setzt_run_wert():
    backend = _fresh_backend()
    lines = intg.install(backend, parts=("autostart",))
    assert lines
    value = backend.get(intg.RUN_KEY, intg.RUN_VALUE)
    assert value == launch.command_line(launch.app_argv("tray"))


def test_uninstall_autostart_entfernt_run_wert():
    backend = _fresh_backend()
    intg.install(backend, parts=("autostart",))
    assert backend.get(intg.RUN_KEY, intg.RUN_VALUE) is not None
    lines = intg.uninstall(backend, parts=("autostart",))
    assert lines
    assert backend.get(intg.RUN_KEY, intg.RUN_VALUE) is None


def test_uninstall_autostart_laesst_fremden_wert_stehen():
    backend = _fresh_backend()
    backend.set(intg.RUN_KEY, intg.RUN_VALUE, r"C:\andere\app.exe --tray")
    lines = intg.uninstall(backend, parts=("autostart",))
    assert lines == []
    assert backend.get(intg.RUN_KEY, intg.RUN_VALUE) == r"C:\andere\app.exe --tray"


def test_plan_entries_autostart_argv_ueberschreibt_default():
    entries = intg.plan_entries(("autostart",), autostart_argv=[r"C:\x\current\Tapesmith.exe", "--tray"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry.path == intg.RUN_KEY
    assert entry.name == intg.RUN_VALUE
    assert entry.value == launch.command_line([r"C:\x\current\Tapesmith.exe", "--tray"])


def test_plan_entries_autostart_ohne_argv_bleibt_wie_bisher():
    entries = intg.plan_entries(("autostart",))
    assert entries[0].value == launch.command_line(launch.app_argv("tray"))


def test_install_autostart_argv_setzt_run_wert():
    backend = _fresh_backend()
    lines = intg.install(backend, parts=("autostart",), autostart_argv=[r"C:\x\current\Tapesmith.exe", "--tray"])
    assert lines
    value = backend.get(intg.RUN_KEY, intg.RUN_VALUE)
    assert value == launch.command_line([r"C:\x\current\Tapesmith.exe", "--tray"])


# ---------- unbekannter Teil ----------

def test_install_unbekannter_teil_wirft():
    with pytest.raises(ValueError):
        intg.install(_fresh_backend(), parts=("nonsens",))


def test_uninstall_unbekannter_teil_wirft():
    with pytest.raises(ValueError):
        intg.uninstall(_fresh_backend(), parts=("nonsens",))


# ---------- WinRegBackend-Sicherheitsnetz ----------

def test_winreg_backend_set_blockiert_in_tests():
    backend = intg.WinRegBackend()
    with pytest.raises(RuntimeError, match="Registry-Schreibzugriff"):
        backend.set(r"Software\Classes\tapesmith", "", "x")


def test_winreg_backend_get_ist_in_tests_erlaubt():
    backend = intg.WinRegBackend()
    assert backend.get(r"Software\Classes\tapesmith-nicht-vorhanden-xyz") is None


def test_winreg_backend_delete_blockiert_in_tests():
    backend = intg.WinRegBackend()
    with pytest.raises(RuntimeError, match="Registry-Schreibzugriff"):
        backend.delete_value(r"Software\Classes\tapesmith", "")
    with pytest.raises(RuntimeError, match="Registry-Schreibzugriff"):
        backend.delete_tree(r"Software\Classes\tapesmith")


def test_winreg_backend_no_registry_env_blockiert_auch_ausserhalb_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("TAPESMITH_NO_REGISTRY", "1")
    backend = intg.WinRegBackend()
    with pytest.raises(RuntimeError, match="Registry-Schreibzugriff"):
        backend.set(r"Software\Classes\tapesmith", "", "x")


# ---------- parse_uri ----------

def test_parse_uri_print_mit_werten():
    action = intg.parse_uri("tapesmith://print?template=datentraeger&host=pmx10&sn=274913")
    assert action.kind == "template"
    assert action.template == "datentraeger"
    assert action.values == {"host": "pmx10", "sn": "274913"}
    assert action.source == "uri"


def test_parse_uri_ohne_doppelslash():
    action = intg.parse_uri("tapesmith:template?template=band")
    assert action.template == "band"


def test_parse_uri_text_mehrere_zeilen():
    action = intg.parse_uri("tapesmith:text?l=A&l=B")
    assert action.kind == "text"
    assert action.lines == ("A", "B")


def test_parse_uri_qr_mit_text():
    action = intg.parse_uri("tapesmith://qr?data=HTTP://L.LAN/D7&text=Box")
    assert action.kind == "qr"
    assert action.qr == "HTTP://L.LAN/D7"
    assert action.lines == ("Box",)


def test_parse_uri_gross_klein_schema_egal():
    action = intg.parse_uri("Tapesmith://template?template=band")
    assert action.template == "band"


def test_parse_uri_mehrfachwerte_letzter_gewinnt():
    action = intg.parse_uri("tapesmith://print?template=a&template=b")
    assert action.template == "b"


def test_parse_uri_anderes_schema_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri("http://example.com")


def test_parse_uri_keine_vorlage_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri("tapesmith://print?host=pmx10")


def test_parse_uri_vorlagenname_mit_pfadtrenner_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri(r"tapesmith://print?template=..\..\etwas")


def test_parse_uri_vier_textzeilen_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri("tapesmith:text?l=A&l=B&l=C&l=D")


def test_parse_uri_zu_langer_wert_wirft():
    lang = "x" * (intg.MAX_VALUE_LEN + 1)
    with pytest.raises(ValueError):
        intg.parse_uri(f"tapesmith://print?template=t&note={lang}")


def test_parse_uri_21_parameter_wirft():
    params = "&".join(f"k{i}=v" for i in range(21))
    with pytest.raises(ValueError):
        intg.parse_uri(f"tapesmith://print?template=t&{params}")


def test_parse_uri_unbekannte_aktion_wirft():
    with pytest.raises(ValueError, match="delete"):
        intg.parse_uri("tapesmith://delete?x=1")


def test_parse_uri_qr_ohne_data_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri("tapesmith://qr?text=Box")


def test_parse_uri_qr_zu_viele_texte_wirft():
    with pytest.raises(ValueError):
        intg.parse_uri("tapesmith://qr?data=x&text=A&text=B&text=C")


# ---------- read_lines_file / file_action ----------

def test_read_lines_file_utf8_bom(tmp_path):
    p = tmp_path / "zeilen.txt"
    p.write_bytes("Erste\nZweite\n\nDritte\n".encode("utf-8-sig"))
    assert intg.read_lines_file(p) == ("Erste", "Zweite", "Dritte")


def test_read_lines_file_cp1252(tmp_path):
    p = tmp_path / "zeilen.txt"
    p.write_bytes("Straße\nHöhe\n".encode("cp1252"))
    assert intg.read_lines_file(p) == ("Straße", "Höhe")


def test_file_action_batch_vorhandene_datei(tmp_path):
    p = tmp_path / "liste.csv"
    p.write_text("a,b\n", encoding="utf-8")
    action = intg.file_action("batch", p)
    assert action.kind == "batch"
    assert action.path == p
    assert action.source == "kontextmenü"


def test_file_action_batch_fehlende_datei_wirft(tmp_path):
    with pytest.raises(ValueError):
        intg.file_action("batch", tmp_path / "fehlt.csv")


def test_file_action_lines_liest_datei(tmp_path):
    p = tmp_path / "zeilen.txt"
    p.write_text("Eins\nZwei\n", encoding="utf-8")
    action = intg.file_action("lines", p)
    assert action.kind == "lines"
    assert action.lines == ("Eins", "Zwei")


def test_file_action_template_falsche_endung_wirft(tmp_path):
    p = tmp_path / "vorlage.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        intg.file_action("template", p)


def test_file_action_template_richtige_endung(tmp_path):
    p = tmp_path / "vorlage.tapesmith.json"
    p.write_text("{}", encoding="utf-8")
    action = intg.file_action("template", p)
    assert action.kind == "template"
    assert action.path == p


def test_file_action_folder_name(tmp_path):
    ordner = tmp_path / "Mein Ordner"
    ordner.mkdir()
    action = intg.file_action("folder-name", ordner)
    assert action.kind == "lines"
    assert action.lines == ("Mein Ordner",)


def test_file_action_folder_qr_unc_ueber_resolver(tmp_path):
    ordner = tmp_path / "Doku" / "Unterordner"
    ordner.mkdir(parents=True)
    drive = ordner.drive

    def resolver(d):
        return r"\\nas\share" if d.upper() == drive.upper() else None

    action = intg.file_action("folder-qr", ordner, resolver=resolver)
    assert action.kind == "qr"
    assert action.qr == r"\\nas\share" + str(ordner)[len(drive):]
    assert action.note == ""


def test_file_action_folder_qr_lokal_ohne_resolver_setzt_hinweis(tmp_path):
    ordner = tmp_path / "Lokal"
    ordner.mkdir()

    def resolver(d):
        return None

    action = intg.file_action("folder-qr", ordner, resolver=resolver)
    assert action.qr == str(ordner)
    assert "Lokaler Pfad" in action.note


def test_file_action_unbekannt_wirft(tmp_path):
    with pytest.raises(ValueError):
        intg.file_action("unbekannt", tmp_path)


# ---------- to_unc ----------

def test_to_unc_bereits_unc_bleibt():
    unc, is_unc = intg.to_unc(Path(r"\\nas\share\Ordner"))
    assert is_unc is True
    assert unc == r"\\nas\share\Ordner"


def test_to_unc_lokal_ohne_resolver_bleibt_lokal():
    path = Path(r"C:\Nutzer\Doku")
    unc, is_unc = intg.to_unc(path, resolver=lambda d: None)
    assert is_unc is False
    assert unc == str(path)


def test_to_unc_mit_resolver():
    path = Path(r"Z:\Doku\Ordner")
    unc, is_unc = intg.to_unc(path, resolver=lambda d: r"\\nas\share" if d.upper() == "Z:" else None)
    assert is_unc is True
    assert unc == r"\\nas\share\Doku\Ordner"
