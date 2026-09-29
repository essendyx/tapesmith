"""Kopien- und Längengrenzen je Quelle ("Variante 1").

`guard.py`/`pipeline.py` bleiben unverändert: nicht-interaktive Quellen (`api`, `mcp`,
`mqtt`, `hotfolder`) können die Guard-Rückfrage nie bestätigen, die Pipeline lehnt ab. Dieses
Modul lässt Kanäle die Kopien- und Längengrenze vorab prüfen und verständlich melden. Reine
Logik ohne Ein-/Ausgabe, Qt-frei, importiert nichts aus `webapi`.
"""

from __future__ import annotations

import logging

from tapesmith import config, guard
from tapesmith.jobs import SOURCES
from tapesmith.i18n import _t

NON_INTERACTIVE = ("api", "mcp", "mqtt", "hotfolder")

log = logging.getLogger(__name__)


def _check_origin(origin: str) -> None:
    if origin not in SOURCES:
        raise ValueError(_t("Unbekannte Quelle '{origin}' (erlaubt: {items})", origin=origin, items=', '.join(SOURCES)))


def policy(cfg: dict) -> guard.GuardPolicy:
    """`guard.load_policy(cfg)`; eine kaputte `guard`-Sektion (ValueError) ergibt die
    Standardwerte statt einer Ausnahme, mit einer Warnung im Log."""
    try:
        return guard.load_policy(cfg)
    except ValueError as exc:
        log.warning("Konfiguration 'guard' ungültig, verwende Standardwerte: %s", exc)
        return guard.GuardPolicy()


def can_confirm_guard(origin: str) -> bool:
    return origin in guard.INTERACTIVE_SOURCES


def max_copies(cfg: dict, origin: str) -> int:
    """Interaktive Quellen: `policy.max_copies`. Sonst `policy.confirm_copies` (mindestens 1,
    auch wenn `confirm_copies` per Konfiguration 0 wäre)."""
    _check_origin(origin)
    pol = policy(cfg)
    if can_confirm_guard(origin):
        return pol.max_copies
    return max(1, pol.confirm_copies)


def max_label_mm(cfg: dict, origin: str) -> float:
    _check_origin(origin)
    pol = policy(cfg)
    if can_confirm_guard(origin):
        return pol.max_label_mm
    return pol.confirm_label_mm


def copies_error(cfg: dict, origin: str, copies: object) -> str | None:
    """`None`, wenn `copies` eine ganze Zahl (kein `bool`) im Bereich 1..`max_copies(cfg, origin)`
    ist; sonst eine deutsche Meldung. Für nicht-interaktive Quellen nennt die Meldung zusätzlich
    die Konfigurationsquelle der Grenze."""
    _check_origin(origin)
    limit = max_copies(cfg, origin)
    valid = isinstance(copies, int) and not isinstance(copies, bool) and 1 <= copies <= limit
    if valid:
        return None
    base = _t("Kopien müssen eine ganze Zahl von 1 bis {limit} sein", limit=limit)
    if can_confirm_guard(origin):
        return base
    return _t("{base} (Grenze für Quelle {origin}: guard.confirm_copies)", base=base, origin=origin)


def family_max_copies(cfg: dict) -> int:
    return min(config.setting(cfg, "family.max_copies"), max_copies(cfg, "api"))


def limits_text(cfg: dict, origin: str) -> str:
    n = max_copies(cfg, origin)
    mm = int(max_label_mm(cfg, origin))
    return _t("höchstens {n} Kopien je Auftrag, Labels bis {mm} mm", n=n, mm=mm)
