"""Tests für die Editierlogik: Operationen auf `LabelDocument`."""

import pytest
from PIL import Image

from tapesmith.document.editing import (
    DUPLICATE_OFFSET,
    PRESETS,
    add_object,
    align,
    default_object,
    distribute,
    duplicate,
    flip_objects,
    hit_test,
    move_objects,
    objects_in_rect,
    remove_objects,
    reorder,
    rotate_objects,
    selection_box,
    set_box,
    set_label_transform,
    set_length,
    step_label,
    update_object,
)
from tapesmith.document.model import (
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
    extent,
    prepare_embedded_image,
)


def _png():
    return prepare_embedded_image(Image.new("L", (10, 10), 0))


def _t(**kw):
    base = dict(id="t1", x=0, y=0, w=10, h=10)
    base.update(kw)
    return TextObject(**base)


# 1 -----------------------------------------------------------------------------

@pytest.mark.parametrize("preset", [p for p in PRESETS if p != "image"])
def test_default_object_presets(preset):
    doc = LabelDocument()
    obj = default_object(preset, doc, content_dots=88)
    assert obj.id
    assert obj.w >= 1 and obj.h >= 1


def test_default_object_image_braucht_png():
    doc = LabelDocument()
    with pytest.raises(ValueError):
        default_object("image", doc, content_dots=88)
    obj = default_object("image", doc, content_dots=88, png=_png())
    assert isinstance(obj, ImageObject) and obj.png


def test_default_object_klassen():
    doc = LabelDocument()
    mapping = {
        "text": TextObject, "qr": QrObject, "code128": Code128Object,
        "datamatrix": DataMatrixObject, "icon": IconObject, "line": LineObject,
        "arrow": LineObject, "rect": RectObject, "warnbar": RectObject,
    }
    for preset, cls in mapping.items():
        obj = default_object(preset, doc, content_dots=88)
        assert isinstance(obj, cls)


def test_default_object_y_mittig():
    doc = LabelDocument()
    obj = default_object("text", doc, content_dots=88)
    assert obj.y == (88 - obj.h) // 2
    qr = default_object("qr", doc, content_dots=88)
    assert qr.w == qr.h == 88 and qr.y == 0


def test_default_object_eindeutige_ids_und_position():
    doc = LabelDocument()
    first = default_object("text", doc, content_dots=88)
    assert first.x == 8  # erstes Objekt
    doc = add_object(doc, first)
    second = default_object("qr", doc, content_dots=88)
    assert second.id != first.id
    assert second.x >= extent(doc) + 8


def test_default_object_at_setzt_ecke():
    doc = LabelDocument()
    obj = default_object("text", doc, content_dots=88, at=(30, 12))
    assert (obj.x, obj.y) == (30, 12)


def test_default_object_unbekannte_vorlage():
    with pytest.raises(ValueError):
        default_object("kreis", LabelDocument(), content_dots=88)


# 2 -----------------------------------------------------------------------------

def test_move_objects():
    doc = LabelDocument(objects=(_t(id="a", x=0, y=0), _t(id="b", x=0, y=0, locked=True)))
    moved = move_objects(doc, ["a", "b"], 1, 0)
    assert moved.objects[0].x == 1
    assert moved.objects[1].x == 0  # gesperrt bleibt stehen
    moved8 = move_objects(doc, ["a"], 8, 0)
    assert moved8.objects[0].x == 8
    # Eingabedokument unverändert
    assert doc.objects[0].x == 0


def test_move_objects_unbekannte_id():
    doc = LabelDocument(objects=(_t(id="a"),))
    with pytest.raises(DocumentError):
        move_objects(doc, ["zz"], 1, 0)


# 3 -----------------------------------------------------------------------------

def test_set_box_klemmt_minimum():
    doc = LabelDocument(objects=(_t(id="text1", w=10, h=10),))
    result = set_box(doc, "text1", x=5, y=5, w=0, h=0)
    obj = result.objects[0]
    assert obj.x == 5 and obj.y == 5 and obj.w == 1 and obj.h == 1


def test_update_object_aendert_und_validiert():
    doc = LabelDocument(objects=(_t(id="text1"),))
    updated = update_object(doc, "text1", text="Neu")
    assert updated.objects[0].text == "Neu"
    with pytest.raises(DocumentError):
        update_object(doc, "text1", rotation=45)


# 4 -----------------------------------------------------------------------------

