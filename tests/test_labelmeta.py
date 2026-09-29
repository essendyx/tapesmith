"""`labelmeta`: `JobMeta` für Text-, Vorlagen-, QR- und Bild-Labels an einer Stelle."""

import json

from tapesmith import labelmeta
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.render.compose import LabelSpec
from tapesmith.render.qrcontent import url_content, wifi_content
from tapesmith.templates.fill import build_spec
from tapesmith.templates.model import template_from_dict


def _template(*, secret: bool) -> dict:
    return {
        "schema_version": 1, "name": "wlan-test", "description": "",
        "fields": [
            {"id": "ssid", "label": "SSID", "type": "input"},
            {"id": "pw", "label": "Passwort", "type": "input", "secret": secret},
        ],
        "layout": {"lines": ["{ssid} {pw}"]},
    }


def test_text_meta_joins_non_empty_lines():
    meta = labelmeta.text_meta(LabelSpec(lines=("pmx10", "", "SN 1")), source="gui")
    assert meta.source == "gui"
    assert meta.kind == "text"
    assert meta.title == "pmx10 SN 1"
    assert meta.spec["lines"] == ["pmx10", "", "SN 1"]


def test_text_meta_qr_only_uses_qr_as_title():
    meta = labelmeta.text_meta(LabelSpec(qr="ABC"))
    assert meta.title == "ABC"


def test_template_meta_masks_secret_field():
    template = template_from_dict(_template(secret=True))
    values = {"ssid": "Gast", "pw": "geheim"}
    spec = build_spec(template, values)
    meta = labelmeta.template_meta(template, values, spec, source="gui")
    assert "geheim" not in meta.title
    assert "•••" in meta.title
    assert meta.values["pw"] == "•••"
    assert meta.sensitive is True
    assert meta.spec is None
    assert meta.source == "gui"


def test_template_meta_without_secret_field_keeps_spec():
    template = template_from_dict(_template(secret=False))
    values = {"ssid": "Gast", "pw": "123"}
    spec = build_spec(template, values)
    meta = labelmeta.template_meta(template, values, spec)
    assert meta.sensitive is False
    assert isinstance(meta.spec, dict)


def test_cli_base_template_meta_is_labelmeta_template_meta():
    assert cmd_base.template_meta is labelmeta.template_meta


def test_qr_meta_wifi_masks_password_everywhere():
    content = wifi_content("Gast", "geheim")
    meta = labelmeta.qr_meta(content, ["Gäste"], source="gui")
    dumped = json.dumps(meta.to_dict())
    assert "geheim" not in dumped
    assert meta.sensitive is True
    assert meta.spec is None


def test_qr_meta_url_with_spec_keeps_spec():
    content = url_content("l.lan/d7")
    meta = labelmeta.qr_meta(content, spec=LabelSpec(qr="https://l.lan/d7"))
    assert meta.spec is not None


def test_image_meta():
    meta = labelmeta.image_meta("logo.png", "gui")
    assert meta.kind == "image"
    assert meta.title == "logo.png"
