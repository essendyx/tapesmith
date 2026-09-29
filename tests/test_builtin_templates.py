import json
from datetime import datetime

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.render.compose import render_label
from tapesmith.templates.fill import CounterStore, build_spec, resolve_values
from tapesmith.templates.model import TemplateError
from tapesmith.templates.store import builtin_dir, find_template, list_templates, user_dir

NOW = datetime(2026, 9, 27)
BY_ID = "ata-SanDisk_SDSSDHP256G_112233274913"


def render(name, inputs, tmp_path):
    t = find_template(name)
    values = resolve_values(t, inputs, NOW, CounterStore(tmp_path / "c.json")).values
    return render_label(build_spec(t, values), load_profile())


def test_builtins_are_listed():
    names = [t.name for t in list_templates()]
    assert "datentraeger" in names and "datentraeger-qr" in names
    assert (builtin_dir() / "datentraeger.tapesmith.json").is_file()


def test_datentraeger_snapshot(tmp_path, snapshot):
    result = render("datentraeger", {"sn": BY_ID}, tmp_path)
    assert result.warnings == []
    snapshot("datentraeger", result.landscape)


def test_datentraeger_qr_snapshot(tmp_path, snapshot):
    result = render("datentraeger-qr", {"sn": BY_ID, "slot": "SSD-3"}, tmp_path)
    assert result.qr is not None and result.qr.decodes
    snapshot("datentraeger-qr", result.landscape)


def test_user_template_overrides_builtin(tmp_path):
    data = json.loads((builtin_dir() / "datentraeger.tapesmith.json").read_text(encoding="utf-8"))
    data["description"] = "eigene Version"
    (user_dir() / "datentraeger.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")
    assert find_template("datentraeger").description == "eigene Version"


def test_find_by_path_and_missing(tmp_path):
    path = tmp_path / "x.tapesmith.json"
    path.write_text((builtin_dir() / "datentraeger.tapesmith.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert find_template(str(path)).path == path
    with pytest.raises(TemplateError, match="nicht gefunden"):
        find_template("gibtsnicht")


def test_wwn_input_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match="lsblk"):
        render("datentraeger", {"sn": "wwn-0x5001b448b9a1c2d3"}, tmp_path)


def test_list_templates_skips_broken_user_file_and_warns(capsys):
    (user_dir() / "kaputt.tapesmith.json").write_text("{nicht json", encoding="utf-8")
    names = [t.name for t in list_templates()]
    assert "datentraeger" in names and "kaputt" not in names
    err = capsys.readouterr().err
    assert "Warnung: Vorlage kaputt.tapesmith.json übersprungen:" in err


def test_find_template_prefers_user_file_over_builtin_and_only_that_file(tmp_path):
    data = json.loads((builtin_dir() / "datentraeger.tapesmith.json").read_text(encoding="utf-8"))
    data["description"] = "eigene Version"
    (user_dir() / "datentraeger.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")
    t = find_template("datentraeger")
    assert t.description == "eigene Version"
    assert t.path == user_dir() / "datentraeger.tapesmith.json"


def test_find_template_path_precedence_only_for_full_suffix(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("{nicht json", encoding="utf-8")
    with pytest.raises(TemplateError, match="nicht gefunden"):
        find_template(str(path))