def _align_doc():
    return LabelDocument(objects=(
        _t(id="a", x=0, y=0, w=10, h=10),
        _t(id="b", x=20, y=5, w=20, h=20),
        _t(id="c", x=50, y=30, w=10, h=30),
    ))


@pytest.mark.parametrize("mode,expected", [
    ("left", {"a": 0, "b": 0, "c": 0}),
    ("hcenter", {"a": 25, "b": 20, "c": 25}),
    ("right", {"a": 50, "b": 40, "c": 50}),
    ("top", {"a": 0, "b": 0, "c": 0}),
    ("vcenter", {"a": 25, "b": 20, "c": 15}),
    ("bottom", {"a": 50, "b": 40, "c": 30}),
])
def test_align_selection(mode, expected):
    doc = _align_doc()
    result = align(doc, ["a", "b", "c"], mode, content_dots=88)
    axis = "x" if mode in ("left", "hcenter", "right") else "y"
    for obj in result.objects:
        assert getattr(obj, axis) == expected[obj.id]


def test_align_label_vcenter():
    doc = _align_doc()
    result = align(doc, ["a", "b", "c"], "vcenter", reference="label", content_dots=88)
    for obj in result.objects:
        assert obj.y == (88 - obj.h) // 2


def test_align_label_horizontal_braucht_length_dots():
    doc = _align_doc()
    with pytest.raises(ValueError):
        align(doc, ["a"], "left", reference="label", content_dots=88)
    result = align(doc, ["a"], "left", reference="label", content_dots=88, length_dots=200)
    assert result.objects[0].x == 0


# 5 -----------------------------------------------------------------------------

def test_distribute_horizontal():
    doc = LabelDocument(objects=(
        _t(id="a", x=0, y=0, w=10, h=10),
        _t(id="b", x=30, y=0, w=10, h=10),
        _t(id="c", x=100, y=0, w=10, h=10),
    ))
    result = distribute(doc, ["a", "b", "c"], "h")
    by_id = {o.id: o for o in result.objects}
    assert by_id["a"].x == 0
    assert by_id["b"].x == 50
    assert by_id["c"].x == 100


def test_distribute_weniger_als_drei_unveraendert():
    doc = LabelDocument(objects=(_t(id="a", x=0), _t(id="b", x=30)))
    result = distribute(doc, ["a", "b"], "h")
    assert result == doc


def test_distribute_unbekannte_achse():
    doc = LabelDocument(objects=(_t(id="a"), _t(id="b"), _t(id="c")))
    with pytest.raises(ValueError):
        distribute(doc, ["a", "b", "c"], "diag")


# 6 -----------------------------------------------------------------------------

def _reorder_doc():
    return LabelDocument(objects=(_t(id="a"), _t(id="b"), _t(id="c"), _t(id="d")))


def test_reorder_raise():
    result = reorder(_reorder_doc(), ["b"], "raise")
    assert [o.id for o in result.objects] == ["a", "c", "b", "d"]


def test_reorder_lower():
    result = reorder(_reorder_doc(), ["c"], "lower")
    assert [o.id for o in result.objects] == ["a", "c", "b", "d"]


def test_reorder_top():
    result = reorder(_reorder_doc(), ["a", "c"], "top")
    assert [o.id for o in result.objects] == ["b", "d", "a", "c"]


def test_reorder_bottom():
    result = reorder(_reorder_doc(), ["b", "d"], "bottom")
    assert [o.id for o in result.objects] == ["b", "d", "a", "c"]


# 7 -----------------------------------------------------------------------------

def test_duplicate():
    doc = LabelDocument(objects=(_t(id="text1", x=0, y=0), QrObject(id="qr1", x=5, y=5, w=8, h=8)))
    result, new_ids = duplicate(doc, ["text1", "qr1"])
    assert len(new_ids) == 2
    assert set(new_ids).isdisjoint({"text1", "qr1"})
    assert [o.id for o in result.objects][:2] == ["text1", "qr1"]
    assert [o.id for o in result.objects][2:] == list(new_ids)
    dup_text = result.objects[2]
    assert (dup_text.x, dup_text.y) == (0 + DUPLICATE_OFFSET[0], 0 + DUPLICATE_OFFSET[1])
    # Original unverändert
    assert doc.objects[0].x == 0


# 8 -----------------------------------------------------------------------------

