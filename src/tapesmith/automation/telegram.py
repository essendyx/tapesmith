"""Addon telegram: Meldungen des Druckdienstes über einen Telegram-Bot.

Meldet nur vier Zustände: Warteschlange hängt, Drucker offline, Druckfehler, Restmeter niedrig
(nichts zu Band leer oder Akku). Jede Art höchstens eine Meldung je Zustandsphase, dann eine
kurze Erholungsmeldung. Ruhezeiten unterdrücken den Versand; Zustände, die danach noch bestehen,
und in der Ruhezeit gesammelte Druckfehler werden anschließend gemeldet.

Das Bot-Token kommt nur zur Laufzeit aus einer Secret-Referenz (`telegram.token_ref`) und erscheint
nie in Meldungen, Logs, Status oder Ausnahmen. Der Versand läuft über einen injizierbaren
HTTP-Poster (`http_post(url, json=..., timeout=...)`, Standard `httpx.post`), Tests senden nie echt.
"""

from __future__ import annotations

import logging
import queue as queue_mod
import re
import socket
import threading
import time
from datetime import datetime, timedelta

from tapesmith import config as config_mod
from tapesmith.i18n import N_, _t

try:  # Secret-Referenzen aus `secretref`; fehlt das Modul, greift der schmale Ersatz unten.
    from tapesmith import secretref as _secretref
except ImportError:  # pragma: no cover: nur ohne `secretref`
    _secretref = None

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"
PREFIX = "Tapesmith: "
RETRY_S = 300.0          # nach einem gescheiterten Versand frühestens so viel später erneut
ERROR_BUNDLE_S = 300.0   # Druckfehler innerhalb dieses Fensters zu einer Meldung zusammenfassen
OFFLINE_STATES = ("offline", "fehler")
ERROR_STATUSES = ("fehler", "unvollständig")

# Standardwerte wie `config.SECTION_DEFAULTS["telegram"]`; Fallback, solange die
# Sektion dort fehlt.
DEFAULTS = {"enabled": False, "token_ref": None,
            "chat_id": None, "quiet_hours": "22:00-07:00", "offline_min": 30, "queue_stuck_min": 15,
            "roll_low_m": 0.5, "notify_queue": True, "notify_offline": True, "notify_error": True,
            "notify_roll": True}

_QUIET_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


# ---------- Secret-Referenzen ----------

if _secretref is not None:
    SecretMissing = _secretref.SecretMissing
else:  # pragma: no cover
    class SecretMissing(ValueError):
        """Ersatz für `secretref.SecretMissing`, falls `secretref` fehlt."""


def read_secret(ref: str, *, keyring_module=None, environ=None) -> str:
    """`secretref.read_secret`; ohne `secretref` ein schmaler Ersatz für `file:`, `env:` und `keyring:`."""
    if _secretref is not None:
        return _secretref.read_secret(ref, keyring_module=keyring_module, environ=environ)
    return _fallback_read_secret(ref, keyring_module=keyring_module, environ=environ)  # pragma: no cover


def describe_ref(ref: str | None) -> str:
    if _secretref is not None:
        return _secretref.describe_ref(ref)
    if not isinstance(ref, str):  # pragma: no cover
        return _t("nicht gesetzt")
    for prefix, label in (("keyring:", _t("Windows-Anmeldeinformationen")), ("file:", _t("Datei")),
                          ("env:", _t("Umgebungsvariable"))):  # pragma: no cover
        if ref.startswith(prefix):
            return f"{label} {ref[len(prefix):]}"
    return _t("nicht gesetzt")  # pragma: no cover


def _fallback_read_secret(ref: str, *, keyring_module=None, environ=None) -> str:  # pragma: no cover
    import os
    from pathlib import Path

    if not isinstance(ref, str):
        raise ValueError(_t("Secret-Referenz ungültig"))
    if ref.startswith("file:"):
        path = ref[len("file:"):]
        p = Path(path)
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, rest = line.partition("=")
            value = rest.strip() if sep and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) else line
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                return value
            break
        raise SecretMissing(_t("Datei {path} fehlt oder ist leer", path=path))
    if ref.startswith("env:"):
        name = ref[len("env:"):]
        value = (environ if environ is not None else os.environ).get(name)
        if not value:
            raise SecretMissing(_t("Umgebungsvariable {name} fehlt oder ist leer", name=name))
        return value
    if ref.startswith("keyring:"):
        service, _, user = ref[len("keyring:"):].partition("/")
        if keyring_module is None:
            try:
                import keyring as keyring_module
            except ImportError:
                raise SecretMissing(_t("Paket keyring fehlt: pip install keyring")) from None
        value = keyring_module.get_password(service, user)
        if not value:
            raise SecretMissing(_t("Kein Wert in den Windows-Anmeldeinformationen für {service}/{user}", service=service, user=user))
        return value
    raise ValueError(_t("Secret-Referenz ungültig: erlaubt keyring:<dienst>/<benutzer>, file:<pfad>, env:<NAME>"))


