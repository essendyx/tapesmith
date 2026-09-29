"""Tests für `configcode` (Konfiguration als Code)."""

import json

import pytest

from tapesmith import config, configcode, paths
from tapesmith.device.profile import CALIBRATION_KEYS
from tapesmith.templates.store import SUFFIX, user_dir


def _write_template(name: str = "eigen") -> None:
    data = {
        "schema_version": 2,
        "name": name,
        "fields": [{"id": "text", "type": "input", "label": "Text"}],
        "layout": {"kind": "text", "text": "{text}"},
    }
    (user_dir() / f"{name}{SUFFIX}").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_export_schreibt_dateien_und_manifest(tmp_path):
    config.save_config({"idle_timeout_s": 123})
    paths.calibration_path().write_text(json.dumps({"content_dots": 90}), encoding="utf-8")
    _write_template()

    target = tmp_path / "out"
    written = configcode.export_config(target)

    assert (target / "config.json").exists()
    assert (target / "calibration.json").exists()
    assert (target / "templates" / f"eigen{SUFFIX}").exists()
    manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "tapesmith-config"
    assert manifest["version"] == 1
    assert "config.json" in manifest["files"]
    assert manifest["files"]["config.json"]

    raw = (target / "config.json").read_text(encoding="utf-8")
    keys = list(json.loads(raw))
    assert keys == sorted(keys)
    assert len(written) >= 4


def test_export_secret_erfordert_strip(tmp_path):
    config.save_config({"ssh": {"hosts": [{"name": "a", "host": "h", "key": "k", "port": 22,
                                            "user": "root"}]},
                         "api_token": "geheim"})
    target = tmp_path / "out"
    with pytest.raises(ValueError, match="Secrets"):
        configcode.export_config(target)

    configcode.export_config(target, strip_secrets=True)
    data = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert "api_token" not in data


def test_import_dry_run_zeigt_neu_und_schreibt_nichts(tmp_path, monkeypatch):
    config.save_config({"idle_timeout_s": 111})
    export_dir = tmp_path / "export"
    configcode.export_config(export_dir)

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))

    plan = configcode.import_config(export_dir, dry_run=True)
    assert all(c.kind == "neu" for c in plan.changes)
    assert plan.backup_dir is None
    assert not paths.config_path().exists()

    plan2 = configcode.import_config(export_dir)
    assert any(c.path == "config.json" for c in plan2.changes)
    assert paths.config_path().exists()
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["idle_timeout_s"] == 111

    plan3 = configcode.import_config(export_dir)
    assert all(c.kind == "gleich" for c in plan3.changes)


def test_import_sichert_alten_stand(tmp_path, monkeypatch):
    config.save_config({"idle_timeout_s": 222})
    export_dir = tmp_path / "export"
    configcode.export_config(export_dir)

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))
    config.save_config({"idle_timeout_s": 999})  # alter Stand in home2

    plan = configcode.import_config(export_dir)
    assert plan.backup_dir is not None
    old_config = plan.backup_dir / "config.json"
    assert old_config.exists()
    old_data = json.loads(old_config.read_text(encoding="utf-8"))
    assert old_data["idle_timeout_s"] == 999


def test_import_ungueltige_calibration_nichts_geschrieben(tmp_path, monkeypatch):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "calibration.json").write_text(
        json.dumps({"content_dots": "nicht-numerisch"}), encoding="utf-8")
    manifest = {
        "format": configcode.FORMAT, "version": 1, "app_version": "0.0",
        "created": "2026-01-01T00:00:00",
        "files": {"calibration.json": configcode._sha256_bytes(
            (export_dir / "calibration.json").read_bytes())},
    }
    (export_dir / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))
    with pytest.raises(ValueError, match="calibration.json"):
        configcode.import_config(export_dir)
    assert not paths.calibration_path().exists()


def test_import_warnt_bei_geaenderter_pruefsumme(tmp_path, monkeypatch):
    config.save_config({"idle_timeout_s": 5})
    export_dir = tmp_path / "export"
    configcode.export_config(export_dir)

    # Datei nachträglich bearbeitet (aber weiterhin gültig).
    data = json.loads((export_dir / "config.json").read_text(encoding="utf-8"))
    data["idle_timeout_s"] = 6
    (export_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))
    plan = configcode.import_config(export_dir)
    assert any("Prüfsumme" in w for w in plan.warnings)
    assert paths.config_path().exists()


@pytest.mark.parametrize("rel", [
    "templates/../../evil.tapesmith.json",
    "templates/../evil.tapesmith.json",
    "templates/sub/evil.tapesmith.json",
    "..\\evil.json",
    "templates/evil\\..\\..\\x.tapesmith.json",
])
def test_check_safe_rel_weist_pfad_traversal_zurueck(rel):
    # MANIFEST.json stammt aus einem geteilten Git-Ordner und kann von Dritten bearbeitet
    # sein; ein Eintrag wie "templates/../../evil.tapesmith.json" würde ohne diese Prüfung zwei
    # Ebenen über templates.store.user_dir() schreiben (verifiziert:
    # Path("C:/tmp/userdir") / "../../evil.tapesmith.json" == WindowsPath("C:/tmp/evil.tapesmith.json")).
    with pytest.raises(ValueError):
        configcode._check_safe_rel(rel)


def test_import_manifest_mit_pfad_traversal_wird_abgewiesen(tmp_path, monkeypatch):
    export_dir = tmp_path / "export"
    (export_dir / "templates").mkdir(parents=True)
    evil = export_dir / "templates" / "evil.tapesmith.json"
    evil.write_text(json.dumps({
        "schema_version": 2, "name": "evil",
        "fields": [{"id": "text", "type": "input", "label": "Text"}],
        "layout": {"kind": "text", "text": "{text}"},
    }), encoding="utf-8")

    manifest = {
        "format": configcode.FORMAT, "version": 1, "app_version": "0.0",
        "created": "2026-01-01T00:00:00",
        # Der Schlüssel im Manifest ist manipuliert (Pfad-Traversal), auch wenn die Datei selbst
        # brav unter templates/ liegt: der ANGEGEBENE rel-Pfad zählt für das Ziel.
        "files": {"templates/../../evil.tapesmith.json": configcode._sha256_bytes(evil.read_bytes())},
    }
    (export_dir / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))
    with pytest.raises(ValueError):
        configcode.import_config(export_dir)

    # Nichts außerhalb des Vorlagenordners darf entstanden sein.
    assert not (tmp_path / "evil.tapesmith.json").exists()
    assert not (home2 / "evil.tapesmith.json").exists()


def test_calibration_keys_verwendet(tmp_path):
    # Nur zur Doku: CALIBRATION_KEYS wird von load_profile genutzt (indirekt getestet).
    assert "content_dots" in CALIBRATION_KEYS
