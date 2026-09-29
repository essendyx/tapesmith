"""Langlebige Kernobjekte der GUI (ohne Qt): Geräteprofil, Verlauf, Verbindungsmanager,
Druck-Pipeline mit Fehldruckschutz und Zähler, gebaut aus `config.json`.

`build_services` öffnet keine Verbindung; das geschieht bei Bedarf bzw. per Vorverbinden.
Callbacks aus Manager- und Pipeline-Threads laufen über `Relay`s, an die sich beliebig viele
Abonnenten (z. B. der Druck-Controller) hängen können.

Gedruckt wird über `AppServices.backend`: den Druckdienst (`DaemonBackend`) oder,
ohne Dienst, ein `LocalBackend` über die hier gebauten Manager-/Pipeline-Objekte.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tapesmith import config as config_mod
from tapesmith import paths
from tapesmith.archive import archive_hook
from tapesmith.connection import ConnectionManager
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.guard import Debouncer, GuardPolicy, load_policy
from tapesmith.history import HistoryStore
from tapesmith.ipc import backend as ipc_backend
from tapesmith.ipc.backend import LocalBackend, PrintBackend, QueueOps, make_backend
from tapesmith.numbering import counter_store
from tapesmith.pipeline import PrintPipeline, manager_runner
from tapesmith.printer import PrinterSession
from tapesmith.printhooks import print_hooks
from tapesmith.tape.profiles import TapeProfile, current_tape, find_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.templates.fill import CounterStore
from tapesmith.transport.base import Transport
from tapesmith.transport.resolve import open_transport


class Relay:
    """Thread-sichere Rückruf-Verteilung (Manager-/Pipeline-Callbacks → beliebig viele Abonnenten)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None]) -> None:
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    def __call__(self, *args) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:
                pass  # ein fehlerhafter Abonnent darf die anderen (und den Worker) nicht stören


@dataclass
class AppServices:
    config: dict
    profile: DeviceProfile
    history: HistoryStore
    manager: ConnectionManager
    pipeline: PrintPipeline
    debouncer: Debouncer
    policy: GuardPolicy
    counters: CounterStore
    state_relay: Relay
    warning_relay: Relay
    cut_pause_relay: Relay = field(default_factory=Relay)
    rolls: RollStore = field(default_factory=RollStore)
    backend: PrintBackend | None = None     # nach build_services immer gesetzt
    _closed: bool = field(default=False, repr=False)

    def tape(self) -> TapeProfile:
        """Aktuell gewähltes Band, aus der Config (`current_tape`)."""
        return current_tape(self.config)

    def set_tape(self, tape_id: str,
                save: Callable[[dict], dict] = config_mod.save_config) -> TapeProfile:
        """Band wechseln: unbekannte `tape_id` -> `ValueError`, nichts gespeichert."""
        find_tape(tape_id)
        saved = save({"tape": {"current": tape_id}})
        self.config.update(saved)
        self._reload_backend()
        return find_tape(tape_id)

    def queue_ops(self) -> QueueOps | None:
        """Warteschlange des Druckdienstes; ohne Dienst `None`."""
        return self.backend.queue_ops() if self.backend is not None else None

    def uses_daemon(self) -> bool:
        return self.backend is not None and self.backend.kind == "daemon"

    def _reload_backend(self) -> None:
        """Dienst liest die Konfiguration neu; ein nicht erreichbarer Dienst bricht nichts ab
        (die Einstellungsseite meldet Fehler über einen eigenen `backend.reload()`)."""
        if self.backend is None:
            return
        try:
            self.backend.reload()
        except Exception:  # noqa: BLE001 (lokale Änderung gilt trotzdem)
            pass

    def reload_policy(self, *, reload_backend: bool = True) -> GuardPolicy:
        """Fehldruckschutz neu aus der Config laden. Wirkt ab dem nächsten Druck."""
        self.policy = load_policy(self.config)
        self.pipeline.set_policy(self.policy)
        if reload_backend:
            self._reload_backend()
        return self.policy

    def reload_profile(self) -> DeviceProfile:
        """Geräteprofil (mit Kalibrierung) neu laden. Gilt ab der nächsten Sitzung."""
        self.profile = load_profile(calibration_path=paths.calibration_path())
        self.pipeline.set_profile(self.profile)
        self.manager.set_profile(self.profile)
        self._reload_backend()
        return self.profile

    def set_cut_pause(self, seconds: float | None) -> None:
        self.pipeline.set_cut_pause(seconds)
        self._reload_backend()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.backend is not None:
                try:
                    self.backend.close()
                except Exception:  # noqa: BLE001 (Aufräumen geht weiter)
                    pass
            self.manager.close()
        finally:
            self.history.close()


