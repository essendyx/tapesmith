"""Restmeter je Rolle: Schätzung mit über „Rolle war leer bei x m" gelerntem Faktor.

Eine „Neue Rolle" hat nominell `ROLL_LENGTH_MM` (4,00 m). Jeder Druck zieht per `consume`
Inhalt + Vor-/Nachlauf ab. `mark_empty` lernt aus der tatsächlichen Länge einen Faktor
(echte Länge / Nennlänge, geklemmt 0,5..1,5), den die nächste `new_roll` übernimmt.
Alles wird unter `FileLock` atomar geschrieben (Muster `templates.fill.CounterStore`).

Rollen werden je Band (`tape_id`) geführt: jedes Band hat seine eigene aktuelle Rolle und seinen
eigenen gelernten Faktor. Ohne `tape_id` gilt das in der Config gewählte Band (`current_tape`),
damit Drucke nach einem Bandwechsel nie gegen die Rolle des vorherigen Bandes zählen. Das alte
Dateiformat (eine globale `current`-Rolle) wird beim Lesen übernommen.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith import config, paths
from tapesmith.fileutil import FileLock, atomic_write_text
from tapesmith.i18n import _t

ROLL_LENGTH_MM = 4000.0
LOW_REST_MM = 300.0
_FACTOR_MIN, _FACTOR_MAX = 0.5, 1.5


def _de(value: float) -> str:
    """Dezimalkomma statt Punkt, eine Nachkommastelle."""
    return f"{value:.1f}".replace(".", ",")


@dataclass(frozen=True)
class RollState:
    tape_id: str
    started: str                # ISO-Zeitpunkt
    length_mm: float            # Nennlänge
    used_mm: float
    jobs: int
    factor: float = 1.0         # aus "leer bei x m" gelernt: echte Länge / Nennlänge

    def to_dict(self) -> dict:
        return {"tape_id": self.tape_id, "started": self.started, "length_mm": self.length_mm,
                "used_mm": self.used_mm, "jobs": self.jobs, "factor": self.factor}

    @staticmethod
    def from_dict(data: dict) -> "RollState":
        return RollState(tape_id=data["tape_id"], started=data["started"], length_mm=data["length_mm"],
                          used_mm=data["used_mm"], jobs=data["jobs"], factor=data.get("factor", 1.0))


def config_tape_id() -> str:
    """Das in der Config gewählte Band; bei unlesbarer Config das Standardband."""
    from tapesmith.tape.profiles import DEFAULT_TAPE, current_tape

    try:
        return current_tape(config.load_config()).id
    except (ValueError, OSError):
        return DEFAULT_TAPE


class RollStore:
    def __init__(self, path: Path | None = None, *,
                 tape: Callable[[], str] | None = None) -> None:
        self.path = Path(path) if path is not None else paths.app_dir() / "rolls.json"
        self._tape = tape if tape is not None else config_tape_id

    def _tape_id(self, tape_id: str | None) -> str:
        return tape_id if tape_id is not None else self._tape()

    def _load(self) -> dict:
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        data.setdefault("rolls", {})
        data.setdefault("factors", {})
        data.setdefault("factor", 1.0)
        data.setdefault("history", [])
        legacy = data.pop("current", None)   # altes Format: eine globale Rolle
        if legacy is not None:
            data["rolls"].setdefault(legacy["tape_id"], legacy)
        return data

    def _save(self, data: dict) -> None:
        lock_path = self.path.with_name(self.path.name + ".lock")
        with FileLock(lock_path):
            atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def current(self, tape_id: str | None = None) -> RollState | None:
        """Aktuelle Rolle des Bandes `tape_id` (Default: Band aus der Config)."""
        raw = self._load()["rolls"].get(self._tape_id(tape_id))
        return RollState.from_dict(raw) if raw is not None else None

    def new_roll(self, tape_id: str, length_mm: float = ROLL_LENGTH_MM, now: datetime | None = None) -> RollState:
        """Neue Rolle für `tape_id`; übernimmt den für dieses Band (sonst zuletzt) gelernten Faktor."""
        data = self._load()
        factor = float(data["factors"].get(tape_id, data["factor"]))
        state = RollState(tape_id=tape_id, started=(now or datetime.now()).isoformat(),
                           length_mm=length_mm, used_mm=0.0, jobs=0, factor=factor)
        data["rolls"][tape_id] = state.to_dict()
        self._save(data)
        return state

    def consume(self, mm: float, tape_id: str | None = None) -> RollState | None:
        """Zieht `mm` von der Rolle des Bandes ab. Ohne Rolle für dieses Band: `None`, kein Fehler."""
        tape = self._tape_id(tape_id)
        data = self._load()
        raw = data["rolls"].get(tape)
        if raw is None:
            return None
        current = RollState.from_dict(raw)
        state = RollState(tape_id=current.tape_id, started=current.started, length_mm=current.length_mm,
                           used_mm=current.used_mm + mm, jobs=current.jobs + 1, factor=current.factor)
        data["rolls"][tape] = state.to_dict()
        self._save(data)
        return state

    def mark_empty(self, at_mm: float | None = None, tape_id: str | None = None) -> float:
        """Korrektur „Rolle war leer bei `at_mm`" (Default: `used_mm`). Lernt
        `factor = at_mm / length_mm` (geklemmt 0,5..1,5) für dieses Band, beendet dessen Rolle
        (`current()` -> `None`) und gibt den gelernten Faktor zurück."""
        tape = self._tape_id(tape_id)
        data = self._load()
        raw = data["rolls"].get(tape)
        if raw is None:
            raise ValueError(_t("Keine Rolle erfasst, nichts zu korrigieren"))
        state = RollState.from_dict(raw)
        at = state.used_mm if at_mm is None else at_mm
        factor = (at / state.length_mm) if state.length_mm else 1.0
        factor = max(_FACTOR_MIN, min(_FACTOR_MAX, factor))
        data["history"].append(state.to_dict())
        del data["rolls"][tape]
        data["factors"][tape] = factor
        data["factor"] = factor
        self._save(data)
        return factor

    def all_rolls(self) -> list[tuple[RollState, bool]]:
        """Alle Rollen für die Statistik: beendete aus der Historie (`True`) und die
        aktuelle je Band (`False`), nach `started` aufsteigend sortiert."""
        data = self._load()
        items: list[tuple[RollState, bool]] = []
        for raw in data["history"]:
            items.append((RollState.from_dict(raw), True))
        for raw in data["rolls"].values():
            items.append((RollState.from_dict(raw), False))
        items.sort(key=lambda pair: pair[0].started)
        return items

    def remaining_mm(self, tape_id: str | None = None) -> float | None:
        state = self.current(tape_id)
        if state is None:
            return None
        return max(0.0, state.length_mm * state.factor - state.used_mm)

    def spread_mm(self, tape_id: str | None = None) -> float | None:
        state = self.current(tape_id)
        if state is None:
            return None
        return 0.05 * state.used_mm + 1.0 * state.jobs + 0.02 * state.length_mm

    def check(self, job_tape_mm: float, tape_id: str | None = None) -> list[str]:
        """Warnungen vor einem Druck: Rest bekannt und Auftrag > Rest -> „reicht wahrscheinlich
        nicht"; sonst wenn danach < `LOW_REST_MM` übrig -> „fast leer"."""
        remaining = self.remaining_mm(tape_id)
        if remaining is None:
            return []
        if job_tape_mm > remaining:
            return [_t("Band reicht wahrscheinlich nicht: Auftrag ca. {job_tape_mm:.0f} mm, Rest ca. {remaining:.0f} mm (geschätzt)", job_tape_mm=job_tape_mm, remaining=remaining)]
        rest_danach = remaining - job_tape_mm
        if rest_danach < LOW_REST_MM:
            return [_t("Band fast leer: nach dem Druck noch ca. {de} m (geschätzt)", de=_de(rest_danach / 1000))]
        return []

    def summary(self, label_mm: float | None = None, tape_id: str | None = None) -> str:
        tape_id = self._tape_id(tape_id)
        state = self.current(tape_id)
        if state is None:
            return _t("Keine Rolle erfasst: „Neue Rolle“ wählen")
        remaining = self.remaining_mm(tape_id)
        spread = self.spread_mm(tape_id)
        text = _t("noch ca. {de} m (± {de2} m)", de=_de(remaining / 1000), de2=_de(spread / 1000))
        if label_mm:
            count = int(remaining // label_mm)
            text += _t(" ≈ {count} Etiketten à {label_mm:.0f} mm", count=count, label_mm=label_mm)
        return text
