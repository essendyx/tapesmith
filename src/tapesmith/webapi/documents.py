"""Dokumentablage für den Web-Editor: Server-Ordner mit `<name>.p12doc.json`-Dateien.

Der Name `_entwurf` ist für den Autosave-Entwurf der Oberfläche reserviert und taucht deshalb nie
in `list_documents()` auf (er lässt sich trotzdem laden/speichern/löschen wie jeder andere Name).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith import paths
from tapesmith.document.model import LabelDocument, document_from_dict, document_to_dict
from tapesmith.fileutil import atomic_write_text
from tapesmith.webapi.errors import NotFound
from tapesmith.i18n import _t

DOC_SUFFIX = ".p12doc.json"
DRAFT_NAME = "_entwurf"
_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")


@dataclass(frozen=True)
class DocumentInfo:
    name: str
    modified: str
    objects: int

    def to_dict(self) -> dict:
        return {"name": self.name, "modified": self.modified, "objects": self.objects}


def documents_dir() -> Path:
    path = paths.app_dir() / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.match(name) or ".." in name:
        raise ValueError(
            _t("Dokumentname '{name}' ungültig (Buchstaben, Ziffern, Leerzeichen, . _ -, höchstens 64 Zeichen, kein '..')", name=name))


def _path_for(name: str) -> Path:
    _validate_name(name)
    return documents_dir() / f"{name}{DOC_SUFFIX}"


def _modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def list_documents() -> list[DocumentInfo]:
    """Alle gespeicherten Dokumente außer dem Autosave-Entwurf, neueste zuerst."""
    infos = []
    for file in documents_dir().glob(f"*{DOC_SUFFIX}"):
        name = file.name[: -len(DOC_SUFFIX)]
        if name == DRAFT_NAME:
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        infos.append(DocumentInfo(name=name, modified=_modified(file),
                                  objects=len(data.get("objects", []))))
    infos.sort(key=lambda info: info.modified, reverse=True)
    return infos


def load_document(name: str) -> LabelDocument:
    path = _path_for(name)
    if not path.is_file():
        raise NotFound(_t("Dokument '{name}' nicht gefunden", name=name))
    data = json.loads(path.read_text(encoding="utf-8"))
    return document_from_dict(data)


def save_document(name: str, document: LabelDocument) -> DocumentInfo:
    path = _path_for(name)
    data = document_to_dict(document)
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    return DocumentInfo(name=name, modified=_modified(path), objects=len(document.objects))


def delete_document(name: str) -> None:
    path = _path_for(name)
    if not path.is_file():
        raise NotFound(_t("Dokument '{name}' nicht gefunden", name=name))
    path.unlink()
