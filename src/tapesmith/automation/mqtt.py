"""Addon mqtt: Home-Assistant-Anbindung per MQTT-Discovery.

Meldet den Druckdienst als Gerät "Labeldrucker P12" bei Home Assistant an (Mosquitto,
`mqtt.host`/`mqtt.port`). Entitäten: Verbindung, Akku und Deckel (nur wenn im Geräteprofil
verifiziert), Warteschlange, Knopf "Testlabel". Über `<base>/print/set` lässt sich eine Vorlage
mit Werten drucken; das Ergebnis kommt auf `<base>/print/result`. Zugangsdaten nur über eine
Secret-Referenz (`tapesmith.secretref`), nie im Klartext. `paho-mqtt` 2.x (`CallbackAPIVersion.
VERSION2`); der Netzwerk-Thread von paho druckt nie selbst, dafür gibt es einen eigenen
Worker-Thread mit begrenzter Warteschlange.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from collections.abc import Callable, Sequence

from tapesmith import __version__ as TAPESMITH_VERSION
from tapesmith import config as config_mod
from tapesmith import secretref, sourcelimits
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

# Höchstens so viele Druckaufträge warten im Worker; weitere werden mit "abgelehnt" verworfen.
MAX_QUEUED_JOBS = 20
# Zustand höchstens einmal in dieser Zeitspanne senden (Sekunden), außer nach (Wieder-)Verbindung.
STATE_MIN_INTERVAL_S = 1.0
# Standardanzahl Kopien, wenn "copies" in der Druck-Nachricht fehlt.
DEFAULT_COPIES = 5

DiscoveryMessage = tuple[str, dict | None, bool]  # (topic, payload | None für Entfernen, retain)


def _default_client_factory(client_id: str):
    import paho.mqtt.client as mqtt_client

    return mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id)


class MqttBridge:
    """MQTT-Discovery, Zustand und Druck-Topics für Home Assistant."""

    name = "mqtt"

    def __init__(self, facade, cfg: dict, *, client_factory: Callable[[str], object] | None = None,
                 secret_reader: Callable[..., str] = secretref.read_secret,
                 clock: Callable[[], float] = time.monotonic, hostname: str | None = None):
        self.facade = facade
        self.cfg = cfg
        self._client_factory = client_factory or _default_client_factory
        self._secret_reader = secret_reader
        self._clock = clock
        self._hostname = hostname or socket.gethostname()

        self._base = config_mod.setting(cfg, "mqtt.base_topic")
        self._prefix = config_mod.setting(cfg, "mqtt.discovery_prefix")
        self._host = config_mod.setting(cfg, "mqtt.host")
        self._port = config_mod.setting(cfg, "mqtt.port")
        self._username = config_mod.setting(cfg, "mqtt.username")
        self._password_ref = config_mod.setting(cfg, "mqtt.password_ref")
        self._templates = tuple(config_mod.setting(cfg, "mqtt.templates"))
        self._tls = config_mod.setting(cfg, "mqtt.tls")
        self._keepalive = int(config_mod.setting(cfg, "mqtt.keepalive_s"))

        self._lock = threading.RLock()
        self._client = None
        self._started = False
        self._connected = False
        self._error: str | None = None

        self._last_state_payload: dict | None = None
        self._last_state_sent_at: float | None = None
        self._pending_state = False

        self._jobs: queue.Queue = queue.Queue(maxsize=MAX_QUEUED_JOBS)
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ---------- Themenpfade ----------

    def _topic(self, suffix: str) -> str:
        return f"{self._base}/{suffix}"

    def _topic_availability(self) -> str:
        return self._topic("availability")

    def _topic_state(self) -> str:
        return self._topic("state")

    def _topic_print_set(self) -> str:
        return self._topic("print/set")

    def _topic_print_result(self) -> str:
        return self._topic("print/result")

    def _topic_test_press(self) -> str:
        return self._topic("test/press")

    def _client_id(self) -> str:
        return f"tapesmith-{self._hostname}"

    # ---------- Lebenszyklus (Addon-Schnittstelle) ----------

    def start(self) -> None:
        if not self._host:
            with self._lock:
                self._error = _t("mqtt.host ist nicht gesetzt (Adresse des MQTT-Brokers eintragen)")
                self._started = False
            log.error("MQTT: kein Broker eingetragen (mqtt.host)")
            return
        password = None
        if self._password_ref:
            try:
                password = self._secret_reader(self._password_ref)
            except secretref.SecretMissing as exc:
                with self._lock:
                    self._error = str(exc)
                    self._started = False
                log.error("MQTT: Kennwort nicht verfügbar: %s", exc)
                return

        client = self._client_factory(self._client_id())
        if self._username:
            client.username_pw_set(self._username, password)
        client.will_set(self._topic_availability(), "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=2, max_delay=120)
        if self._tls:
            client.tls_set()
        client.connect_async(self._host, self._port, keepalive=self._keepalive)
        client.loop_start()

        with self._lock:
            self._client = client
            self._error = None
            self._started = True
            self._connected = False
            self._last_state_payload = None
            self._last_state_sent_at = None
            self._pending_state = False

        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="tapesmith-mqtt", daemon=True)
        self._worker.start()
        self.facade.subscribe(self._handle_event)

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            client = self._client
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            # Warteschlange voll: das laufende Element leeren, dann den Sentinel nachreichen.
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                pass
            self._jobs.put_nowait(None)
        if self._worker is not None:
            self._worker.join(timeout=5)
            self._worker = None
        if client is not None:
            try:
                client.publish(self._topic_availability(), "offline", qos=0, retain=True)
            except Exception as exc:  # noqa: BLE001: Abmelden darf das Stoppen nicht verhindern
                log.warning("MQTT: 'offline' beim Stoppen nicht gesendet: %s", exc)
            client.loop_stop()
            client.disconnect()
        with self._lock:
            self._client = None
            self._started = False
            self._connected = False

    def status(self) -> dict:
        with self._lock:
            error = self._error
            running = self._started and error is None
            if error:
                detail = error
            elif self._connected:
                detail = _t("verbunden mit {host}:{port}", host=self._host, port=self._port)
            else:
                detail = _t("getrennt ({host}:{port})", host=self._host, port=self._port)
            return {"name": self.name, "running": running, "error": error, "detail": detail}

    # ---------- Discovery ----------

    def discovery_messages(self) -> list[DiscoveryMessage]:
        """`(topic, payload, retain)` je Entität; `payload=None` entfernt eine nicht (mehr)
        verifizierte Entität (leerer retained Payload)."""
        device = {"identifiers": [f"tapesmith_{self._hostname}"], "name": "Labeldrucker P12",
                  "manufacturer": "Phomemo", "model": "P12", "sw_version": TAPESMITH_VERSION}
        availability = self._topic_availability()
        state_topic = self._topic_state()
        verified = set(self.facade.verified())

        def entity(component: str, obj: str, payload: dict | None) -> DiscoveryMessage:
            topic = f"{self._prefix}/{component}/tapesmith/{obj}/config"
            return topic, payload, True

        messages: list[DiscoveryMessage] = [
            entity("binary_sensor", "verbindung", {
                "name": _t("Verbindung"), "unique_id": "tapesmith_verbindung",
                "device_class": "connectivity", "state_topic": state_topic,
                "availability_topic": availability,
                "value_template": "{{ 'ON' if value_json.connected else 'OFF' }}",
                "device": device,
            }),
        ]

        messages.append(entity("sensor", "akku", {
            "name": _t("Akku"), "unique_id": "tapesmith_akku", "device_class": "battery",
            "unit_of_measurement": "%", "state_class": "measurement", "state_topic": state_topic,
            "availability_topic": availability, "value_template": "{{ value_json.battery }}",
            "device": device,
        } if "battery" in verified else None))

        messages.append(entity("binary_sensor", "deckel", {
            "name": _t("Deckel"), "unique_id": "tapesmith_deckel", "device_class": "opening",
            "state_topic": state_topic, "availability_topic": availability,
            # Ein unbekannter Deckelzustand (lid_open: null) ist kein OFF: die Vorlage liefert
            # dafuer die Jinja-Sentinel `none`, Home Assistant zeigt dann unbekannt statt "zu".
            "value_template": ("{% if value_json.lid_open is none %}{{ none }}{% else %}"
                               "{{ 'ON' if value_json.lid_open else 'OFF' }}{% endif %}"),
            "device": device,
        } if "lid" in verified else None))

        messages.append(entity("sensor", "warteschlange", {
            "name": _t("Warteschlange"), "unique_id": "tapesmith_warteschlange",
            "unit_of_measurement": _t("Aufträge"), "state_topic": state_topic,
            "availability_topic": availability, "value_template": "{{ value_json.queue }}",
            "icon": "mdi:tray-full", "device": device,
        }))

        messages.append(entity("button", "testlabel", {
            "name": _t("Testlabel"), "unique_id": "tapesmith_testlabel",
            "command_topic": self._topic_test_press(), "availability_topic": availability,
            "icon": "mdi:label-outline", "device": device,
        }))

        return messages

    # ---------- Zustand ----------

    def state_payload(self) -> dict:
        """`{"connected", "battery", "lid_open", "queue"}` genau nach dem festgelegten Pfad
        `facade.status()["report"]["status"]["values"][...]["value"]`."""
        state = self.facade.state()
        connected = state.get("state") == "verbunden"

        report = self.facade.status().get("report") or {}
        status = report.get("status") or {}
        values = status.get("values") or {}
        verified = set(self.facade.verified())

        battery = None
        if "battery" in verified:
            raw = values.get("battery", {}).get("value")
            if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 100:
                battery = raw

        lid_open = None
        if "lid" in verified:
            raw = values.get("lid", {}).get("value")
            if raw in ("offen", "zu"):
                lid_open = raw == "offen"

        jobs = self.facade.queue().get("jobs", [])
        queue_n = sum(1 for job in jobs if job.get("state") in ("wartet", "läuft"))

        return {"connected": connected, "battery": battery, "lid_open": lid_open, "queue": queue_n}

    def _handle_event(self, event: str, _data: dict) -> None:
        if event in ("state", "status", "queue", "job"):
            self._publish_state()

    def _publish_state(self, *, force: bool = False) -> None:
        with self._lock:
            if self._client is None and not force:
                return
            payload = self.state_payload()
            now = self._clock()
            if not force and payload == self._last_state_payload:
                return
            if (not force and self._last_state_sent_at is not None
                    and now - self._last_state_sent_at < STATE_MIN_INTERVAL_S):
                self._pending_state = True
                return
            self._send_state(payload, now)

    def _send_state(self, payload: dict, now: float) -> None:
        self._last_state_payload = payload
        self._last_state_sent_at = now
        self._pending_state = False
        client = self._client
        if client is not None:
            client.publish(self._topic_state(), json.dumps(payload, ensure_ascii=False), qos=0, retain=True)

    def _flush_pending_state(self) -> None:
        with self._lock:
            if not self._pending_state or self._client is None:
                return
            now = self._clock()
            if (self._last_state_sent_at is not None
                    and now - self._last_state_sent_at < STATE_MIN_INTERVAL_S):
                return
            payload = self.state_payload()
            self._pending_state = False
            if payload == self._last_state_payload:
                return
            self._send_state(payload, now)

    # ---------- paho-Callbacks (Netzwerk-Thread) ----------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        success = reason_code == 0 or getattr(reason_code, "value", 0) == 0
        if not success:
            with self._lock:
                self._connected = False
                self._error = _t("Verbindung abgelehnt: {reason_code}", reason_code=reason_code)
            log.error("MQTT: Verbindung abgelehnt: %s", reason_code)
            return
        with self._lock:
            self._connected = True
            self._error = None
        for topic, payload, retain in self.discovery_messages():
            client.publish(topic, "" if payload is None else json.dumps(payload, ensure_ascii=False),
                           qos=0, retain=retain)
        client.publish(self._topic_availability(), "online", qos=0, retain=True)
        client.subscribe(self._topic_print_set(), qos=1)
        client.subscribe(self._topic_test_press(), qos=1)
        with self._lock:
            self._last_state_payload = None  # nach (Wieder-)Verbindung immer senden
        self._publish_state(force=True)

    def _on_message(self, client, userdata, msg) -> None:
        topic = getattr(msg, "topic", None)
        payload = getattr(msg, "payload", b"")
        if topic == self._topic_print_set():
            self._handle_print_set(payload)
        elif topic == self._topic_test_press():
            self._submit_job({"kind": "test"})

    def _on_disconnect(self, client, userdata, flags, reason_code=None, properties=None) -> None:
        with self._lock:
            self._connected = False

    # ---------- Druck ----------

    def _handle_print_set(self, payload: bytes | str) -> None:
        try:
            text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
            data = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            self._publish_result("abgelehnt", "", _t("Nachricht ist kein gültiges JSON"))
            return
        if not isinstance(data, dict):
            self._publish_result("abgelehnt", "", _t("Nachricht muss ein JSON-Objekt sein"))
            return

        template = data.get("template")
        if not isinstance(template, str) or not template:
            self._publish_result("abgelehnt", "", _t("Feld 'template' fehlt oder ist leer"))
            return
        if self._templates and template not in self._templates:
            self._publish_result("abgelehnt", template, _t("Vorlage '{template}' ist für MQTT nicht freigegeben", template=template))
            return

        values = data.get("values", {})
        if values is None:
            values = {}
        if not isinstance(values, dict):
            self._publish_result("abgelehnt", template, _t("Feld 'values' muss ein Objekt sein"))
            return

        copies = _normalize_copies(data.get("copies", DEFAULT_COPIES))
        cfg = self.facade.config()
        error = sourcelimits.copies_error(cfg, "mqtt", copies)
        if error:
            self._publish_result("abgelehnt", template, error)
            return

        self._submit_job({"kind": "template", "template": template, "values": values, "copies": copies})

    def _submit_job(self, job: dict) -> None:
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            title = job.get("template") or _t("Testlabel")
            self._publish_result(
                "abgelehnt", title,
                _t("Warteschlange voll (höchstens {max_queued_jobs} wartende Aufträge)", max_queued_jobs=MAX_QUEUED_JOBS))

    def _worker_loop(self) -> None:
        while True:
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                self._flush_pending_state()
                if self._stop_event.is_set():
                    return
                continue
            if job is None:
                return
            self._process_job(job)
            self._flush_pending_state()

    def _process_job(self, job: dict) -> None:
        if job.get("kind") == "test":
            source = {"kind": "test"}
            options = None
            title_fallback = _t("Testlabel")
        else:
            source = {"kind": "template", "template": job["template"], "values": job.get("values", {})}
            options = {"copies": job.get("copies", DEFAULT_COPIES)}
            title_fallback = job["template"]

        try:
            outcome = self.facade.print(source, options, origin="mqtt")
        except Exception as exc:  # noqa: BLE001: der Worker soll trotz Druckfehlern weiterlaufen
            log.error("MQTT: Druck fehlgeschlagen: %s", exc)
            self._publish_result("fehler", title_fallback, str(exc))
            return

        status = outcome.get("status", "fehler")
        title = outcome.get("title") or title_fallback
        self._publish_result(status, title, _outcome_message(outcome))

    def _publish_result(self, status: str, title: str, message: str) -> None:
        payload = json.dumps({"status": status, "title": title, "message": message}, ensure_ascii=False)
        with self._lock:
            client = self._client
        if client is not None:
            client.publish(self._topic_print_result(), payload, qos=0, retain=False)


def _normalize_copies(copies: object) -> object:
    """Home Assistants Nummern-Selektor liefert im Skript-Template ohne `| int`-Filter eine
    Gleitkommazahl (z. B. 1.0 statt 1): eine ganzzahlige Gleitkommazahl gilt wie die ganze Zahl,
    eine echte Nachkommastelle (z. B. 1.5) bleibt ungueltig (sourcelimits.copies_error lehnt sie
    ab)."""
    if isinstance(copies, float) and not isinstance(copies, bool) and copies.is_integer():
        return int(copies)
    return copies


def _outcome_message(outcome: dict) -> str:
    parts: list[str] = list(outcome.get("warnings") or [])
    parts += list(outcome.get("reasons") or [])
    error = outcome.get("error")
    if error:
        text = error.get("message") if isinstance(error, dict) else str(error)
        if text:
            parts.append(text)
    return "; ".join(p for p in parts if p)


def create(facade, cfg: dict) -> MqttBridge | None:
    """Addon oder `None`, wenn `mqtt.enabled` aus ist."""
    if not config_mod.setting(cfg, "mqtt.enabled"):
        return None
    return MqttBridge(facade, cfg)