# ---------- Konfiguration ----------

def setting(cfg: dict, key: str):
    """`config.setting(cfg, "telegram.<key>")` mit Fallback auf `DEFAULTS`."""
    try:
        return config_mod.setting(cfg, f"telegram.{key}")
    except KeyError:
        section = cfg.get("telegram") if isinstance(cfg, dict) else None
        if isinstance(section, dict) and key in section:
            return section[key]
        return DEFAULTS[key]


def _chat_id_missing(chat_id) -> bool:
    return chat_id is None or (isinstance(chat_id, str) and not chat_id.strip())


CHAT_ID_MISSING = N_("Chat-ID fehlt: tapesmith config set telegram.chat_id <id>")


# ---------- Ruhezeiten ----------

def parse_quiet_hours(spec: str | None) -> tuple[int, int] | None:
    """`HH:MM-HH:MM` in Minuten seit Mitternacht (Anfang, Ende); None bei None oder ungültig."""
    if not isinstance(spec, str):
        return None
    m = _QUIET_RE.match(spec.strip())
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if start == end:
        return None
    return start, end


def in_quiet_hours(spec: str | None, when: datetime) -> bool:
    """Liegt `when` in der Ruhezeit? Darf über Mitternacht gehen; Ende gehört nicht dazu."""
    parsed = parse_quiet_hours(spec)
    if parsed is None:
        return False
    start, end = parsed
    t = when.hour * 60 + when.minute
    if start < end:
        return start <= t < end
    return t >= start or t < end


# ---------- Versand ----------

class TelegramError(RuntimeError):
    """Versand gescheitert. Die Meldung enthält nie das Token und nie die API-URL."""


