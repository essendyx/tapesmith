"""Die letzten Schnelldruck-Texte aus dem Verlauf (Vorschlags-Chips). Kein Qt-Import."""

from __future__ import annotations

from tapesmith.history import HistoryStore


def recent_texts(history: HistoryStore, n: int = 5, source: str = "gui",
                  scan_limit: int = 200) -> list[tuple[str, ...]]:
    """Bis zu `n` zuletzt gedruckte Schnelldruck-Texte (neueste zuerst), aus den
    letzten `scan_limit` Verlaufseinträgen. Nur erfolgreiche, nicht-sensible
    Text-Jobs der angegebenen Quelle zählen; Duplikate werden übersprungen
    (die neueste Fassung gewinnt)."""
    seen: set[tuple[str, ...]] = set()
    result: list[tuple[str, ...]] = []
    for entry in history.search("", limit=scan_limit):
        if len(result) >= n:
            break
        if entry.kind != "text" or entry.source != source or entry.status != "ok" or entry.sensitive:
            continue
        if entry.spec is None:
            continue
        lines = entry.spec.get("lines")
        if not isinstance(lines, list):
            continue
        stripped = tuple(lines)
        while stripped and not stripped[0].strip():
            stripped = stripped[1:]
        while stripped and not stripped[-1].strip():
            stripped = stripped[:-1]
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result