def test_rotate_objects_90():
    doc = LabelDocument(objects=(TextObject(id="t1", x=10, y=20, w=40, h=20),))
    result = rotate_objects(doc, ["t1"], 90)
    obj = result.objects[0]
    assert obj.rotation == 90
    assert (obj.x, obj.y, obj.w, obj.h) == (20, 10, 20, 40)


def test_rotate_objects_180_lässt_box():
    doc = LabelDocument(objects=(TextObject(id="t1", x=10, y=20, w=40, h=20),))
    result = rotate_objects(doc, ["t1"], 180)
    obj = result.objects[0]
    assert obj.rotation == 180
    assert (obj.x, obj.y, obj.w, obj.h) == (10, 20, 40, 20)


def test_rotate_objects_unbekannter_winkel():
    doc = LabelDocument(objects=(TextObject(id="t1", x=0, y=0, w=10, h=10),))
    with pytest.raises(ValueError):
        rotate_objects(doc, ["t1"], 45)


def test_flip_objects():
    doc = LabelDocument(objects=(TextObject(id="t1", x=0, y=0, w=10, h=10, mirror=False),))
    result = flip_objects(doc, ["t1"])
    assert result.objects[0].mirror is True
    result2 = flip_objects(result, ["t1"])
    assert result2.objects[0].mirror is False


def test_set_label_transform():
    doc = LabelDocument()
    result = set_label_transform(doc, mirror=True)
    assert result.mirror is True and result.rotate180 is False
    result2 = set_label_transform(result, rotate180=True)
    assert result2.mirror is True and result2.rotate180 is True
    assert set_label_transform(doc) == doc


def test_set_length():
    doc = LabelDocument()
    fixed = set_length(doc, "fixed", 40.0)
    assert fixed.length_mode == "fixed" and fixed.length_mm == 40.0
    back_auto = set_length(fixed, "auto")
    assert back_auto.length_mode == "auto" and back_auto.length_mm is None


# 9 -----------------------------------------------------------------------------

def test_hit_test():
    doc = LabelDocument(objects=(
        TextObject(id="a", x=0, y=0, w=10, h=10),
        TextObject(id="b", x=5, y=5, w=10, h=10),
        TextObject(id="c", x=100, y=100, w=5, h=5, visible=False),
    ))
    assert hit_test(doc, 6, 6) == "b"  # oberstes
    assert hit_test(doc, 1, 1) == "a"
    assert hit_test(doc, 100, 100) is None  # unsichtbar übersprungen
    assert hit_test(doc, 50, 50) is None


def test_objects_in_rect():
    doc = LabelDocument(objects=(
        TextObject(id="a", x=0, y=0, w=10, h=10),
        TextObject(id="b", x=5, y=5, w=20, h=20),
        TextObject(id="c", x=200, y=200, w=5, h=5, visible=False),
    ))
    fully = objects_in_rect(doc, (0, 0, 10, 10))
    assert fully == ("a",)
    touching = objects_in_rect(doc, (0, 0, 10, 10), touch=True)
    assert touching == ("a", "b")


def test_selection_box():
    doc = LabelDocument(objects=(
        TextObject(id="a", x=0, y=0, w=10, h=5),
        TextObject(id="b", x=20, y=10, w=5, h=5),
    ))
    assert selection_box(doc, ["a", "b"]) == (0, 0, 25, 15)
    assert selection_box(doc, []) is None


# 10 ----------------------------------------------------------------------------

def test_step_label():
    doc = LabelDocument(objects=(
        QrObject(id="qr1", x=0, y=0, w=10, h=10),
        TextObject(id="text1", x=0, y=0, w=10, h=10),
    ))
    assert step_label("move", doc, ["qr1"]) == "QR verschoben"
    assert step_label("edit", doc, ["text1"]) == "Text geändert"
    assert step_label("move", doc, ["qr1", "text1"]) == "2 Objekte verschoben"
    assert step_label("label", doc, []) == "Label geändert"


def test_step_label_unbekannte_aktion():
    doc = LabelDocument(objects=(TextObject(id="text1", x=0, y=0, w=10, h=10),))
    with pytest.raises(ValueError):
        step_label("egal", doc, ["text1"])


def test_remove_objects():
    doc = LabelDocument(objects=(_t(id="a"), _t(id="b")))
    result = remove_objects(doc, ["a"])
    assert [o.id for o in result.objects] == ["b"]
    with pytest.raises(DocumentError):
        remove_objects(doc, ["zz"])
