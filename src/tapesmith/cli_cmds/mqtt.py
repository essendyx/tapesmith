"""`tapesmith mqtt`: Home-Assistant-Discovery anzeigen und die MQTT-Konfiguration prüfen."""

import argparse
import json

from tapesmith import config, secretref
from tapesmith.automation import mqtt
from tapesmith.cli_cmds.base import CliContext
from tapesmith.i18n import N_, _t

COMMAND = "mqtt"
HELP = N_("MQTT/Home-Assistant-Anbindung prüfen (Discovery-Nachrichten, Status)")

# Modul-Attribut für Tests (Fake-Keyring statt echtem Credential Manager).
KEYRING = None


class _ProfileFacade:
    """Fassade nur für `MqttBridge.discovery_messages()`: liefert ausschließlich `verified()`
    aus dem Geräteprofil, verbindet sich zu nichts."""

    def __init__(self, verified: tuple[str, ...]):
        self._verified = verified

    def verified(self) -> tuple[str, ...]:
        return self._verified


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="mqtt_cmd", required=True)
    sub.add_parser("discovery", help=_t("Discovery-Nachrichten als JSON zeigen (keine Verbindung)"))
    sub.add_parser("status", help=_t("an/aus, Broker, Benutzer und Passwort-Referenz zeigen"))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()

    if args.mqtt_cmd == "discovery":
        profile = ctx.load_profile()
        bridge = mqtt.MqttBridge(_ProfileFacade(tuple(profile.verified)), cfg)
        messages = [{"topic": topic, "payload": "" if payload is None else payload}
                    for topic, payload, _retain in bridge.discovery_messages()]
        ctx.out(json.dumps(messages, ensure_ascii=False))
        return 0

    if args.mqtt_cmd == "status":
        enabled = config.setting(cfg, "mqtt.enabled")
        host = config.setting(cfg, "mqtt.host")
        port = config.setting(cfg, "mqtt.port")
        username = config.setting(cfg, "mqtt.username")
        password_ref = config.setting(cfg, "mqtt.password_ref")
        describe = secretref.describe_ref(password_ref)
        has_value = bool(password_ref) and secretref.has_secret(password_ref, keyring_module=KEYRING)
        ctx.out(f"MQTT: {'an' if enabled else 'aus'}")
        ctx.out(f"Broker: {host}:{port}")
        ctx.out(_t("Benutzer: {value}", value=username or 'nicht gesetzt'))
        ctx.out(_t("Passwort-Referenz: {describe} ({value})", describe=describe, value='vorhanden' if has_value else 'fehlt'))
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{mqtt_cmd}'", mqtt_cmd=args.mqtt_cmd))
