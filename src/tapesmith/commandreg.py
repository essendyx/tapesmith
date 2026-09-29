"""Befehlsregister: unscharfe Suche über Titel/Schlüsselwörter für die Kommandopalette.

Kein Qt hier, nur das Register und die Suchlogik. Die Palette (`gui/command_palette.py`)
verwendet dieses Modul, um Treffer zu ermitteln und Befehle auszuführen.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from tapesmith.i18n import _t

_UMLAUT_MAP = {"ß": "ss"}
_AEOU_MAP = {"ae": "a", "oe": "o", "ue": "u"}


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    run: Callable[[], object] = field(compare=False, repr=False)
    keywords: tuple[str, ...] = ()
    shortcut: str = ""
    group: str = ""
    enabled: Callable[[], bool] = field(default=lambda: True, compare=False, repr=False)


def fold(text: str) -> str:
    """casefold, `ß`->`ss`, Umlaute/Akzente entfernt (NFKD). `ae`/`oe`/`ue` bleiben erhalten."""
    text = text.casefold()
    for src, dst in _UMLAUT_MAP.items():
        text = text.replace(src, dst)
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks


def _fold_variants(text: str) -> tuple[str, ...]:
    """Gefaltete Form plus eine Variante mit `ae/oe/ue` -> `a/o/u` (für z. B. „geoeffnet“)."""
    folded = fold(text)
    variant = folded
    for src, dst in _AEOU_MAP.items():
        variant = variant.replace(src, dst)
    if variant == folded:
        return (folded,)
    return (folded, variant)


def _initials(words: list[str]) -> str:
    return "".join(w[0] for w in words if w)


def _is_subsequence(query: str, text: str) -> bool:
    it = iter(text)
    return all(ch in it for ch in query)


def _score(query: str, command: Command) -> int:
    best = 0
    title_folded = fold(command.title)
    title_words = title_folded.split()
    keyword_variants = [fold(k) for k in command.keywords]

    for q in _fold_variants(query):
        if not q:
            continue
        if q in keyword_variants:
            best = max(best, 100)
            continue
        if title_folded.startswith(q):
            best = max(best, 80)
            continue
        if any(k.startswith(q) for k in keyword_variants):
            best = max(best, 70)
            continue
        if any(w.startswith(q) for w in title_words):
            best = max(best, 60)
            continue
        if q in title_folded:
            best = max(best, 40)
            continue
        if any(q in k for k in keyword_variants):
            best = max(best, 30)
            continue
        if _initials(title_words).startswith(q):
            best = max(best, 20)
            continue
        if _is_subsequence(q, title_folded):
            best = max(best, 10)
    return best


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        if command.id in self._commands:
            raise ValueError(_t("Befehl '{id}' bereits registriert", id=command.id))
        self._commands[command.id] = command

    def unregister(self, command_id: str) -> None:
        self._commands.pop(command_id, None)

    def get(self, command_id: str) -> Command:
        return self._commands[command_id]

    def all(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: (c.group, c.title))

    def search(self, query: str, limit: int = 20) -> list[Command]:
        enabled = [c for c in self._commands.values() if c.enabled()]
        query = query.strip()
        if not query:
            return sorted(enabled, key=lambda c: (c.group, c.title))[:limit]
        scored = []
        for command in enabled:
            score = _score(query, command)
            if score > 0:
                scored.append((score, command))
        scored.sort(key=lambda pair: (-pair[0], pair[1].title))
        return [c for _score_, c in scored[:limit]]

    def run(self, command_id: str) -> object:
        command = self.get(command_id)
        if not command.enabled():
            raise ValueError(_t("Befehl '{title}' gerade nicht verfügbar", title=command.title))
        return command.run()
