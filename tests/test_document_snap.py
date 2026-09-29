"""Tests für Einrasten/Hilfslinien."""

from tapesmith.document.model import LabelDocument, TextObject
from tapesmith.document.snap import Guide, SnapResult, snap_move, snap_resize


def _obj(id_, x, y, w, h, **kw):
    return TextObject(id=id_, x=x, y=y, w=w, h=h, **kw)


# 11 ------------------------------------------------------------------------

def test_snap_move_rastet_an_bandmitte():
    doc = LabelDocument(objects=(_obj("a", 10, 30, 20, 20),))
    result = snap_move(doc, ["a"], 0, 3, content_dots=88)
    assert result.dy == 4
    assert result.dx == 0
    assert Guide("h", 44, "center") in result.guides


# 12 ------------------------------------------------------------------------

def test_snap_move_rastet_an_objektkante():
    doc = LabelDocument(objects=(
        _obj("moving", 50, 0, 10, 10),
        _obj("other", 20, 40, 30, 10),
    ))
    result = snap_move(doc, ["moving"], -28, 0, content_dots=88)
    # Ziel-x der bewegten Box: 50-28=22, nahe der linken Kante von "other" bei 20
    assert result.dx == -30
    assert Guide("v", 20, "object") in result.guides


# 13 ------------------------------------------------------------------------

def test_snap_move_grid_ohne_kandidat():
    doc = LabelDocument(objects=(_obj("a", 10, 10, 5, 5),))
    result = snap_move(doc, ["a"], 3, 0, content_dots=88, grid=8)
    # linke Kante 10+3=13 -> nächstes Vielfaches von 8 ist 16 -> dx=6
    assert result.dx == 6
    assert result.guides == ()


# 14 ------------------------------------------------------------------------

def test_snap_move_disabled():
    doc = LabelDocument(objects=(_obj("a", 10, 30, 20, 20),))
    result = snap_move(doc, ["a"], 0, 3, content_dots=88, enabled=False)
    assert result == SnapResult(0, 3, ())


def test_snap_move_ausgewaehlte_objekte_keine_kandidaten():
    doc = LabelDocument(objects=(
        _obj("a", 10, 30, 20, 20),
        _obj("b", 100, 30, 20, 20),
    ))
    # Beide ausgewählt: "b" darf nicht als Kandidat für "a" dienen.
    result = snap_move(doc, ["a", "b"], 1, 0, content_dots=88)
    assert not any(g.kind == "object" for g in result.guides)


# 15 ------------------------------------------------------------------------

def test_snap_resize_nur_bewegte_kante():
    doc = LabelDocument(objects=(
        _obj("a", 0, 0, 40, 20),
        _obj("other", 100, 0, 10, 10),
    ))
    # rechte Kante von "a" bei 40, Ziel dx=+57 -> 97, nahe an linker Kante von "other" (100)
    result = snap_resize(doc, "a", "e", 57, 5, content_dots=88)
    assert result.dx == 60
    assert result.dy == 5  # unverändert, "e" bewegt keine y-Kante
    assert all(g.orientation == "v" for g in result.guides)
