"""Fehldruckschutz-Kern: Entprellung, Job-Sperre, Rückfrage- und Obergrenzen,
Kontingente für nicht-interaktive Quellen. Reine Logik, keine Ein-/Ausgabe."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from PIL import Image

from tapesmith.jobs import SOURCES
from tapesmith.i18n import _t

INTERACTIVE_SOURCES = frozenset({"cli", "gui", "hotkey"})


@dataclass(frozen=True)
class Quota:
    jobs_per_hour: int
    mm_per_hour: float


DEFAULT_QUOTAS: dict[str, Quota] = {
    "api": Quota(20, 1000.0),
    "mcp": Quota(20, 1000.0),
    "mqtt": Quota(10, 500.0),
    "hotfolder": Quota(30, 1500.0),
}


@dataclass(frozen=True)
class GuardPolicy:
    confirm_label_mm: float = 150.0
    confirm_copies: int = 5
    max_label_mm: float = 500.0
    max_request_mm: float = 2000.0
    max_copies: int = 50
    quotas: Mapping[str, Quota] = field(default_factory=lambda: dict(DEFAULT_QUOTAS))

    def __hash__(self) -> int:  # frozen, aber quotas ist ein dict -> nicht hashbar
        raise TypeError(_t("GuardPolicy ist nicht hashbar (enthält dict 'quotas')"))


@dataclass(frozen=True)
class JobRequest:
    source: str
    label_mm: float
    tape_mm: float
    copies: int
    labels: int = 1


@dataclass(frozen=True)
class Usage:
    jobs: int = 0
    tape_mm: float = 0.0


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    needs_confirmation: bool
    reasons: tuple[str, ...]

    def message(self) -> str:
        return "; ".join(self.reasons)


class GuardRejected(ValueError):
    def __init__(self, decision: GuardDecision) -> None:
        super().__init__(decision.message())
        self.decision = decision


class JobRunning(RuntimeError):
    pass


def evaluate(
    request: JobRequest,
    policy: GuardPolicy | None = None,
    usage: Usage = Usage(),
) -> GuardDecision:
    if request.source not in SOURCES:
        raise ValueError(_t("Unbekannte Quelle '{source}' (erlaubt: {items})", source=request.source, items=', '.join(SOURCES)))
    if policy is None:
        policy = GuardPolicy()

    hard_reasons: list[str] = []

    if request.copies > policy.max_copies:
        hard_reasons.append(
            _t("{copies} Kopien überschreiten die Obergrenze von {max_copies}", copies=request.copies, max_copies=policy.max_copies)
        )
    if request.label_mm > policy.max_label_mm:
        hard_reasons.append(
            _t("Label mit {label_mm:.0f} mm überschreitet die Obergrenze von {max_label_mm:.0f} mm", label_mm=request.label_mm, max_label_mm=policy.max_label_mm)
        )
    if request.tape_mm > policy.max_request_mm:
        hard_reasons.append(
            _t("Auftrag braucht ca. {tape_mm:.0f} mm Band, Obergrenze {max_request_mm:.0f} mm", tape_mm=request.tape_mm, max_request_mm=policy.max_request_mm)
        )

    quota = policy.quotas.get(request.source)
    if quota is not None:
        if usage.jobs + 1 > quota.jobs_per_hour:
            hard_reasons.append(
                _t("Kontingent für {source} erschöpft: {jobs_per_hour} Jobs pro Stunde", source=request.source, jobs_per_hour=quota.jobs_per_hour)
            )
        if usage.tape_mm + request.tape_mm > quota.mm_per_hour:
            hard_reasons.append(
                _t("Kontingent für {source} erschöpft: {mm_per_hour:.0f} mm pro Stunde", source=request.source, mm_per_hour=quota.mm_per_hour)
            )

    if hard_reasons:
        return GuardDecision(allowed=False, needs_confirmation=False, reasons=tuple(hard_reasons))

    confirm_reasons: list[str] = []
    if request.label_mm > policy.confirm_label_mm:
        confirm_reasons.append(_t("Label ist {label_mm:.0f} mm lang", label_mm=request.label_mm))
    if request.copies > policy.confirm_copies:
        confirm_reasons.append(_t("{copies} Kopien", copies=request.copies))

    if confirm_reasons:
        if request.source in INTERACTIVE_SOURCES:
            return GuardDecision(allowed=True, needs_confirmation=True, reasons=tuple(confirm_reasons))
        confirm_reasons.append(_t("Quelle {source} kann nicht bestätigen", source=request.source))
        return GuardDecision(allowed=False, needs_confirmation=False, reasons=tuple(confirm_reasons))

    return GuardDecision(allowed=True, needs_confirmation=False, reasons=())


_POLICY_FIELDS = {"confirm_label_mm", "confirm_copies", "max_label_mm", "max_request_mm", "max_copies"}


def load_policy(cfg: dict) -> GuardPolicy:
    raw = cfg.get("guard", {})
    kwargs: dict = {}
    quotas = dict(DEFAULT_QUOTAS)

    for key, value in raw.items():
        if key == "quotas":
            if not isinstance(value, Mapping):
                raise ValueError(_t("config.json: guard.{key} muss ein Objekt sein", key=key))
            for source, q in value.items():
                jobs_per_hour = q["jobs_per_hour"]
                mm_per_hour = q["mm_per_hour"]
                if jobs_per_hour < 0 or mm_per_hour < 0:
                    raise ValueError(_t("config.json: guard.quotas.{source} darf nicht negativ sein", source=source))
                quotas[source] = Quota(jobs_per_hour, float(mm_per_hour))
            continue
        if key not in _POLICY_FIELDS:
            raise ValueError(_t("config.json: guard.{key} ist unbekannt", key=key))
        if value < 0:
            raise ValueError(_t("config.json: guard.{key} darf nicht negativ sein", key=key))
        kwargs[key] = value

    kwargs["quotas"] = quotas
    return GuardPolicy(**kwargs)


class Debouncer:
    def __init__(
        self,
        min_interval_s: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._running_lock = threading.Lock()

    def accept(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            cutoff = now - self._min_interval_s * 10
            for stale_key in [k for k, t in self._last.items() if t < cutoff]:
                del self._last[stale_key]

            last = self._last.get(key)
            if last is not None and now - last < self._min_interval_s:
                return False
            self._last[key] = now
            return True

    @contextmanager
    def running(self) -> Iterator[None]:
        if not self._running_lock.acquire(blocking=False):
            raise JobRunning(_t("Es läuft bereits ein Druckauftrag"))
        try:
            yield
        finally:
            self._running_lock.release()


def content_key(source: str, heads: Sequence[Image.Image]) -> str:
    digest = hashlib.sha256()
    digest.update(source.encode("utf-8"))
    for head in heads:
        digest.update(str(head.size).encode("utf-8"))
        digest.update(head.tobytes())
    return digest.hexdigest()
