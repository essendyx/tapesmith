"""HTTP-Server der Web-Oberfläche im Druckdienst (uvicorn in einem eigenen Thread).

Standard: bindet nur 127.0.0.1 (Port `web.port`, Standard 8712, per `TAPESMITH_WEB_PORT`
überschreibbar; 0 = freier Port). Mit `lan.enabled` zusätzlich das LAN: `lan.bind`
`0.0.0.0` ergibt genau einen Socket auf allen Schnittstellen, eine feste Adresse einen zweiten
Socket neben 127.0.0.1 mit demselben Port. Scheitert der LAN-Socket, läuft der Dienst nur lokal
weiter (`ctx.extras["lan_error"]`). Beim Start entsteht `web/session.json` mit Loopback-Port und
zufälligem Sitzungs-Token, beim Beenden wird sie gelöscht.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn

from tapesmith import config as config_mod
from tapesmith.ipc import pipe
from tapesmith.webapi import session
from tapesmith.webapi.access import LanPolicy
from tapesmith.webapi.app import create_app
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.events import EventBroker
from tapesmith.webui import static_dir as default_static_dir
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

DEFAULT_PORT = 8712
LOOPBACK = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"
PORT_ENV = "TAPESMITH_WEB_PORT"
STOP_JOIN_S = 5.0


def _check_port(value, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError(_t("{source}: Port muss eine ganze Zahl 0..65535 sein, ist {value!r}", source=source, value=value))
    return value


def web_settings(cfg: dict, env: Mapping[str, str] = os.environ) -> int:
    """Port aus `cfg["web"]` (Standard 8712); `TAPESMITH_WEB_PORT` hat Vorrang. Die Web-Oberfläche
    läuft immer: ein alter Schlüssel `web.enabled` in config.json wird ignoriert."""
    section = cfg.get("web")
    section = section if isinstance(section, dict) else {}
    port = _check_port(section.get("port", DEFAULT_PORT), "config.json 'web.port'")
    raw = env.get(PORT_ENV)
    if raw is not None and raw.strip() != "":
        try:
            port = int(raw.strip())
        except ValueError:
            raise ValueError(_t("{port_env}: Port muss eine ganze Zahl 0..65535 sein, ist {raw!r}", port_env=PORT_ENV, raw=raw)) from None
        _check_port(port, PORT_ENV)
    return port


def bind_socket(port: int, host: str = LOOPBACK) -> socket.socket:
    """Lauschender Socket auf `host` (Standard 127.0.0.1); unter Windows exklusiv (kein Kapern)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        sock.bind((host, int(port)))
        sock.listen(64)
    except OSError:
        sock.close()
        raise
    return sock


