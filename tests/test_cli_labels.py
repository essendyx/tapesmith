import json

import pytest
from PIL import Image

from tapesmith import cli, paths


def job_rows(path):
    data = path.read_bytes()
    return int.from_bytes(data[38:40], "little")


def test_text_preview(tmp_path, capsys):
    out = tmp_path / "p.png"
    assert cli.main(["text", "pmx10 SSD-1 SN 274913", "--preview", str(out)]) == 0
    with Image.open(out) as img:
        assert img.height == 96 * 4
    assert "Vorschau" in capsys.readouterr().out


def test_text_print_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "SSD-1", "--length-mm", "20"]) == 0
    assert job_rows(job) == 160


def test_text_warning_on_stderr(tmp_path, capsys):
    assert cli.main(["text", "WWWWWWWWWW", "--max-mm", "10", "--preview", str(tmp_path / "w.png")]) == 0
    assert "Warnung:" in capsys.readouterr().err


def test_length_mm_and_max_mm_are_mutually_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["text", "x", "--length-mm", "10", "--max-mm", "20",
                  "--preview", str(tmp_path / "w.png")])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_text_with_more_than_3_lines_is_exit_1(tmp_path, capsys):
    assert cli.main(["text", "a", "b", "c", "d", "--preview", str(tmp_path / "w.png")]) == 1
    assert "höchstens 3 Zeilen" in capsys.readouterr().err


def test_font_missing_is_exit_1(tmp_path, capsys, monkeypatch):
    from tapesmith.render.fonts import FontMissing

    def boom(spec, profile):
        raise FontMissing("Schriftdatei fehlt: comic.ttf")

    monkeypatch.setattr(cli, "render_label", boom)
    assert cli.main(["text", "x", "--preview", str(tmp_path / "w.png")]) == 1
    assert "Fehler:" in capsys.readouterr().err


def test_template_list_and_show(capsys):
    assert cli.main(["template", "list"]) == 0
    out = capsys.readouterr().out
    assert "datentraeger" in out and "datentraeger-qr" in out
    assert cli.main(["template", "show", "datentraeger"]) == 0
    assert "sn" in capsys.readouterr().out


def test_template_show_redacts_secret_default(tmp_path, capsys):
    tpl = tmp_path / "geheim.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "geheim", "description": "",
        "fields": [{"id": "pw", "label": "Passwort", "type": "input", "secret": True, "default": "geheim123"}],
        "layout": {"lines": ["{pw}"]},
    }), encoding="utf-8")
    assert cli.main(["template", "show", str(tpl)]) == 0
    out = capsys.readouterr().out
    assert "REDACTED" in out or "•••" in out
    assert "geheim123" not in out


def test_template_print_preview_and_missing_field(tmp_path, capsys):
    out = tmp_path / "d.png"
    assert cli.main(["template", "print", "datentraeger", "--set", "sn=ata-SanDisk_SDSSDHP256G_112233274913",
                     "--preview", str(out)]) == 0
    assert out.is_file()
    assert cli.main(["template", "print", "datentraeger", "--preview", str(out)]) == 6
    assert "Seriennummer" in capsys.readouterr().err
    assert cli.main(["template", "print", "gibtsnicht"]) == 6
    assert cli.main(["template", "print", "datentraeger", "--set", "ohnegleich"]) == 1


def test_broken_user_template_does_not_disturb_list_or_print(tmp_path, capsys):
    from tapesmith.templates.store import user_dir
    (user_dir() / "kaputt.tapesmith.json").write_text("{nicht json", encoding="utf-8")

    assert cli.main(["template", "list"]) == 0
    listed = capsys.readouterr()
    assert "datentraeger" in listed.out
    assert "übersprungen" in listed.err

    out = tmp_path / "d.png"
    assert cli.main(["template", "print", "datentraeger", "--set", "sn=ata-SanDisk_SDSSDHP256G_112233274913",
                     "--preview", str(out)]) == 0
    assert out.is_file()


def test_set_on_counter_field_rejected_by_cli(tmp_path, capsys):
    tpl = tmp_path / "zaehler2.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "zaehler2", "description": "",
        "fields": [{"id": "nr", "label": "Nr", "type": "counter", "format": "ASN{:05d}"}],
        "layout": {"lines": ["{nr}"]},
    }), encoding="utf-8")
    assert cli.main(["template", "print", str(tpl), "--set", "nr=5",
                     "--preview", str(tmp_path / "z.png")]) == 6
    assert "nicht eingebbar" in capsys.readouterr().err


def test_wwn_input_is_exit_6_via_cli(tmp_path, capsys):
    assert cli.main(["template", "print", "datentraeger", "--set", "sn=wwn-0x5001b448b9a1c2d3",
                     "--preview", str(tmp_path / "d.png")]) == 6
    assert "lsblk" in capsys.readouterr().err


def test_hexlog_with_secret_template_warns(tmp_path, capsys):
    tpl = tmp_path / "geheim2.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "geheim2", "description": "",
        "fields": [{"id": "pw", "label": "Passwort", "type": "input", "secret": True, "required": True}],
        "layout": {"lines": ["{pw}"]},
    }), encoding="utf-8")
    out, log = tmp_path / "d.png", tmp_path / "hex.log"
    assert cli.main(["--hexlog", str(log), "template", "print", str(tpl), "--set", "pw=geheim",
                     "--preview", str(out)]) == 0
    assert "Hex-Log enthält Rasterdaten mit sensiblen Werten" in capsys.readouterr().err


def test_hexlog_without_secret_template_is_silent(tmp_path, capsys):
    out, log = tmp_path / "d.png", tmp_path / "hex.log"
    assert cli.main(["--hexlog", str(log), "template", "print", "datentraeger",
                     "--set", "sn=ata-SanDisk_SDSSDHP256G_112233274913",
                     "--preview", str(out)]) == 0
    assert "sensiblen" not in capsys.readouterr().err


def test_counter_commits_only_on_print(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    tpl = tmp_path / "zaehler.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "zaehler", "description": "",
        "fields": [{"id": "nr", "label": "Nr", "type": "counter", "format": "ASN{:05d}"}],
        "layout": {"lines": ["{nr}"]},
    }), encoding="utf-8")
    counters = paths.app_dir() / "counters.json"
    assert cli.main(["template", "print", str(tpl), "--preview", str(tmp_path / "z.png")]) == 0
    assert not counters.exists()
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "template", "print", str(tpl)]) == 0
    assert cli.main(["--transport", f"file:{job}", "template", "print", str(tpl)]) == 0
    assert json.loads(counters.read_text(encoding="utf-8")) == {"zaehler.nr": 2}


def test_template_schriftgroesse_show_und_print(tmp_path, capsys):
    assert cli.main(["template", "show", "raster-patchpanel"]) == 0
    out = capsys.readouterr().out
    assert "schriftgroesse" in out and "auto-feld" in out
    png = tmp_path / "r.png"
    assert cli.main(["template", "print", "raster-patchpanel", "--set", "belegung=A;Kabelbinder",
                     "--set", "schriftgroesse=9", "--preview", str(png)]) == 0
    assert png.is_file()
    assert "verkleinert" in capsys.readouterr().err
    assert cli.main(["template", "print", "raster-patchpanel", "--set", "belegung=A",
                     "--set", "schriftgroesse=riesig", "--preview", str(png)]) == 6
    assert "Schriftgröße" in capsys.readouterr().err