def _scrub(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return re.sub(r"https?://api\.telegram\.org/\S*", "<Telegram-API>", text)


def _default_post(url, json=None, timeout=None):
    import httpx

    return httpx.post(url, json=json, timeout=timeout)


def send_message(token: str, chat_id, text: str, *, http_post=None, timeout_s: float = 10.0) -> None:
    """Sendet `text` an `chat_id`. Fehler (Netz, Status != 200, `ok: false`): `TelegramError`."""
    post = http_post if http_post is not None else _default_post
    url = API.format(token=token)
    try:
        response = post(url, json={"chat_id": chat_id, "text": text}, timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001: Netzfehler jeder Art, Meldung ohne Token/URL
        raise TelegramError(_scrub(_t("Telegram nicht erreichbar ({name}: {exc})", name=type(exc).__name__, exc=exc), token)) from None
    status = getattr(response, "status_code", None)
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = None
    ok = isinstance(payload, dict) and payload.get("ok") is True
    if status == 200 and ok:
        return
    description = payload.get("description") if isinstance(payload, dict) else None
    detail = f"HTTP {status}" + (f", {description}" if description else "")
    raise TelegramError(_scrub(_t("Telegram lehnt ab ({detail})", detail=detail), token))


def _load_token(cfg: dict, reader, **kw) -> str:
    ref = setting(cfg, "token_ref")
    if not ref:
        raise SecretMissing(_t("Bot-Token nicht gesetzt: tapesmith config set telegram.token_ref <referenz>"))
    return reader(ref, **kw)


def send_test(cfg: dict, *, http_post=None, keyring_module=None) -> tuple[bool, str | None]:
    """Testnachricht senden (auch bei `telegram.enabled = false`): (ok, Fehlertext)."""
    chat_id = setting(cfg, "chat_id")
    if _chat_id_missing(chat_id):
        return False, _t(CHAT_ID_MISSING)
    try:
        token = _load_token(cfg, read_secret, keyring_module=keyring_module)
    except ValueError as exc:  # SecretMissing ist ein ValueError, ebenso eine ungültige Referenz
        return False, str(exc)
    text = _t("{prefix}Testnachricht vom Druckdienst auf {gethostname}", prefix=PREFIX, gethostname=socket.gethostname())
    try:
        send_message(token, chat_id, text, http_post=http_post)
    except TelegramError as exc:
        return False, str(exc)
    return True, None


# ---------- Überwachung ----------

def _fmt_m(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class _Phase:
    """Ein Zustand mit genau einer Meldung je Phase (active: Zustand besteht, sent: gemeldet)."""

    __slots__ = ("active", "sent")

    def __init__(self):
        self.active = False
        self.sent = False


class TelegramNotifier:
    """Addon: beobachtet die Fassade und meldet über Telegram."""

    name = "telegram"

    def __init__(self, facade, cfg: dict, *, http_post=None, secret_reader=read_secret,
                 now=datetime.now, clock=time.monotonic, tick_s: float = 30.0, hostname=None):
        self.facade = facade
        self.cfg = cfg
        self._post = http_post
        self._reader = secret_reader
        self._now = now
        self._clock = clock
        self._tick_s = tick_s
        self._hostname = hostname or socket.gethostname()
        self._token: str | None = None
        self._chat_id = None
        self._events: queue_mod.SimpleQueue = queue_mod.SimpleQueue()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._check_lock = threading.Lock()
        self._error: str | None = None
        self._last_failure: float | None = None
        # Zustände
        self._queue = _Phase()
        self._offline = _Phase()
        self._offline_since: float | None = None
        self._roll_armed = True
        self._pending_errors: list[dict] = []
        self._quiet_errors: list[dict] = []
        self._last_error_sent: float | None = None

    # ---------- Einstellungen ----------

    def _opt(self, key: str):
        return setting(self.cfg, key)

    # ---------- Lebenszyklus ----------

    def start(self) -> None:
        chat_id = self._opt("chat_id")
        if _chat_id_missing(chat_id):
            self._error = _t(CHAT_ID_MISSING)
            log.warning("Telegram: %s", self._error)
            return
        try:
            self._token = _load_token(self.cfg, self._reader)
        except ValueError as exc:
            self._error = str(exc)
            log.warning("Telegram: Bot-Token nicht lesbar: %s", self._error)
            return
        self._chat_id = chat_id
        self._error = None
        self.facade.subscribe(self._on_event)
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="p12-telegram", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=15)

    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        if self._error and self._last_failure is not None:
            detail = _t("letzter Versand fehlgeschlagen: {error}", error=self._error)
        elif self._error:
            detail = self._error
        else:
            quiet = self._opt("quiet_hours")
            detail = _t("aktiv, Ruhezeit {quiet}", quiet=quiet) if parse_quiet_hours(quiet) else _t("aktiv, keine Ruhezeit")
        return {"name": self.name, "running": running, "error": self._error, "detail": detail}

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.check()
            except Exception:  # noqa: BLE001: der Thread darf nie sterben
                log.exception("Telegram: Prüfdurchlauf fehlgeschlagen")
            self._wake.wait(self._tick_s)
            self._wake.clear()

    # ---------- Ereignisse ----------

    def _on_event(self, event: str, data: dict) -> None:
        """Nie blockieren: nur einreihen und den Thread wecken."""
        if event in ("job", "state"):
            self._events.put((event, data, self._clock(), self._now()))
            self._wake.set()

    def _drain(self) -> None:
        while True:
            try:
                event, data, at, when = self._events.get_nowait()
            except queue_mod.Empty:
                return
            if not isinstance(data, dict):
                continue
            if event == "state":
                self._observe_state(data.get("state"), at)
            elif event == "job" and data.get("phase") == "fertig" and data.get("status") in ERROR_STATUSES:
                if self._opt("notify_error"):
                    self._pending_errors.append({**data, "_when": when})

    def _observe_state(self, state, at: float) -> None:
        if state in OFFLINE_STATES:
            if self._offline_since is None:
                self._offline_since = at
        elif state == "verbunden":
            self._offline_since = None
        # Übergangszustände (z. B. verbindet) lassen die Offline-Zeit weiterlaufen.

    # ---------- Prüfdurchlauf ----------

    def check(self) -> None:
        with self._check_lock:
            self._drain()
            quiet = in_quiet_hours(self._opt("quiet_hours"), self._now())
            snapshot = self._safe(self.facade.queue) or {}
            waiting = [j for j in snapshot.get("jobs", []) if isinstance(j, dict) and j.get("state") == "wartet"]
            self._check_queue(snapshot, waiting, quiet)
            self._check_offline(waiting, quiet)
            self._check_errors(snapshot, quiet)
            self._check_roll(quiet)

    def _safe(self, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram: Abfrage am Dienst fehlgeschlagen: %s", exc)
            return None

    def _can_send(self) -> bool:
        return self._last_failure is None or self._clock() - self._last_failure >= RETRY_S

    def _send(self, text: str) -> bool:
        if not self._can_send() or not self._token:
            return False
        try:
            send_message(self._token, self._chat_id, text, http_post=self._post)
        except TelegramError as exc:
            self._error = str(exc)
            self._last_failure = self._clock()
            log.warning("Telegram: Versand fehlgeschlagen: %s", self._error)
            return False
        self._error = None
        self._last_failure = None
        return True

    def _phase(self, phase: _Phase, active: bool, enabled: bool, quiet: bool, message, recovery: str) -> None:
        if active:
            phase.active = True
            if enabled and not phase.sent and not quiet and self._send(message()):
                phase.sent = True
            return
        phase.active = False
        if phase.sent and enabled:
            if quiet:
                phase.sent = False   # Erholungsmeldungen während der Ruhezeit entfallen ersatzlos
            elif self._send(recovery):
                phase.sent = False   # nur bei Erfolg als erledigt gelten, sonst erneuter Versuch in check()

    def _check_queue(self, snapshot: dict, waiting: list[dict], quiet: bool) -> None:
        now = self._now()
        created = [c for c in (_parse_iso(j.get("created")) for j in waiting) if c is not None]
        oldest = min(created) if created else None
        age = now - oldest if oldest is not None else None
        stuck = age is not None and age > timedelta(minutes=float(self._opt("queue_stuck_min")))

        def message() -> str:
            minutes = int(age.total_seconds() // 60)
            reason = snapshot.get("waiting_reason") or "unbekannt"
            return (_t("{prefix}Warteschlange hängt seit {minutes} min, {count} Aufträge warten ({reason}).", prefix=PREFIX, minutes=minutes, count=len(waiting), reason=reason))

        self._phase(self._queue, stuck, bool(self._opt("notify_queue")), quiet, message,
                    _t("{prefix}Warteschlange läuft wieder.", prefix=PREFIX))

    def _check_offline(self, waiting: list[dict], quiet: bool) -> None:
        state = self._safe(self.facade.state) or {}
        if state.get("state") is not None:
            self._observe_state(state.get("state"), self._clock())
        since = self._offline_since
        elapsed = self._clock() - since if since is not None else None
        down = elapsed is not None and elapsed >= float(self._opt("offline_min")) * 60

        def message() -> str:
            suffix = _t(", {count} Aufträge warten", count=len(waiting)) if waiting else ""
            return _t("{prefix}Drucker seit {value} min nicht erreichbar{suffix}.", prefix=PREFIX, value=int(elapsed // 60), suffix=suffix)

        # Erholung nur bei "verbunden": erst dann wird `_offline_since` zurückgesetzt.
        self._phase(self._offline, down, bool(self._opt("notify_offline")), quiet, message,
                    _t("{prefix}Drucker wieder erreichbar.", prefix=PREFIX))

    def _sensitive(self, data: dict, snapshot: dict) -> bool:
        if data.get("sensitive") or not (data.get("title") or "").strip():
            return True
        qid = data.get("queue_id")
        if qid is not None:
            for job in snapshot.get("jobs", []):
                if isinstance(job, dict) and job.get("id") == qid and job.get("sensitive"):
                    return True
        return False

    def _title(self, data: dict, snapshot: dict) -> str:
        return _t("(sensibel)") if self._sensitive(data, snapshot) else f"„{data.get('title')}“"

    def _check_errors(self, snapshot: dict, quiet: bool) -> None:
        if quiet:
            self._quiet_errors.extend(self._pending_errors)
            self._pending_errors = []
            return
        if self._quiet_errors:
            last = self._quiet_errors[-1]
            text = (_t("{prefix}{count} Druckfehler während der Ruhezeit, zuletzt {title}.", prefix=PREFIX, count=len(self._quiet_errors), title=self._title(last, snapshot)))
            if self._send(text):
                self._quiet_errors = []
        if not self._pending_errors:
            return
        if self._last_error_sent is not None and self._clock() - self._last_error_sent < ERROR_BUNDLE_S:
            return
        first = self._pending_errors[0]
        more = len(self._pending_errors) - 1
        text = (_t("{prefix}Druckfehler bei {title} (Quelle {value}, Status {get})", prefix=PREFIX, title=self._title(first, snapshot), value=first.get('source') or 'unbekannt', get=first.get('status')) + (_t(" und {more} weitere", more=more) if more else "") + ".")
        if self._send(text):
            self._pending_errors = []
            self._last_error_sent = self._clock()

    def _check_roll(self, quiet: bool) -> None:
        remaining = self._safe(self.facade.remaining_m)
        if remaining is None:
            return
        low = float(self._opt("roll_low_m"))
        if remaining >= low:
            self._roll_armed = True
            return
        if self._roll_armed and self._opt("notify_roll") and not quiet:
            if self._send(_t("{prefix}Rolle fast leer, geschätzt noch {fmt_m} m.", prefix=PREFIX, fmt_m=_fmt_m(remaining))):
                self._roll_armed = False


def create(facade, cfg: dict) -> TelegramNotifier | None:
    """Addon oder None (`telegram.enabled` falsch)."""
    if not setting(cfg, "enabled"):
        return None
    return TelegramNotifier(facade, cfg)
