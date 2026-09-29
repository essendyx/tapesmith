"""Tests für den UndoStack."""

import pytest

from tapesmith.document.model import LabelDocument, TextObject
from tapesmith.document.undo import UndoStack


def _doc(x=0):
    return LabelDocument(objects=(TextObject(id="t1", x=x, y=0, w=10, h=10),))


# 16 --------------------------------------------------------------------------

def test_push_undo_redo():
    stack = UndoStack(_doc(0), "Neues Label")
    assert not stack.can_undo() and not stack.can_redo()
    assert stack.push(_doc(1), "Verschoben") is True
    assert stack.can_undo() and not stack.can_redo()
    assert stack.current == _doc(1)
    assert stack.undo() == _doc(0)
    assert not stack.can_undo() and stack.can_redo()
    assert stack.redo() == _doc(1)
    assert not stack.can_redo()


def test_push_nach_undo_verwirft_redo():
    stack = UndoStack(_doc(0))
    stack.push(_doc(1), "A")
    stack.push(_doc(2), "B")
    stack.undo()
    assert stack.push(_doc(3), "C") is True
    assert not stack.can_redo()
    assert stack.labels() == ("Neues Label", "A", "C")


# 17 --------------------------------------------------------------------------

def test_push_gleiches_dokument_liefert_false():
    stack = UndoStack(_doc(0))
    assert stack.push(_doc(0), "Nichts") is False
    assert len(stack.steps) == 1
    assert stack.index == 0


# 18 --------------------------------------------------------------------------

def test_merge_key_fasst_pushes_zusammen():
    stack = UndoStack(_doc(0))
    stack.push(_doc(1), "QR verschoben", merge_key="nudge:qr1")
    stack.push(_doc(2), "QR verschoben", merge_key="nudge:qr1")
    stack.push(_doc(3), "QR verschoben", merge_key="nudge:qr1")
    assert len(stack.steps) == 2  # nur 1 neuer Schritt
    assert stack.current == _doc(3)
    assert stack.labels() == ("Neues Label", "QR verschoben")
    stack.undo()
    # nach undo beginnt ein neuer Schritt, auch mit demselben merge_key
    stack.push(_doc(4), "QR verschoben", merge_key="nudge:qr1")
    assert len(stack.steps) == 2
    assert stack.current == _doc(4)


def test_merge_key_bricht_bei_anderem_push():
    stack = UndoStack(_doc(0))
    stack.push(_doc(1), "QR verschoben", merge_key="nudge:qr1")
    stack.push(_doc(2), "Text geändert")  # kein merge_key -> bricht Kette
    stack.push(_doc(3), "QR verschoben", merge_key="nudge:qr1")
    assert len(stack.steps) == 4


# 19 --------------------------------------------------------------------------

def test_jump():
    stack = UndoStack(_doc(0))
    stack.push(_doc(1), "A")
    stack.push(_doc(2), "B")
    assert stack.jump(0) == _doc(0)
    assert stack.index == 0
    assert stack.jump(2) == _doc(2)
    with pytest.raises(IndexError):
        stack.jump(3)
    with pytest.raises(IndexError):
        stack.jump(-1)


# 20 --------------------------------------------------------------------------

def test_unbegrenzte_pushes():
    stack = UndoStack(_doc(0))
    for i in range(1, 1001):
        assert stack.push(_doc(i), f"Schritt {i}") is True
    assert len(stack.steps) == 1001
    labels = stack.labels()
    assert labels[0] == "Neues Label"
    assert labels[-1] == "Schritt 1000"
    assert len(labels) == 1001


# 21 --------------------------------------------------------------------------

def test_dirty():
    stack = UndoStack(_doc(0))
    assert not stack.dirty
    stack.mark_saved()
    assert not stack.dirty
    stack.push(_doc(1), "A")
    assert stack.dirty
    stack.undo()
    assert not stack.dirty
    stack.push(_doc(2), "B")
    assert stack.dirty
    stack.mark_saved()
    assert not stack.dirty


def test_reset():
    stack = UndoStack(_doc(0))
    stack.push(_doc(1), "A")
    stack.mark_saved()
    stack.reset(_doc(5), "Neu")
    assert stack.current == _doc(5)
    assert stack.labels() == ("Neu",)
    assert not stack.dirty
    assert not stack.can_undo() and not stack.can_redo()
