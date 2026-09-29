"""Tests für die letzten Schnelldruck-Texte aus dem Verlauf (Vorschlags-Chips). Ohne Qt."""

import subprocess
import sys

from tapesmith.history import HistoryStore
from tapesmith.gui.recent import recent_texts
from tapesmith.jobs import JobMeta
from tapesmith.render.compose import LabelSpec


def test_kein_qt_import():
    code = (
        "import sys\n"
        "import tapesmith.gui.recent\n"
        "assert 'PySide6' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _record_text(store: HistoryStore, source: str, lines: tuple[str, ...], *,
                  sensitive: bool = False, status: str = "ok") -> int:
    from tapesmith.jobs import spec_to_dict
    spec = LabelSpec(lines=lines)
    meta = JobMeta(source=source, kind="text", title=" ".join(lines), sensitive=sensitive,
                   spec=spec_to_dict(spec))
    return store.record(meta, landscape=None, head=None, length_mm=10.0, tape_mm=12.0,
                         status=status)


def test_recent_texts_filtert_und_dedupliziert(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite3")
    _record_text(store, "gui", ("A",))
    _record_text(store, "gui", ("B", "C"))
    _record_text(store, "cli", ("X",))
    _record_text(store, "gui", ("Y",), status="abgebrochen")
    _record_text(store, "gui", ("Z",), sensitive=True)
    template_meta = JobMeta(source="gui", kind="template", title="Vorlage", spec=None)
    store.record(template_meta, landscape=None, head=None, length_mm=10.0, tape_mm=12.0,
                 status="ok")
    _record_text(store, "gui", ("A",))  # Duplikat, neuester

    result = recent_texts(store)

    assert result == [("A",), ("B", "C")]
    assert recent_texts(store, n=1) == [("A",)]


def test_recent_texts_leerer_verlauf(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite3")
    assert recent_texts(store) == []
