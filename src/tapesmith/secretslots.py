"""Geheimwerte der Oberfläche: feste Plätze (Slots) je Dienst.

Jeder Slot gehört zu genau einer Secret-Referenz in `config.json` (MQTT-Passwort, Telegram-Token)
oder `homelab.json` (Paperless, Home Assistant, Kurz-Link-Dienst, je Proxmox-Host). Aus der
Oberfläche gesetzte Werte liegen immer in den Windows-Anmeldeinformationen unter einer festen
Tapesmith-Referenz (`keyring:tapesmith/<slot>`); die Referenz wird dabei automatisch eingetragen.
Referenzen auf Dateien oder Umgebungsvariablen (`file:`, `env:`) funktionieren weiter und gelten
als externe Quelle; `adopt` übernimmt ihren Wert in die Tapesmith-Referenz.

Werte erscheinen nie in einer Rückgabe, einer Meldung oder einem Log.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass

from tapesmith import config as config_mod
from tapesmith import modules
from tapesmith.i18n import N_, _t
from tapesmith.integrations import credentials
from tapesmith.integrations import settings as homelab_settings
from tapesmith.integrations.errors import TokenMissing

log = logging.getLogger(__name__)

KEYRING_SERVICE = "tapesmith"

SOURCE_TAPESMITH = "tapesmith"
SOURCE_EXTERNAL = "extern"
SOURCE_NONE = "none"

_CONFIG_SLOTS = (
    ("mqtt", "mqtt.password_ref", N_("MQTT-Passwort")),
    ("telegram", "telegram.token_ref", N_("Telegram-Bot-Token")),
)
_HOMELAB_SLOTS = (
    ("paperless", "paperless.token_ref", "Paperless"),
    ("homeassistant", "homeassistant.token_ref", "Home Assistant"),
    ("shortlink", "shortlink.token_ref", N_("Kurz-Link-Dienst")),
)
PROXMOX_PREFIX = "proxmox:"

# Modul, zu dem ein Slot gehört (None: Kernfunktion auf der Seite Zugriff)
_SLOT_MODULES = {"paperless": "paperless", "homeassistant": "homeassistant", "shortlink": "assets"}
PROXMOX_MODULE = "proxmox"
ACCESS_TARGET = "/zugriff"


class SlotNotFound(KeyError):
    """Unbekannter Slot (z. B. Proxmox-Host, den es nicht gibt)."""


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    store: str            # "config" | "homelab"
    key: str              # gepunkteter Schlüssel der Referenz, bei Proxmox "proxmox.hosts"
    host: str | None = None

    @property
    def module(self) -> str | None:
        """Modul, dessen Einstellungen den Slot enthalten (None: Seite Zugriff)."""
        return PROXMOX_MODULE if self.host is not None else _SLOT_MODULES.get(self.id)

    @property
    def target(self) -> str:
        """Ort in der Oberfläche, an dem der Dienst eingerichtet wird."""
        module = self.module
        return f"/einstellungen?abschnitt=modul-{module}" if module else ACCESS_TARGET

    @property
    def managed_ref(self) -> str:
        """Feste Tapesmith-Referenz dieses Slots in den Windows-Anmeldeinformationen."""
        user = f"proxmox-{self.host}" if self.host is not None else self.id
        return f"keyring:{KEYRING_SERVICE}/{user}"


def _homelab_data() -> dict:
    return homelab_settings.load_unchecked()


def all_slots(*, cfg: dict | None = None, homelab: dict | None = None) -> list[Slot]:
    """Alle Slots in fester Reihenfolge; Proxmox je eingetragenem Host."""
    del cfg  # die Slots aus config.json sind fest
    data = _homelab_data() if homelab is None else homelab
    slots = [Slot(slot_id, label, "config", key) for slot_id, key, label in _CONFIG_SLOTS]
    slots += [Slot(slot_id, label, "homelab", key) for slot_id, key, label in _HOMELAB_SLOTS]
    for host in (data.get("proxmox") or {}).get("hosts") or []:
        name = host.get("name") if isinstance(host, dict) else None
        if isinstance(name, str) and name:
            slots.append(Slot(f"{PROXMOX_PREFIX}{name}", f"Proxmox {name}", "homelab", "proxmox.hosts", host=name))
    return slots


def find_slot(slot_id: str, *, homelab: dict | None = None) -> Slot:
    for slot in all_slots(homelab=homelab):
        if slot.id == slot_id:
            return slot
    raise SlotNotFound(slot_id)


def current_ref(slot: Slot, *, cfg: dict | None = None, homelab: dict | None = None) -> str | None:
    """Die eingetragene Referenz des Slots (oder None)."""
    if slot.store == "config":
        cfg = config_mod.load_config() if cfg is None else cfg
        ref = config_mod.setting(cfg, slot.key)
    else:
        data = _homelab_data() if homelab is None else homelab
        if slot.host is not None:
            ref = next((h.get("token_ref") for h in data["proxmox"].get("hosts") or []
                        if isinstance(h, dict) and h.get("name") == slot.host), None)
        else:
            section, _, name = slot.key.partition(".")
            ref = (data.get(section) or {}).get(name)
    return ref if isinstance(ref, str) and ref else None


def _source(slot: Slot, ref: str | None) -> str:
    if not ref:
        return SOURCE_NONE
    return SOURCE_TAPESMITH if ref == slot.managed_ref else SOURCE_EXTERNAL


def slot_status(slot: Slot, *, cfg: dict | None = None, homelab: dict | None = None,
                keyring_module=None, environ=None) -> dict:
    """Zustand ohne Wert: Quelle (`tapesmith`, `extern`, `none`) und ob ein Wert vorliegt."""
    ref = current_ref(slot, cfg=cfg, homelab=homelab)
    try:
        present = credentials.has_secret(ref, keyring_module=keyring_module, environ=environ)
    except Exception:  # noqa: BLE001 (jede Ausnahme beim Prüfen gilt als "nicht gesetzt")
        present = False
    cfg = config_mod.load_config() if cfg is None else cfg
    module = slot.module
    return {"id": slot.id, "label": _t(slot.label), "source": _source(slot, ref), "set": present,
            "module": module, "module_enabled": True if module is None else modules.is_enabled(cfg, module),
            "target": slot.target}


def statuses(*, keyring_module=None, environ=None) -> list[dict]:
    cfg = config_mod.load_config()
    data = _homelab_data()
    return [slot_status(s, cfg=cfg, homelab=data, keyring_module=keyring_module, environ=environ)
            for s in all_slots(homelab=data)]


def _set_ref(slot: Slot, ref: str | None) -> None:
    """Trägt die Referenz des Slots in die zugehörige Datei ein (None: entfernt sie)."""
    if slot.store == "config":
        current = config_mod.load_config()
        section_name, _, key = slot.key.partition(".")
        existing = current.get(section_name)
        section = dict(existing) if isinstance(existing, dict) else {}
        section[key] = ref
        candidate = dict(current)
        candidate[section_name] = section
        config_mod.validate_config(candidate)
        config_mod.save_config({section_name: section})
        return
    if slot.host is not None:
        hosts = copy.deepcopy(_homelab_data()["proxmox"].get("hosts") or [])
        for host in hosts:
            if isinstance(host, dict) and host.get("name") == slot.host:
                host["token_ref"] = ref
        homelab_settings.update_settings({"proxmox.hosts": hosts})
        return
    homelab_settings.update_settings({slot.key: ref})


def _keyring_parts(ref: str) -> tuple[str, str]:
    service, _, user = ref[len("keyring:"):].partition("/")
    return service, user


def _load_keyring(keyring_module):
    if keyring_module is not None:
        return keyring_module
    import keyring

    return keyring


def store(slot_id: str, value: str, *, keyring_module=None, environ=None) -> dict:
    """Speichert `value` unter der Tapesmith-Referenz des Slots und trägt die Referenz ein."""
    slot = find_slot(slot_id)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_t("Wert darf nicht leer sein"))
    credentials.write_secret(slot.managed_ref, value, keyring_module=keyring_module)
    if current_ref(slot) != slot.managed_ref:
        _set_ref(slot, slot.managed_ref)
    log.info("Geheimwert gespeichert: %s", slot.id)
    return slot_status(slot, keyring_module=keyring_module, environ=environ)


def adopt(slot_id: str, *, keyring_module=None, environ=None) -> dict:
    """Übernimmt den Wert einer externen Quelle (Datei, Umgebungsvariable, fremder Eintrag in den
    Windows-Anmeldeinformationen) in die Tapesmith-Referenz des Slots."""
    slot = find_slot(slot_id)
    ref = current_ref(slot)
    if _source(slot, ref) != SOURCE_EXTERNAL:
        raise ValueError(_t("Keine externe Quelle eingetragen, nichts zu übernehmen"))
    try:
        value = credentials.read_secret(ref, what=_t(slot.label), keyring_module=keyring_module,
                                        environ=environ)
    except TokenMissing as exc:
        raise ValueError(_t("Die externe Quelle liefert keinen Wert, bitte den Wert direkt eingeben")) from exc
    credentials.write_secret(slot.managed_ref, value, keyring_module=keyring_module)
    _set_ref(slot, slot.managed_ref)
    log.info("Geheimwert aus externer Quelle übernommen: %s", slot.id)
    return slot_status(slot, keyring_module=keyring_module, environ=environ)


def remove(slot_id: str, *, keyring_module=None, environ=None) -> dict:
    """Entfernt den Wert: Eintrag der Tapesmith-Referenz löschen und die Referenz austragen.
    Externe Dateien und Umgebungsvariablen bleiben unangetastet."""
    slot = find_slot(slot_id)
    ref = current_ref(slot)
    if ref == slot.managed_ref or ref is None:
        service, user = _keyring_parts(slot.managed_ref)
        try:
            module = _load_keyring(keyring_module)
            module.delete_password(service, user)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001 (kein Eintrag vorhanden: nichts zu löschen)
            pass
    if ref is not None:
        _set_ref(slot, None)
    log.info("Geheimwert entfernt: %s", slot.id)
    return slot_status(slot, keyring_module=keyring_module, environ=environ)


def adopt_all(*, keyring_module=None, environ=None) -> dict:
    """Übernimmt jeden Slot mit externer Quelle, auch von ausgeschalteten Modulen. Slots, deren
    Quelle keinen Wert liefert, werden mit Grund übersprungen; die anderen laufen trotzdem weiter."""
    adopted: list[str] = []
    skipped: list[dict] = []
    for slot in all_slots():
        if _source(slot, current_ref(slot)) != SOURCE_EXTERNAL:
            continue
        try:
            adopt(slot.id, keyring_module=keyring_module, environ=environ)
        except ValueError as exc:
            skipped.append({"id": slot.id, "label": _t(slot.label), "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001 (ein kaputter Slot darf die anderen nicht aufhalten)
            log.warning("Übernahme von %s gescheitert: %s", slot.id, type(exc).__name__)
            skipped.append({"id": slot.id, "label": _t(slot.label),
                            "reason": _t("Übernahme fehlgeschlagen ({kind})", kind=type(exc).__name__)})
        else:
            adopted.append(slot.id)
    log.info("Geheimwerte übernommen: %d, übersprungen: %d", len(adopted), len(skipped))
    return {"adopted": adopted, "skipped": skipped,
            "slots": statuses(keyring_module=keyring_module, environ=environ)}