def default_transport_factory(cfg: dict) -> Callable[[], Transport]:
    return lambda: open_transport(cfg["transport"], cfg["mac"], None,
                                  open_timeout=float(cfg["connect_timeout_s"]))


def build_services(*, config: dict | None = None, profile: DeviceProfile | None = None,
                   history: HistoryStore | None = None,
                   transport_factory: Callable[[], Transport] | None = None,
                   lock_factory: Callable[[], Any] | None = None,
                   session_factory: Callable[..., PrinterSession] | None = None,
                   sleep: Callable[[float], None] | None = None,
                   now: Callable[[], datetime] = datetime.now,
                   debounce_s: float = 1.5,
                   rolls: RollStore | None = None,
                   backend: PrintBackend | None = None,
                   use_daemon: bool | None = None) -> AppServices:
    """Baut die Dienste. `backend` übergeben -> genau dieses; sonst entscheidet `use_daemon`
    (None: Dienst nur ohne eigene Transport-Fabrik und laut Config/`TAPESMITH_NO_DAEMON`)."""
    cfg = config if config is not None else config_mod.load_config()
    if use_daemon is None:
        use_daemon = transport_factory is None and ipc_backend.use_daemon(cfg)
    if profile is None:
        profile = load_profile(calibration_path=paths.calibration_path())
    if history is None:
        history = HistoryStore()
    if transport_factory is None:
        transport_factory = default_transport_factory(cfg)
    if rolls is None:
        rolls = RollStore(tape=lambda: current_tape(cfg).id)

    state_relay = Relay()
    warning_relay = Relay()
    cut_pause_relay = Relay()
    extra: dict[str, Any] = {}
    if lock_factory is not None:
        extra["lock_factory"] = lock_factory
    if session_factory is not None:
        extra["session_factory"] = session_factory
    if sleep is not None:
        extra["sleep"] = sleep
    manager = ConnectionManager(transport_factory, profile,
                                idle_timeout_s=float(cfg["idle_timeout_s"]),
                                connect_timeout_s=float(cfg["connect_timeout_s"]),
                                on_state=state_relay, **extra)
    policy = load_policy(cfg)
    debouncer = Debouncer(debounce_s)
    pipeline = PrintPipeline(profile, manager_runner(manager), history=history, policy=policy,
                             debouncer=debouncer, preflight=True, on_warning=warning_relay, now=now,
                             on_cut_pause=cut_pause_relay, cut_pause_s=cfg.get("cut_pause_s"),
                             **print_hooks(rolls, lambda: current_tape(cfg).id))
    counters: CounterStore = counter_store(cfg)
    hook = archive_hook(cfg)

    def local(reason: str = "") -> LocalBackend:
        return LocalBackend(pipeline, warning_relay=warning_relay, cut_pause_relay=cut_pause_relay,
                            state_relay=state_relay, manager=manager,
                            post_hooks=[hook] if hook is not None else [], fallback_reason=reason)

    if backend is None:
        if use_daemon:
            backend = make_backend(cfg, profile, client="gui", local_factory=local, planner=pipeline.plan)
        else:
            backend = local("")
    return AppServices(config=cfg, profile=profile, history=history, manager=manager,
                       pipeline=pipeline, debouncer=debouncer, policy=policy, counters=counters,
                       state_relay=state_relay, warning_relay=warning_relay,
                       cut_pause_relay=cut_pause_relay, rolls=rolls, backend=backend)
