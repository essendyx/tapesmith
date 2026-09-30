"""Gemeinsame Fakes für die Tests des Druckdienstes p12d (kein Druck, keine echten Geräte)."""

from __future__ import annotations

import threading
import time
from datetime import datetime

from PIL import Image

from tapesmith import config as config_mod
from tapesmith.daemon.queue import JobQueue
from tapesmith.daemon.service import PrintService
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel, PrintRequest
from tapesmith.tape.rolls import RollStore
from tapesmith.transport.base import MemoryTransport

PROFILE = load_profile()
INIT_PACKET = PROFILE.init_packets[0]

STATUS_OK = {
    bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
    bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
    bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
}
STATUS_LID_OPEN = {**STATUS_OK, bytes.fromhex("1f1112"): bytes.fromhex("1a0599")}
STATUS_QUERIES = {bytes.fromhex(q) for q in ("1f1108", "1f1111", "1f1112", "1f1107", "1f1109",
                                             "1f1119", "1f110e", "1f1120")}


class NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeNow:
    def __init__(self, now: datetime = datetime(2026, 9, 27, 12, 0, 0)):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def head(mark: int = 0, rows: int = 40) -> Image.Image:
    img = Image.new("1", (PROFILE.head_dots, rows), 255)
    img.putpixel((PROFILE.content_offset + mark, 0), 0)
    return img


def label(mark: int = 0, rows: int = 40) -> PrintLabel:
    return PrintLabel(head(mark, rows))


def request(mark: int = 0, *, source: str = "cli", title: str = "T", rows: int = 40,
            sensitive: bool = False, values: dict | None = None, **kw) -> PrintRequest:
    meta = JobMeta(source=source, kind="text", title=title, sensitive=sensitive, values=values or {})
    return PrintRequest(labels=(label(mark, rows),), meta=meta, **kw)


class Events:
    """Sammelt Ereignisse des Dienstes (thread-sicher)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.items: list[tuple[str, dict]] = []

    def __call__(self, event: str, data: dict) -> None:
        with self._lock:
            self.items.append((event, dict(data)))

    def of(self, event: str) -> list[dict]:
        with self._lock:
            return [d for e, d in self.items if e == event]

    def names(self) -> list[str]:
        with self._lock:
            return [e for e, _ in self.items]


class TransportFactory:
    """Transport-Fabrik `(cfg, profile) -> () -> Transport`; zählt Aufrufe, wirft auf Wunsch."""

    def __init__(self, transport, errors=()):
        self.transport = transport
        self.errors = list(errors)      # der Reihe nach: Ausnahme oder None (= Transport liefern)
        self.built = 0
        self.calls = 0

    def __call__(self, cfg, profile):
        self.built += 1

        def make():
            self.calls += 1
            if self.errors:
                error = self.errors.pop(0)
                if error is not None:
                    raise error
            return self.transport
        return make


class ConfigHolder:
    def __init__(self, config: dict | None = None):
        self.cfg = {**config_mod.DEFAULTS, "transport": "memory", **(config or {})}
        self.error: Exception | None = None

    def __call__(self) -> dict:
        if self.error is not None:
            raise self.error
        return dict(self.cfg)


def make_service(tmp_path, responses=None, config=None, **overrides):
    """(service, transport) mit MemoryTransport, No-op-Lock, Fake-sleep und Stores in tmp_path."""
    transport = overrides.pop("transport", None) or MemoryTransport(STATUS_OK if responses is None else responses)
    kwargs = dict(
        config_loader=ConfigHolder(config),
        profile_loader=load_profile,
        transport_factory=TransportFactory(transport),
        lock_factory=NullLock,
        sleep=lambda s: None,
        history=HistoryStore(tmp_path / "h.db"),
        queue=JobQueue(tmp_path / "q.db"),
        rolls=RollStore(tmp_path / "r.json", tape=lambda: "schwarz-weiss"),
        archive_factory=lambda cfg: None,
        watch_files=False,
    )
    kwargs.update(overrides)
    service = PrintService(**kwargs)
    service._test_stores = (kwargs["history"], kwargs["queue"])
    return service, transport


def close_service(service) -> None:
    service.close()
    for store in getattr(service, "_test_stores", ()):
        try:
            store.close()
        except Exception:
            pass


def wait_until(predicate, timeout: float = 30.0, step: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def split_jobs(written: list[bytes]) -> list[list[bytes]]:
    """Teilt den Schreibstrom an jedem Vorschub in Druckjobs (Statusabfragen herausgefiltert)."""
    jobs: list[list[bytes]] = []
    current: list[bytes] = []
    for data in written:
        if data in STATUS_QUERIES:
            continue
        current.append(data)
        if data == PROFILE.feed_command:
            jobs.append(current)
            current = []
    if current:
        jobs.append(current)
    return jobs
