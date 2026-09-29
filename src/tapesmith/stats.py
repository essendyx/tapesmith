"""Statistik zum Bandverbrauch: Auswertung des Verlaufs (`iter_entries`) nach Monat,
Vorlage, Quelle und Art, sowie der Rollen (`RollStore.all_rolls`). Alle Bandangaben sind
geschätzt (Vor-/Nachlauf ist kalibriert, aber ein gelernter Faktor bleibt eine Schätzung)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tapesmith.history import HistoryStore
from tapesmith.tape.profiles import find_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.i18n import N_, _t

GROUPS = ("monat", "vorlage", "quelle", "art")
COUNTED_STATUSES = ("ok", "abgebrochen", "unvollständig")   # "fehler"/"läuft" verbrauchen kein Band
NO_TEMPLATE = N_("(ohne Vorlage)")


@dataclass(frozen=True)
class UsageRow:
    key: str
    jobs: int
    labels: int
    tape_mm: float


def _group_key(entry, by: str) -> str:
    if by == "monat":
        return f"{entry.created:%Y-%m}"
    if by == "vorlage":
        return entry.template or _t(NO_TEMPLATE)
    if by == "quelle":
        return entry.source
    return entry.kind   # "art"


def usage_by(history: HistoryStore, by: str, *, since: datetime | None = None,
            until: datetime | None = None) -> list[UsageRow]:
    """Bandverbrauch gruppiert nach `by`; "monat" aufsteigend, sonst nach Band absteigend,
    dann Schlüssel. Nur Status aus `COUNTED_STATUSES` zählt."""
    if by not in GROUPS:
        raise ValueError(_t("Unbekannte Gruppierung '{by}' (erlaubt: {items})", by=by, items=', '.join(GROUPS)))
    acc: dict[str, list] = {}
    for entry in history.iter_entries(since=since, until=until):
        if entry.status not in COUNTED_STATUSES:
            continue
        key = _group_key(entry, by)
        row = acc.setdefault(key, [0, 0, 0.0])
        row[0] += 1
        row[1] += entry.copies
        row[2] += entry.tape_mm
    rows = [UsageRow(key=key, jobs=v[0], labels=v[1], tape_mm=v[2]) for key, v in acc.items()]
    if by == "monat":
        rows.sort(key=lambda r: r.key)
    else:
        rows.sort(key=lambda r: (-r.tape_mm, r.key))
    return rows


def totals(rows: Sequence[UsageRow]) -> UsageRow:
    return UsageRow(key="Summe", jobs=sum(r.jobs for r in rows), labels=sum(r.labels for r in rows),
                    tape_mm=sum(r.tape_mm for r in rows))


@dataclass(frozen=True)
class RollUsage:
    tape_id: str
    tape_name: str
    started: str
    length_mm: float
    used_mm: float
    jobs: int
    finished: bool
    factor: float


def roll_usage(rolls: RollStore) -> list[RollUsage]:
    """Alle Rollen (beendet und aktuell) mit aufgelöstem Bandnamen (`find_tape`; unbekannte
    `tape_id` -> die id selbst)."""
    result = []
    for state, finished in rolls.all_rolls():
        try:
            name = find_tape(state.tape_id).name
        except ValueError:
            name = state.tape_id
        result.append(RollUsage(tape_id=state.tape_id, tape_name=name, started=state.started,
                                length_mm=state.length_mm, used_mm=state.used_mm, jobs=state.jobs,
                                finished=finished, factor=state.factor))
    return result


def format_m(mm: float) -> str:
    """1234.0 -> "1,23 m" (Dezimalkomma)."""
    return f"{mm / 1000:.2f} m".replace(".", ",")
