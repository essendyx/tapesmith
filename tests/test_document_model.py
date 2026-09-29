"""Tests für das Objektmodell: Validierung, JSON, Hilfsfunktionen."""

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from tapesmith.document.model import (
    DOC_VERSION,
    KIND_CLASSES,
    KIND_NAMES,
    MAX_IMAGE_SIDE,
    OBJECT_KINDS,
    Code128Object,
    DataMatrixObject,
    DocumentError,
    IconObject,
    ImageObject,
    LabelDocument,
    LineObject,
    QrObject,
    RectObject,
    TextObject,
    bbox,
    decode_png,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    encode_png,
    extent,
    find_object,
    map_texts,
    new_id,
    object_from_dict,
    object_to_dict,
    prepare_embedded_image,
    replace_object,
    texts,
    with_objects,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

CLASSES = [
    ("text", TextObject),
    ("qr", QrObject),
    ("code128", Code128Object),
    ("datamatrix", DataMatrixObject),
    ("icon", IconObject),
    ("line", LineObject),
    ("rect", RectObject),
    ("image", ImageObject),
]


def _png():
    return prepare_embedded_image(Image.new("L", (20, 10), 0))


def _full_doc():
    objs = (
        TextObject(id="text1", x=8, y=4, w=200, h=40, text="{host}\nZeile 2", font="sans-bold",
                   size=20, align="center", valign="top", invert=True, vertical=True,
                   rotation=90, mirror=True, locked=True, visible=False, name="Titel"),
        QrObject(id="qr1", x=-5, y=0, w=88, h=88, data="{sn}", error="h", module=3),
        Code128Object(id="code128-1", x=0, y=0, w=100, h=30, data="ABC", module=3,
                      show_text=False, text_size=12, rotation=180),
        DataMatrixObject(id="dm1", x=0, y=0, w=40, h=40, data="X", module=4),
        IconObject(id="icon1", x=0, y=0, w=20, h=20, icon="{symbol}"),
        LineObject(id="line1", x=0, y=0, w=50, h=5, direction="down", thickness=3, dash=4,
                   arrow_start=True, arrow_end=True),
        RectObject(id="rect1", x=0, y=0, w=50, h=20, thickness=0, radius=5, fill="stripes",
                   stripe=8),
        ImageObject(id="img1", x=0, y=0, w=20, h=10, png=_png(), threshold=100, dither="floyd",
                    invert=True, keep_aspect=False, rotation=270),
    )
    return LabelDocument(objects=objs, length_mode="fixed", length_mm=40, margin_mm=2.5,
                         mirror=True, rotate180=True)


# 1 ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind,cls", CLASSES)
def test_objektart_mit_standardwerten(kind, cls):
    extra = {"png": _png()} if cls is ImageObject else {}
    obj = cls(id="t1", x=0, y=0, w=10, h=10, **extra)
    assert obj.kind == kind
    assert KIND_CLASSES[kind] is cls
    assert kind in OBJECT_KINDS and kind in KIND_NAMES


def test_konstanten():
    assert DOC_VERSION == 1
    assert set(KIND_CLASSES) == set(OBJECT_KINDS)


# 2 ---------------------------------------------------------------------------

def test_rundlauf_dict_und_json():
    doc = _full_doc()
    assert {o.kind for o in doc.objects} == set(OBJECT_KINDS)
    data = document_to_dict(doc)
    assert data["version"] == 1
    assert document_from_dict(data) == doc
    assert document_from_json(document_to_json(doc)) == doc


def test_json_format_mit_umlauten_und_einrueckung():
    doc = LabelDocument(objects=(TextObject(id="t1", x=0, y=0, w=5, h=5, text="Grüße"),))
    js = document_to_json(doc)
    assert "Grüße" in js
    assert '\n  "' in js


def test_beispiel_json_aus_der_spec():
    doc = document_from_dict({
        "version": 1, "length_mode": "fixed", "length_mm": 40.0,
        "objects": [
            {"kind": "text", "id": "text1", "x": 8, "y": 4, "w": 200, "h": 40, "text": "{host}",
             "font": "sans-bold"},
            {"kind": "qr", "id": "qr1", "x": 220, "y": 0, "w": 88, "h": 88, "data": "{sn}"}]})
    assert doc.length_mm == 40.0
    assert isinstance(doc.objects[1], QrObject)


def test_laengen_int_werden_float():
    doc = document_from_dict({"objects": [], "length_mode": "max", "length_mm": 30, "margin_mm": 2})
    assert isinstance(doc.length_mm, float) and doc.length_mm == 30.0
    assert isinstance(doc.margin_mm, float)


# 3 ---------------------------------------------------------------------------

def test_object_to_dict_nur_nicht_standard():
    assert object_to_dict(TextObject(id="t1", x=1, y=2, w=3, h=4)) == {
        "kind": "text", "id": "t1", "x": 1, "y": 2, "w": 3, "h": 4}


def test_object_to_dict_reihenfolge_der_felder():
    d = object_to_dict(TextObject(id="t1", x=1, y=2, w=3, h=4, rotation=90, text="a", invert=True))
    assert list(d) == ["kind", "id", "x", "y", "w", "h", "rotation", "text", "invert"]


def test_document_to_dict_minimal():
    assert document_to_dict(LabelDocument()) == {"version": 1, "objects": []}


def test_object_from_dict():
    obj = object_from_dict({"kind": "line", "id": "l1", "x": 0, "y": 0, "w": 9, "h": 2, "dash": 3})
    assert obj == LineObject(id="l1", x=0, y=0, w=9, h=2, dash=3)


# 4 ---------------------------------------------------------------------------

def _t(**kw):
    base = dict(id="t1", x=0, y=0, w=10, h=10)
    base.update(kw)
    return base


@pytest.mark.parametrize("factory,match", [
    (lambda: TextObject(**_t(id="1abc")), "Objekt-ID '1abc' ungültig"),
    (lambda: TextObject(**_t(w=0)), "mindestens 1 Punkt"),
    (lambda: TextObject(**_t(rotation=45)), "Drehung"),
    (lambda: TextObject(**_t(x=True)), "ganze Zahl"),
    (lambda: TextObject(**_t(mirror=1)), "mirror"),
    (lambda: TextObject(**_t(font="comic")), "Schrift 'comic'"),
    (lambda: TextObject(**_t(text="a\nb\nc\nd")), "3 Zeilen"),
    (lambda: TextObject(**_t(size=5)), "Schriftgröße"),
    (lambda: TextObject(**_t(align="justify")), "Ausrichtung"),
    (lambda: TextObject(**_t(valign="center")), "Ausrichtung"),
    (lambda: QrObject(**_t(error="x")), "Fehlerkorrektur"),
    (lambda: QrObject(**_t(module=21)), "Modul"),
    (lambda: Code128Object(**_t(module=1)), "mindestens 2 Punkte"),
    (lambda: Code128Object(**_t(text_size=41)), "Textgröße"),
    (lambda: DataMatrixObject(**_t(module=1)), "Modul"),
    (lambda: IconObject(**_t(icon="")), "Icon"),
    (lambda: IconObject(**_t(icon="fa:star")), "Icon"),
    (lambda: LineObject(**_t(direction="diag")), "Richtung"),
    (lambda: LineObject(**_t(thickness=0)), "Stärke"),
    (lambda: LineObject(**_t(dash=51)), "Strich"),
    (lambda: RectObject(**_t(thickness=0, fill="none")), "Füllung"),
    (lambda: RectObject(**_t(radius=41)), "Radius"),
    (lambda: RectObject(**_t(fill="dots")), "Füllung"),
    (lambda: RectObject(**_t(stripe=1)), "Streifen"),
    (lambda: ImageObject(**_t(png="")), "Bilddaten"),
    (lambda: ImageObject(**_t(png="x", threshold=256)), "Schwelle"),
    (lambda: ImageObject(**_t(png="x", dither="atkinson")), "Rasterung"),
])
def test_objekt_validierung(factory, match):
    with pytest.raises(DocumentError, match=match):
        factory()


def test_gueltige_icons():
    IconObject(**_t(icon="tabler:arrow-up"))
    IconObject(**_t(icon="simple:github"))
    IconObject(**_t(icon="user:mein_logo.v2"))
    IconObject(**_t(icon="{symbol}"))


def test_rahmen_ohne_linie_mit_fuellung_erlaubt():
    RectObject(**_t(thickness=0, fill="solid"))


@pytest.mark.parametrize("kwargs,match", [
    ({"objects": (TextObject(**_t()), QrObject(**_t()))}, "Objekt-ID 't1' doppelt"),
    ({"length_mode": "fixed"}, "Länge"),
    ({"length_mode": "max", "length_mm": 0}, "Länge"),
    ({"length_mode": "auto", "length_mm": 10}, "Länge"),
    ({"objects": [TextObject(**_t())]}, "Tupel"),
    ({"objects": ("kein objekt",)}, "Objekt"),
    ({"length_mode": "egal"}, "Längenmodus"),
    ({"margin_mm": 21}, "Rand"),
    ({"mirror": "ja"}, "mirror"),
])
def test_dokument_validierung(kwargs, match):
    with pytest.raises(DocumentError, match=match):
        LabelDocument(**kwargs)


def test_replace_validiert_erneut():
    obj = TextObject(**_t())
    with pytest.raises(DocumentError):
        dataclasses.replace(obj, w=0)


# 5 ---------------------------------------------------------------------------

def test_neuere_version():
    with pytest.raises(DocumentError, match="Dokument-Version 2 ist neuer als diese App \\(1\\)"):
        document_from_dict({"version": 2, "objects": []})


def test_version_fehlt_ist_1():
    assert document_from_dict({"objects": []}) == LabelDocument()


def test_unbekannter_dokument_schluessel():
    with pytest.raises(DocumentError, match=r"unbekannte Eigenschaften \['foo'\]"):
        document_from_dict({"objects": [], "foo": 1})


def test_unbekannter_objekt_schluessel():
    with pytest.raises(DocumentError, match=r"unbekannte Eigenschaften \['farbe'\]"):
        object_from_dict({"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 1, "h": 1, "farbe": 3})


def test_unbekannte_objektart():
    with pytest.raises(DocumentError, match="kreis.*text"):
        document_from_dict({"objects": [{"kind": "kreis", "id": "k1", "x": 0, "y": 0, "w": 1, "h": 1}]})


def test_pflichtfeld_fehlt():
    with pytest.raises(DocumentError, match="fehlt"):
        object_from_dict({"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 1})


def test_ungueltiges_json():
    with pytest.raises(DocumentError, match="JSON"):
        document_from_json("{kaputt")


def test_kein_objekt_als_dict():
    with pytest.raises(DocumentError):
        document_from_dict({"objects": "abc"})
    with pytest.raises(DocumentError):
        document_from_dict([])


# 6 ---------------------------------------------------------------------------

def test_texts_und_map_texts():
    doc = _full_doc()
    assert texts(doc) == ["{host}\nZeile 2", "{sn}", "ABC", "X", "{symbol}"]
    mapped = map_texts(doc, lambda s: s.upper())
    assert texts(mapped) == ["{HOST}\nZEILE 2", "{SN}", "ABC", "X", "{SYMBOL}"]
    for before, after in zip(doc.objects, mapped.objects):
        if before.kind in ("line", "rect", "image"):
            assert after is before
    assert mapped.length_mm == doc.length_mm and mapped.mirror


# 7 ---------------------------------------------------------------------------

def test_bbox_und_extent():
    a = TextObject(id="a", x=-2, y=3, w=10, h=5)
    b = QrObject(id="b", x=20, y=0, w=30, h=30, visible=False)
    c = LineObject(id="c", x=5, y=0, w=15, h=2)
    assert bbox(a) == (-2, 3, 8, 8)
    assert extent(LabelDocument(objects=(a, b, c))) == 20
    assert extent(LabelDocument()) == 0


def test_find_replace_with_objects():
    a = TextObject(id="a", x=0, y=0, w=10, h=5)
    b = QrObject(id="b", x=20, y=0, w=30, h=30)
    c = LineObject(id="c", x=5, y=0, w=15, h=2)
    doc = LabelDocument(objects=(a, b, c), length_mode="max", length_mm=30)
    assert find_object(doc, "b") is b
    with pytest.raises(DocumentError, match="'zz'"):
        find_object(doc, "zz")
    b2 = dataclasses.replace(b, data="neu")
    doc2 = replace_object(doc, b2)
    assert [o.id for o in doc2.objects] == ["a", "b", "c"]
    assert doc2.objects[1] is b2 and doc2.length_mm == 30
    with pytest.raises(DocumentError):
        replace_object(doc, QrObject(id="zz", x=0, y=0, w=1, h=1))
    doc3 = with_objects(doc, [c, a])
    assert doc3.objects == (c, a) and doc3.length_mode == "max"


def test_new_id():
    mk = lambda i: TextObject(id=i, x=0, y=0, w=1, h=1)  # noqa: E731
    assert new_id(LabelDocument(), "text") == "text1"
    assert new_id(LabelDocument(objects=(mk("text1"),)), "text") == "text2"
    assert new_id(LabelDocument(objects=(mk("text1"), mk("text3"))), "text") == "text2"
    assert new_id(LabelDocument(objects=(mk("text1"),)), "qr") == "qr1"
    with pytest.raises(DocumentError):
        new_id(LabelDocument(), "kreis")


# 8/9 -------------------------------------------------------------------------

def test_prepare_embedded_image_rgba():
    img = Image.new("RGBA", (3000, 100), (0, 0, 0, 128))
    img.paste((0, 0, 0, 0), (0, 0, 300, 100))
    result = decode_png(prepare_embedded_image(img))
    assert result.mode == "L"
    assert result.size[0] == MAX_IMAGE_SIDE
    assert result.getpixel((10, result.size[1] // 2)) == 255
    assert result.getpixel((900, result.size[1] // 2)) < 200


def test_prepare_kleines_bild_bleibt():
    result = decode_png(prepare_embedded_image(Image.new("1", (30, 40), 1)))
    assert result.size == (30, 40) and result.mode == "L"


def test_encode_decode_rundlauf():
    img = Image.new("L", (7, 3), 42)
    back = decode_png(encode_png(img))
    assert back.mode == "L" and back.size == (7, 3) and back.getpixel((0, 0)) == 42


def test_decode_png_kaputt():
    with pytest.raises(DocumentError, match="Bilddaten nicht lesbar"):
        decode_png("kein-base64")
    with pytest.raises(DocumentError, match="Bilddaten nicht lesbar"):
        decode_png("aGFsbG8=")


# 10 --------------------------------------------------------------------------

def test_kein_qt():
    code = "import tapesmith.document\nimport tapesmith.document.model\nimport sys\nprint('PySide6' in sys.modules)\n"
    env = dict(os.environ)
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else os.pathsep.join([src_path, existing])
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(REPO_ROOT),
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False", result.stdout + result.stderr
