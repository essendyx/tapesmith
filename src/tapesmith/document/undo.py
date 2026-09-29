"""Unbegrenztes Undo/Redo mit benannten Schritten und Sprung zu jedem Schritt."""

from dataclasses import dataclass

from tapesmith.document.model import LabelDocument
from tapesmith.i18n import _t


@dataclass(frozen=True)
class UndoStep:
    label: str
    document: LabelDocument


class UndoStack:
    def __init__(self, initial: LabelDocument, label: str | None = None) -> None:
        self._steps: list[UndoStep] = [UndoStep(_t("Neues Label") if label is None else label, initial)]
        self._index = 0
        self._saved_index = 0
        self._last_merge_key: str | None = None

    @property
    def current(self) -> LabelDocument:
        return self._steps[self._index].document

    @property
    def index(self) -> int:
        return self._index

    @property
    def steps(self) -> tuple[UndoStep, ...]:
        return tuple(self._steps)

    def labels(self) -> tuple[str, ...]:
        return tuple(step.label for step in self._steps)

    def push(self, doc: LabelDocument, label: str, *, merge_key: str | None = None) -> bool:
        if doc == self.current:
            return False
        if (merge_key is not None and self._last_merge_key == merge_key
                and self._index == len(self._steps) - 1):
            self._steps[self._index] = UndoStep(self._steps[self._index].label, doc)
        else:
            del self._steps[self._index + 1:]
            self._steps.append(UndoStep(label, doc))
            self._index += 1
        self._last_merge_key = merge_key
        return True

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._steps) - 1

    def undo(self) -> LabelDocument | None:
        if not self.can_undo():
            return None
        self._index -= 1
        self._last_merge_key = None
        return self.current

    def redo(self) -> LabelDocument | None:
        if not self.can_redo():
            return None
        self._index += 1
        self._last_merge_key = None
        return self.current

    def jump(self, index: int) -> LabelDocument:
        if not 0 <= index < len(self._steps):
            raise IndexError(_t("Schritt {index} außerhalb 0..{value}", index=index, value=len(self._steps) - 1))
        self._index = index
        self._last_merge_key = None
        return self.current

    def reset(self, doc: LabelDocument, label: str | None = None) -> None:
        self._steps = [UndoStep(_t("Neues Label") if label is None else label, doc)]
        self._index = 0
        self._saved_index = 0
        self._last_merge_key = None

    def mark_saved(self) -> None:
        self._saved_index = self._index

    @property
    def dirty(self) -> bool:
        return self._index != self._saved_index
