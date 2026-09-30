"""CLI-Integration: `template lint`, `template print` (v2), invertierte Codes in `text`/`print`,
`reprint` einer Dokument-Vorlage, `template show` Art."""

import json

from tapesmith import cli
from tapesmith.templates.store import user_dir


def _write(data: dict, name: str | None = None) -> None:
    filename = f"{name or data['name']}.tapesmith.json"
    (user_dir() / filename).write_text(json.dumps(data), encoding="utf-8")


# 14. template lint --------------------------------------------------------------------------

def test_lint_all_builtin_is_exit_0(capsys):
    assert cli.main(["template", "lint"]) == 0
    assert "Vorlagen geprüft" in capsys.readouterr().out


def test_lint_dir_with_broken_template_is_exit_6_with_error_line(tmp_path, capsys):
    good = {"schema_version": 2, "name": "gut", "description": "", "fields": [],
           "layout": {"lines": ["x"]}, "sample": {}}
    bad = {"schema_version": 2, "name": "schlecht", "description": "",
          "fields": [{"id": "host", "label": "Host", "type": "input", "required": True}],
          "layout": {"lines": ["{host}"], "fixed_length_mm": 1}}
    (tmp_path / "gut.tapesmith.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "schlecht.tapesmith.json").write_text(json.dumps(bad), encoding="utf-8")

    assert cli.main(["template", "lint", "--dir", str(tmp_path)]) == 6
    out = capsys.readouterr().out
    assert any("error" in line for line in out.splitlines())


def test_lint_strict_turns_warning_only_into_exit_6(tmp_path, capsys):
    tpl = {"schema_version": 2, "name": "nurwarnung", "description": "",
          "fields": [{"id": "host", "label": "Host", "type": "input", "default": "x"}],
          "layout": {"lines": ["{host}"]}}
    (tmp_path / "nurwarnung.tapesmith.json").write_text(json.dumps(tpl), encoding="utf-8")

    assert cli.main(["template", "lint", "--dir", str(tmp_path)]) == 0
    capsys.readouterr()
    assert cli.main(["template", "lint", "--dir", str(tmp_path), "--strict"]) == 6


def test_lint_json_is_valid_json_list(capsys):
    assert cli.main(["template", "lint", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    if data:
        assert set(data[0]) == {"template", "level", "data", "message"}


# 15. template print einer Dokument-Vorlage --------------------------------------------------

def test_template_print_document_kind_writes_preview(tmp_path):
    _write({
        "schema_version": 2, "name": "doc-print-test", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "document": {"objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
        ]},
    })
    out = tmp_path / "v.png"
    assert cli.main(["template", "print", "doc-print-test", "--preview", str(out)]) == 0
    assert out.is_file()


# 16. Band-Rückfrage ----------------------------------------------------------------

def test_template_print_tape_mismatch_needs_confirmation(tmp_path, capsys, monkeypatch):
    _write({
        "schema_version": 2, "name": "tape-mismatch", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "layout": {"lines": ["{host}"]},
        "tapes": ["material:kunststoff"],
    })
    assert cli.main(["tape", "set", "schwarz-weiss-papier"]) == 0
    capsys.readouterr()

    # Eine Vorschau wird nie von der Band-Rückfrage blockiert ...
    assert cli.main(["template", "print", "tape-mismatch",
                     "--preview", str(tmp_path / "v.png")]) == 0
    assert (tmp_path / "v.png").is_file()
    capsys.readouterr()

    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    # ... ein echter Druck ohne --yes und ohne Konsole aber weiterhin
    assert cli.main(["--transport", f"file:{job}", "template", "print", "tape-mismatch"]) == 1
    assert "mit --yes bestätigen" in capsys.readouterr().err
    assert not job.exists()
    assert cli.main(["--transport", f"file:{job}", "template", "print", "tape-mismatch", "--yes"]) == 0
    assert job.exists()


# 17. "Gekürzt: …" -------------------------------------------------------------------------

def test_template_print_reports_shortened_fields(tmp_path, capsys):
    _write({
        "schema_version": 2, "name": "kurz-test", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input", "default": ""},
            {"id": "sn", "label": "SN", "type": "input", "default": ""},
        ],
        "layout": {"lines": ["{host}", "{sn}"]},
        "target": "m2-2280",
        "shorten": [
            {"field": "host", "rule": "strip_domain"},
            {"field": "sn", "rule": "last", "n": 6},
        ],
    })
    out = tmp_path / "v.png"
    assert cli.main(["template", "print", "kurz-test", "--set", "host=pmx10.home.lan",
                     "--set", "sn=S4EWNX0R123456", "--preview", str(out)]) == 0
    assert "Gekürzt:" in capsys.readouterr().err


# 18. Dunkles Band in `tapesmith text --qr` ---------------------------------------------------------

def test_text_qr_inverts_on_dark_tape(tmp_path):
    light = tmp_path / "light.png"
    dark = tmp_path / "dark.png"
    no_qr_light = tmp_path / "nolight.png"
    no_qr_dark = tmp_path / "nodark.png"

    assert cli.main(["tape", "set", "schwarz-weiss"]) == 0
    assert cli.main(["text", "X", "--qr", "1234", "--preview", str(light)]) == 0
    assert cli.main(["text", "X", "--preview", str(no_qr_light)]) == 0

    assert cli.main(["tape", "set", "weiss-schwarz"]) == 0
    assert cli.main(["text", "X", "--qr", "1234", "--preview", str(dark)]) == 0
    assert cli.main(["text", "X", "--preview", str(no_qr_dark)]) == 0

    assert light.read_bytes() != dark.read_bytes()
    assert no_qr_light.read_bytes() == no_qr_dark.read_bytes()


# 19. Nachdruck einer Dokument-Vorlage -----------------------------------------------------

def test_reprint_last_prints_document_template_again(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    _write({
        "schema_version": 2, "name": "doc-reprint-test", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "document": {"objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
        ]},
    })
    job1 = tmp_path / "job1.bin"
    assert cli.main(["--transport", f"file:{job1}", "template", "print", "doc-reprint-test"]) == 0

    job2 = tmp_path / "job2.bin"
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last"]) == 0
    assert job2.exists()


# 20. template show zeigt Art ---------------------------------------------------------------

def test_template_show_displays_kind_document(capsys):
    _write({
        "schema_version": 2, "name": "doc-show-test", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "document": {"objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
        ]},
    })
    assert cli.main(["template", "show", "doc-show-test"]) == 0
    out = capsys.readouterr().out
    assert "Art: document" in out


# 21. Dunkles Band in `tapesmith print --qr` --------------------------------------------------------

def test_print_qr_inverts_on_dark_tape(tmp_path):
    light = tmp_path / "light.png"
    dark = tmp_path / "dark.png"
    no_qr_light = tmp_path / "nolight.png"
    no_qr_dark = tmp_path / "nodark.png"

    assert cli.main(["tape", "set", "schwarz-weiss"]) == 0
    assert cli.main(["print", "pmx10", "--qr", "112233274913", "--preview", str(light)]) == 0
    assert cli.main(["print", "pmx10", "--preview", str(no_qr_light)]) == 0

    assert cli.main(["tape", "set", "weiss-schwarz"]) == 0
    assert cli.main(["print", "pmx10", "--qr", "112233274913", "--preview", str(dark)]) == 0
    assert cli.main(["print", "pmx10", "--preview", str(no_qr_dark)]) == 0

    assert light.read_bytes() != dark.read_bytes()
    assert no_qr_light.read_bytes() == no_qr_dark.read_bytes()