class WebServer:
    def __init__(self, service, *, port: int, home_key: str, static_dir: Path | None = None,
                 token: str | None = None,
                 server_factory: Callable[[uvicorn.Config], Any] = uvicorn.Server,
                 socket_factory: Callable[..., socket.socket] = bind_socket, start_timeout_s: float = 5.0,
                 now: Callable[[], datetime] = datetime.now, lan: LanPolicy | None = None,
                 lan_bind: str | None = None):
        self.service = service
        self.port = int(port)
        self.home_key = home_key
        self.static_dir = static_dir if static_dir is not None else default_static_dir()
        self.token = token or session.load_or_create_token()
        self.ctx: ApiContext | None = None
        self._server_factory = server_factory
        self._socket_factory = socket_factory
        self._start_timeout_s = float(start_timeout_s)
        self._now = now
        self.lan = lan if lan is not None else LanPolicy.disabled()
        self.lan_bind = lan_bind or ALL_INTERFACES
        self._sock: socket.socket | None = None
        self._sockets: list[socket.socket] = []
        self._lan_error: str | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._session_written = False

    @property
    def clients(self) -> int:
        """Offene Ereignis-Ströme (`/api/v1/events`), also offene Oberflächen-Fenster und Tabs."""
        ctx = self.ctx
        return ctx.broker.subscriber_count() if ctx is not None else 0

    def _lan_failed(self, exc: OSError) -> None:
        self._lan_error = str(exc)
        log.warning("LAN-Freigabe nicht möglich, Web-Oberfläche nur lokal: %s", exc)

    def _bind(self) -> None:
        """Bindet die Sockets laut LAN-Freigabe; der erste bestimmt den Port."""
        self._sockets = []
        self._lan_error = None
        if self.lan.enabled and self.lan_bind == ALL_INTERFACES:
            try:
                self._sockets.append(self._socket_factory(self.port, ALL_INTERFACES))
            except OSError as exc:
                self._lan_failed(exc)
        if not self._sockets:
            self._sockets.append(self._socket_factory(self.port))
        self._sock = self._sockets[0]
        self.port = int(self._sock.getsockname()[1])
        if self.lan.enabled and self.lan_bind != ALL_INTERFACES:
            try:
                self._sockets.append(self._socket_factory(self.port, self.lan_bind))
            except OSError as exc:
                self._lan_failed(exc)

    def _listen(self) -> list[str]:
        result = []
        for sock in self._sockets:
            host, port = sock.getsockname()[:2]
            result.append(f"{host}:{port}")
        return result

    def _lan_config(self) -> dict:
        try:
            cfg = self.service.config
        except Exception:  # noqa: BLE001 (nur Momentaufnahme für die Oberfläche)
            cfg = {}
        cfg = cfg if isinstance(cfg, dict) else {}
        keys = config_mod.SECTION_DEFAULTS["lan"]
        return {key: copy.deepcopy(config_mod.setting(cfg, f"lan.{key}")) for key in keys}

    def start(self) -> None:
        try:
            self._bind()
            ctx = ApiContext(service=self.service, home_key=self.home_key, token=self.token,
                             broker=EventBroker(), static_dir=self.static_dir, port=self.port, lan=self.lan)
            ctx.extras["listen"] = self._listen()
            ctx.extras["lan_config"] = self._lan_config()
            if self._lan_error is not None:
                ctx.extras["lan_error"] = self._lan_error
            self.ctx = ctx
            app = create_app(ctx)
            self.service.add_emitter(ctx.broker.publish)
            config = uvicorn.Config(app, log_config=None, access_log=False, lifespan="on",
                                    timeout_graceful_shutdown=2)
            server = self._server_factory(config)
            _disable_signal_handlers(server)
            self._server = server
            self._thread = threading.Thread(target=self._run, name="p12d-web", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + self._start_timeout_s
            while not getattr(server, "started", False):
                if time.monotonic() >= deadline or not self._thread.is_alive() and not server.started:
                    raise RuntimeError(_t("Web-Server ist nicht rechtzeitig gestartet"))
                time.sleep(0.02)
            session.write_session(port=self.port, token=self.token, pid=os.getpid(), home_key=self.home_key,
                                  started=self._now())
            self._session_written = True
            log.info("Web-Oberfläche bereit: http://127.0.0.1:%s/ (lauscht auf %s)", self.port,
                     ", ".join(ctx.extras["listen"]))
        except BaseException:
            self.stop()
            raise

    def _run(self) -> None:
        try:
            self._server.run(sockets=list(self._sockets))
        except Exception:  # noqa: BLE001 (der Dienst läuft ohne Web weiter)
            log.exception("Web-Server beendet mit Fehler")

    def stop(self) -> None:
        ctx, self.ctx = self.ctx, None
        if ctx is not None:
            ctx.broker.close_all()
        server = self._server
        if server is not None:
            server.should_exit = True
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(STOP_JOIN_S)
        if self._session_written:
            session.remove_session(os.getpid())
            self._session_written = False
        if ctx is not None:
            ctx.close()
        sockets, self._sockets, self._sock = self._sockets, [], None
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass


def _disable_signal_handlers(server: Any) -> None:
    """Der Dienst behandelt Signale selbst; uvicorn läuft ohnehin nicht im Haupt-Thread."""
    if hasattr(server, "install_signal_handlers"):
        server.install_signal_handlers = lambda: None
    if hasattr(server, "capture_signals"):
        server.capture_signals = contextlib.nullcontext


def default_web(service) -> WebServer:
    """Web-Server laut Config (läuft immer, nur der Port ist einstellbar)."""
    port = web_settings(service.config)
    cfg = service.config
    return WebServer(service, port=port, home_key=pipe.home_key(), lan=LanPolicy.from_config(cfg),
                     lan_bind=config_mod.setting(cfg, "lan.bind"))
