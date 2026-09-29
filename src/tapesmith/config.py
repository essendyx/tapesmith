"""Benutzerkonfiguration (config.json) mit Defaults.

`SECTION_DEFAULTS` sammelt die sektionierten Schlüssel (daemon, queue,
status, hotkey, tray, ble, ssh, archive, backup, numbering, modules, ...). Zugriff über `setting(cfg, "a.b")`
mit Fallback auf die Defaults; andere Module lesen nur noch darüber. `validate_config`
bündelt alle Prüfungen (bisherige + neue) und wird von `load_config` sowie von `set_setting`
(vor dem Speichern) genutzt.
"""

import ipaddress
import json
import re
from collections.abc import Callable

from tapesmith import fileutil, paths
from tapesmith.i18n import _t

DEFAULTS = {
    "mac": None,  # MAC des Druckers; None = einziger gekoppelter Bluetooth-Drucker (p12 setup setzt sie)
    "transport": "auto",
    "idle_timeout_s": 300,
    "connect_timeout_s": 5,
    "guard": {},
    "gui": {},
    "tape": {"current": "schwarz-weiss"},
    "templates_dir": None,
    "cut_pause_s": None,
}

GUI_DEFAULTS = {
    "ctrl_enter_only": False, "preview_mode": "design", "screen_px_per_mm": None,
    "favorites": [], "editor_grid_dots": 8, "editor_snap": True,
}

# Sektionierte Konfigurationsschlüssel. DEFAULTS/GUI_DEFAULTS bleiben
# unverändert; ältere Module lesen ihre Werte mit identischen Defaults direkt.
SECTION_DEFAULTS = {
    "daemon": {"enabled": True, "spawn": True, "connect_timeout_s": 2.0, "start_timeout_s": 10.0,
               "idle_exit_s": 1800},
    "queue": {"enabled": True, "auto_retry": True, "backoff_start_s": 30, "backoff_max_s": 300,
              "probe": "auto", "cli_default": False},
    "status": {"poll_s": 120},
    "hotkey": {"enabled": True, "quick": "Ctrl+Alt+L", "clipboard": "Ctrl+Alt+Shift+L"},
    "tray": {"favorites": [], "toast_s": 3, "notify": True},
    "ble": {"address": None, "names": ["P12", "P12 PRO", "P12PRO"], "scan_timeout_s": 8.0},
    "ssh": {"hosts": [], "timeout_s": 20, "strict_host_key": True},
    "archive": {"dir": None, "git_commit": False},
    "backup": {"dir": None, "keep": 10, "auto_daily": False},
    "numbering": {"dir": None},
    # Lokale HTTP-API des Druckdienstes (web); Sprache und Farbschema (app).
    # `app.quick_window` (Web-Kompaktfenster oder Qt-Popup) ist entfallen: die Oberfläche läuft nur
    # noch im Browser, der Schnelldruck ist immer das Qt-Popup der Tray-App. Ein alter Eintrag in
    # config.json wird ignoriert.
    "web": {"port": 8712},
    "app": {"language": "auto", "theme": "system"},
    # LAN-Freigabe, Familie, MCP, Hotfolder, MQTT/Home Assistant, Telegram.
    "lan": {"enabled": False, "bind": "0.0.0.0", "allowed_networks": ["192.168.0.0/16"],
            "hostnames": [], "public_url": None},
    "family": {"templates": ["gefriergut", "geoeffnet-am", "vorratsdose", "schule", "eigentum"],
               "max_copies": 5, "freetext_enabled": True},
    "mcp": {"http": True},
    "hotfolder": {"enabled": False, "dir": None, "poll_s": 2.0, "settle_s": 1.5, "max_bytes": 2000000},
    "mqtt": {"enabled": False, "host": None, "port": 1883, "username": "tapesmith",
             "password_ref": "keyring:tapesmith/mqtt", "base_topic": "tapesmith",
             "discovery_prefix": "homeassistant", "templates": [], "tls": False, "keepalive_s": 60},
    "telegram": {"enabled": False, "token_ref": None,
                 "chat_id": None, "quiet_hours": "22:00-07:00", "offline_min": 30,
                 "queue_stuck_min": 15, "roll_low_m": 0.5, "notify_queue": True,
                 "notify_offline": True, "notify_error": True, "notify_roll": True},
    # Auto-Update (Quelle, Kanal, Prüfabstand, Installation bei Leerlauf).
    # Das Repository ist öffentlich: GitHub-Abrufe laufen ohne Token. Ein alter Eintrag
    # `update.token_ref` in config.json wird ignoriert.
    "update": {"enabled": True, "source": "github:essendyx/tapesmith",
               "channel": "stable", "check_interval_h": 24, "auto_install": False, "idle_min": 10,
               "keep_versions": 2},
    # Eingeschaltete Module (tapesmith.modules); Standard: keine.
    "modules": {"enabled": []},
}

# Erlaubte Werte für Sprache, Farbschema und Update-Kanal; Form einer GitHub-Update-Quelle.
LANGUAGE_CHOICES = ("auto", "de", "en")
THEME_CHOICES = ("system", "hell", "dunkel")
UPDATE_CHANNELS = ("stable", "beta")
_GITHUB_SOURCE_RE = re.compile(r"^github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# Hostname (lan.hostnames), Vorlagenname (family.templates/mqtt.templates), MQTT-Themenpfad
# (ohne Wildcards) und Telegram-Chat-ID/Ruhezeiten.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$")
_TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MQTT_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")
_CHAT_ID_TEXT_RE = re.compile(r"^-?\d{1,20}$")
_CHAT_ID_CHANNEL_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_QUIET_HOURS_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")

# Ohne Punkt setzbare Schlüssel (`set_setting`); Sektionen (gui/tape/guard/SECTION_DEFAULTS)
# brauchen dagegen "<sektion>.<schlüssel>".
TOP_LEVEL_KEYS = ("mac", "transport", "idle_timeout_s", "connect_timeout_s", "templates_dir", "cut_pause_s")

SECRET_KEY_PARTS = ("token", "password", "passwort", "secret", "kennwort")

_SSH_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")


def gui_setting(cfg: dict, key: str):
    """Liest eine GUI-Einstellung aus `cfg["gui"]` mit Fallback auf `GUI_DEFAULTS`.
    Unbekannter Schlüssel -> KeyError."""
    if key not in GUI_DEFAULTS:
        raise KeyError(key)
    return cfg.get("gui", {}).get(key, GUI_DEFAULTS[key])


def tape_setting(cfg: dict) -> str:
    """Liest `cfg["tape"]["current"]` mit Fallback auf den Default."""
    default = DEFAULTS["tape"]["current"]
    tape = cfg.get("tape")
    if not isinstance(tape, dict):
        return default
    return tape.get("current", default)


class UnknownSetting(KeyError):
    """Wie `KeyError`, aber `str()` liefert die Meldung ohne die umschließenden Anführungszeichen,
    die `KeyError.__str__` sonst über `repr()` ergänzt."""

    def __str__(self) -> str:
        if self.args:
            return str(self.args[0])
        return ""


def check_transport(value) -> str:
    """Prüft und normalisiert eine Transportangabe für `set_setting("transport", …)`.

    Erlaubt: `auto`, `ble`, `ble:<Adresse>`, `usb`, `COM<n>` (Groß-/Kleinschreibung egal,
    gespeichert als `COM<n>`), `file:<pfad>` (Pfad nicht leer). Sonst `ValueError`."""
    text = str(value)
    stripped = text.strip()
    low = stripped.lower()
    if low in ("auto", "ble", "usb"):
        return low
    if low.startswith("ble:") and stripped[4:]:
        return "ble:" + stripped[4:]
    if low.startswith("file:") and stripped[5:]:
        return "file:" + stripped[5:]
    match = re.fullmatch(r"com(\d+)", low)
    if match:
        return "COM" + match.group(1)
    raise ValueError(
        _t("Transport {value!r} ungültig: erlaubt auto, ble, ble:<Adresse>, usb, COM<n>, file:<Pfad>", value=value))


def normalize_mac(mac: str) -> str:
    normalized = "".join(ch for ch in mac if ch.isalnum()).upper()
    if not re.match(r"^[0-9A-F]{12}$", normalized):
        raise ValueError(_t("Ungültige MAC-Adresse: {mac!r}", mac=mac))
    return normalized


def setting(cfg: dict, dotted: str):
    """Liest einen Konfigurationswert mit Fallback auf die Defaults.

    "sektion.schlüssel": `cfg[sektion][schlüssel]` mit Fallback `SECTION_DEFAULTS`; "gui.x" über
    `GUI_DEFAULTS` (`gui_setting`); ohne Punkt: `cfg[key]` mit Fallback `DEFAULTS`. Unbekannter
    Pfad -> `KeyError(dotted)`.
    """
    if "." in dotted:
        section_name, _, key = dotted.partition(".")
        if section_name == "gui":
            try:
                return gui_setting(cfg, key)
            except KeyError:
                raise KeyError(dotted) from None
        if section_name not in SECTION_DEFAULTS or key not in SECTION_DEFAULTS[section_name]:
            raise KeyError(dotted)
        section = cfg.get(section_name)
        default = SECTION_DEFAULTS[section_name][key]
        if isinstance(section, dict) and key in section:
            return section[key]
        return default
    if dotted not in DEFAULTS:
        raise KeyError(dotted)
    return cfg.get(dotted, DEFAULTS[dotted])


def _section_names() -> set:
    return {"gui", "tape", "guard"} | set(SECTION_DEFAULTS)


def _section_example_key(section_name: str) -> str:
    """Ein tatsächlich existierender Schlüssel der Sektion, für die Hinweismeldung
    ('bitte "<sektion>.<schlüssel>" angeben, z. B. …')."""
    if section_name == "gui":
        return next(iter(GUI_DEFAULTS))
    if section_name == "tape":
        return "current"
    if section_name == "guard":
        from tapesmith import guard
        return sorted(guard._POLICY_FIELDS)[0]
    return next(iter(SECTION_DEFAULTS[section_name]))


def _set_top_level(dotted: str, value, save: Callable[[dict], dict]) -> dict:
    if dotted in TOP_LEVEL_KEYS:
        if dotted == "mac":
            value = normalize_mac(value)
        elif dotted == "transport":
            value = check_transport(value)
        current = load_config()
        candidate = dict(current)
        candidate[dotted] = value
        validate_config(candidate)
        return save({dotted: value})
    if dotted in _section_names():
        example = _section_example_key(dotted)
        raise UnknownSetting(
            _t("'{dotted}' ist eine Sektion: bitte '{dotted}.<schlüssel>' angeben, z. B. {dotted}.{example}", dotted=dotted, example=example))
    known = ", ".join(TOP_LEVEL_KEYS)
    raise UnknownSetting(
        _t("Unbekannter Schlüssel '{dotted}'. Bekannt: {known} sowie <sektion>.<schlüssel> (siehe 'p12 config show')", dotted=dotted, known=known))


def _check_dotted_known(section_name: str, key: str) -> None:
    """Wirft `UnknownSetting`, wenn `section_name.key` kein bekannter Konfigurationspfad ist."""
    if section_name in SECTION_DEFAULTS or section_name == "gui":
        try:
            setting({}, f"{section_name}.{key}")
        except KeyError:
            if section_name == "gui":
                known_keys = ", ".join(GUI_DEFAULTS)
            else:
                known_keys = ", ".join(SECTION_DEFAULTS[section_name])
            raise UnknownSetting(
                _t("Unbekannter Schlüssel '{section_name}.{key}'. Bekannt in '{section_name}': {known_keys}", section_name=section_name, key=key, known_keys=known_keys)) from None
        return
    if section_name == "guard":
        from tapesmith import guard
        if key not in guard._POLICY_FIELDS:
            known_keys = ", ".join(sorted(guard._POLICY_FIELDS))
            raise UnknownSetting(
                _t("Unbekannter Schlüssel 'guard.{key}'. Bekannt in 'guard': {known_keys}", key=key, known_keys=known_keys))
        return
    if section_name == "tape":
        if key != "current":
            raise UnknownSetting(_t("Unbekannter Schlüssel 'tape.{key}'. Bekannt in 'tape': current", key=key))
        return
    raise UnknownSetting(
        _t("Unbekannter Schlüssel '{section_name}.{key}'. Unbekannte Sektion '{section_name}' (siehe 'p12 config show')", section_name=section_name, key=key))


def set_setting(dotted: str, value, *, save: Callable[[dict], dict] = None) -> dict:
    """Setzt einen Konfigurationswert dauerhaft: liest die vorhandene Sektion, setzt den
    Schlüssel, validiert das Ergebnis und speichert NUR bei Erfolg als `{"sektion": ganze_sektion}`
    (bzw. `{schlüssel: wert}` für die Schlüssel ohne Punkt aus `TOP_LEVEL_KEYS`).

    Ungültiger oder unbekannter Schlüssel -> `ValueError`/`UnknownSetting`, die Datei bleibt
    unverändert. Rückgabe: das Ergebnis von `save`.
    """
    if save is None:
        save = save_config
    section_name, sep, key = dotted.partition(".")
    if not sep:
        return _set_top_level(dotted, value, save)
    _check_dotted_known(section_name, key)
    current = load_config()
    existing = current.get(section_name)
    section = dict(existing) if isinstance(existing, dict) else {}
    section[key] = value
    candidate = dict(current)
    candidate[section_name] = section
    validate_config(candidate)
    return save({section_name: section})


def parse_cli_value(text: str):
    """Wandelt einen CLI-Text in den passenden Python-Wert um: "true"/"false" -> bool,
    "null"/"none" -> None, Ganzzahl/Kommazahl -> int/float, JSON-Liste/-Objekt -> list/dict,
    sonst unverändert als Text."""
    stripped = text.strip()
    low = stripped.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    if stripped[:1] in ("[", "{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return text


def secret_keys(cfg: dict) -> list[str]:
    """Gepunktete Pfade (rekursiv über verschachtelte Objekte), deren Schlüsselname einen
    `SECRET_KEY_PARTS`-Teil enthält und deren Wert ein nicht-leerer Text ist, der KEINE
    Secret-Referenz ist (kein Präfix `keyring:`, `file:`, `env:`, siehe `secretref.is_ref`)."""
    from tapesmith import secretref  # spät, um Zyklen zu vermeiden

    found: list[str] = []

    def walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                walk(value, path)
                continue
            if any(part in key.casefold() for part in SECRET_KEY_PARTS):
                if isinstance(value, str) and value.strip() and not secretref.is_ref(value):
                    found.append(path)

    walk(cfg, "")
    return found


# ---------- bisherige Prüf-Helfer (unverändert) ----------

def _check_number(cfg: dict, key: str, *, minimum: float, inclusive: bool) -> None:
    value = cfg.get(key)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok:
        ok = value >= minimum if inclusive else value > minimum
    if not ok:
        vergleich = "≥" if inclusive else ">"
        raise ValueError(
            _t("config.json: '{key}' muss eine Zahl {vergleich} {minimum} sein, ist {value!r}", key=key, vergleich=vergleich, minimum=minimum, value=value))


def _check_optional_text(cfg: dict, key: str) -> None:
    value = cfg.get(key)
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_t("config.json: '{key}' muss None oder ein nicht-leerer Text sein, ist {value!r}", key=key, value=value))


def _check_cut_pause(cfg: dict) -> None:
    value = cfg.get("cut_pause_s")
    if value is None:
        return
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if not ok:
        raise ValueError(
            _t("config.json: 'cut_pause_s' muss None, 0 oder eine Zahl > 0 sein, ist {value!r}", value=value))


def _check_gui_screen_px(gui: dict) -> None:
    if "screen_px_per_mm" not in gui:
        return
    value = gui["screen_px_per_mm"]
    if value is None:
        return
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= value <= 20
    if not ok:
        raise ValueError(
            _t("config.json: 'gui.screen_px_per_mm' muss None oder eine Zahl 1..20 sein, ist {value!r}", value=value))


def _check_gui_grid_dots(gui: dict) -> None:
    if "editor_grid_dots" not in gui:
        return
    value = gui["editor_grid_dots"]
    ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 64
    if not ok:
        raise ValueError(
            _t("config.json: 'gui.editor_grid_dots' muss eine ganze Zahl 1..64 sein, ist {value!r}", value=value))


def _check_gui_favorites(gui: dict) -> None:
    if "favorites" not in gui:
        return
    value = gui["favorites"]
    ok = isinstance(value, list) and all(isinstance(x, str) for x in value)
    if not ok:
        raise ValueError(_t("config.json: 'gui.favorites' muss eine Liste von Texten sein, ist {value!r}", value=value))


# ---------- neue Prüf-Helfer (sektioniert) ----------

def _section(cfg: dict, name: str) -> dict | None:
    if name not in cfg:
        return None
    value = cfg[name]
    if not isinstance(value, dict):
        raise ValueError(_t("config.json: '{name}' muss ein Objekt sein, ist {value!r}", name=name, value=value))
    return value


def _check_bool_key(section: dict, sect_name: str, key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if not isinstance(value, bool):
        raise ValueError(_t("config.json: '{sect_name}.{key}' muss true oder false sein, ist {value!r}", sect_name=sect_name, key=key, value=value))


def _check_number_key(section: dict, sect_name: str, key: str, *, minimum: float, inclusive: bool) -> None:
    if key not in section:
        return
    value = section[key]
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok:
        ok = value >= minimum if inclusive else value > minimum
    if not ok:
        vergleich = "≥" if inclusive else ">"
        raise ValueError(
            _t("config.json: '{sect_name}.{key}' muss eine Zahl {vergleich} {minimum} sein, ist {value!r}", sect_name=sect_name, key=key, vergleich=vergleich, minimum=minimum, value=value))


def _check_optional_text_key(section: dict, sect_name: str, key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            _t("config.json: '{sect_name}.{key}' muss None oder ein nicht-leerer Text sein, ist {value!r}", sect_name=sect_name, key=key, value=value))


def _check_daemon(section: dict) -> None:
    _check_bool_key(section, "daemon", "enabled")
    _check_bool_key(section, "daemon", "spawn")
    _check_number_key(section, "daemon", "connect_timeout_s", minimum=0, inclusive=False)
    _check_number_key(section, "daemon", "start_timeout_s", minimum=0, inclusive=False)
    _check_number_key(section, "daemon", "idle_exit_s", minimum=0, inclusive=True)


def _check_queue(section: dict) -> None:
    _check_bool_key(section, "queue", "enabled")
    _check_bool_key(section, "queue", "auto_retry")
    _check_bool_key(section, "queue", "cli_default")
    start = section.get("backoff_start_s", SECTION_DEFAULTS["queue"]["backoff_start_s"])
    ok_start = isinstance(start, (int, float)) and not isinstance(start, bool) and start > 0
    if not ok_start:
        raise ValueError(_t("config.json: 'queue.backoff_start_s' muss eine Zahl > 0 sein, ist {start!r}", start=start))
    if "backoff_max_s" in section:
        max_s = section["backoff_max_s"]
        ok_max = isinstance(max_s, (int, float)) and not isinstance(max_s, bool) and max_s >= start
        if not ok_max:
            raise ValueError(
                _t("config.json: 'queue.backoff_max_s' muss eine Zahl ≥ backoff_start_s ({start}) sein, ist {max_s!r}", start=start, max_s=max_s))
    if "probe" in section:
        probe = section["probe"]
        if probe not in ("auto", "ble", "connect", "off"):
            raise ValueError(
                _t("config.json: 'queue.probe' muss eines von auto/ble/connect/off sein, ist {probe!r}", probe=probe))


def _check_hotkey(section: dict) -> None:
    _check_bool_key(section, "hotkey", "enabled")
    for key in ("quick", "clipboard"):
        if key not in section:
            continue
        value = section[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                _t("config.json: 'hotkey.{key}' muss ein nicht-leerer Text sein, ist {value!r}", key=key, value=value))


def _check_tray(section: dict) -> None:
    _check_bool_key(section, "tray", "notify")
    if "toast_s" in section:
        value = section["toast_s"]
        ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10
        if not ok:
            raise ValueError(_t("config.json: 'tray.toast_s' muss eine ganze Zahl 1..10 sein, ist {value!r}", value=value))
    if "favorites" in section:
        favorites = section["favorites"]
        if not isinstance(favorites, list):
            raise ValueError(_t("config.json: 'tray.favorites' muss eine Liste sein, ist {favorites!r}", favorites=favorites))
        for item in favorites:
            if (not isinstance(item, dict) or not isinstance(item.get("title"), str)
                    or not isinstance(item.get("template"), str)):
                raise ValueError(
                    _t("config.json: 'tray.favorites' Einträge brauchen Text 'title' und 'template', ist {item!r}", item=item))
            if "values" in item:
                values = item["values"]
                ok_values = (isinstance(values, dict)
                             and all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()))
                if not ok_values:
                    raise ValueError(
                        _t("config.json: 'tray.favorites[].values' muss ein Objekt Text→Text sein, ist {values!r}", values=values))


def _check_ble(section: dict) -> None:
    if "address" in section and section["address"] is not None:
        try:
            section["address"] = normalize_mac(section["address"])
        except ValueError:
            raise ValueError(
                _t("config.json: 'ble.address' muss None oder eine gültige MAC sein, ist {address!r}", address=section['address'])) from None
    if "names" in section:
        names = section["names"]
        ok = isinstance(names, list) and bool(names) and all(isinstance(n, str) and n.strip() for n in names)
        if not ok:
            raise ValueError(
                _t("config.json: 'ble.names' muss eine nicht-leere Liste nicht-leerer Texte sein, ist {names!r}", names=names))
    _check_number_key(section, "ble", "scan_timeout_s", minimum=0, inclusive=False)


def _check_ssh_hosts(hosts) -> None:
    if not isinstance(hosts, list):
        raise ValueError(_t("config.json: 'ssh.hosts' muss eine Liste sein, ist {hosts!r}", hosts=hosts))
    seen: set[str] = set()
    for host in hosts:
        if not isinstance(host, dict):
            raise ValueError(_t("config.json: 'ssh.hosts[]' muss ein Objekt sein, ist {host!r}", host=host))
        name = host.get("name")
        if not isinstance(name, str) or not _SSH_NAME_RE.match(name):
            raise ValueError(
                _t("config.json: 'ssh.hosts[].name' muss {pattern} entsprechen, ist {name!r}", pattern=_SSH_NAME_RE.pattern, name=name))
        if name in seen:
            raise ValueError(_t("config.json: 'ssh.hosts' doppelter Name '{name}'", name=name))
        seen.add(name)
        host_value = host.get("host")
        if (not isinstance(host_value, str) or not host_value.strip() or " " in host_value
                or host_value.startswith("-")):
            raise ValueError(
                _t("config.json: 'ssh.hosts[].host' darf keine Leerzeichen haben und nicht mit '-' beginnen, ist {host_value!r}", host_value=host_value))
        user = host.get("user", "root")
        if not isinstance(user, str) or not _SSH_USER_RE.match(user):
            raise ValueError(
                _t("config.json: 'ssh.hosts[].user' muss {pattern} entsprechen, ist {user!r}", pattern=_SSH_USER_RE.pattern, user=user))
        port = host.get("port", 22)
        ok_port = isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
        if not ok_port:
            raise ValueError(_t("config.json: 'ssh.hosts[].port' muss 1..65535 sein, ist {port!r}", port=port))
        key = host.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                _t("config.json: 'ssh.hosts[].key' muss ein nicht-leerer Pfadtext sein, ist {key!r}", key=key))


def _check_backup_keep(section: dict) -> None:
    if "keep" not in section:
        return
    value = section["keep"]
    ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000
    if not ok:
        raise ValueError(_t("config.json: 'backup.keep' muss eine ganze Zahl 1..1000 sein, ist {value!r}", value=value))


def _check_web(section: dict) -> None:
    # `web.enabled` gibt es nicht mehr (die Web-Oberfläche läuft immer); ein alter Eintrag bleibt
    # gültig und wird ignoriert.
    if "port" in section:
        value = section["port"]
        ok = isinstance(value, int) and not isinstance(value, bool) and 1024 <= value <= 65535
        if not ok:
            raise ValueError(
                _t("config.json: 'web.port' muss eine ganze Zahl 1024..65535 sein, ist {value!r} (Port 0 nur über die Umgebungsvariable TAPESMITH_WEB_PORT, nicht in der Datei)", value=value))


def _check_range_key(section: dict, sect_name: str, key: str, *, minimum: float, maximum: float,
                      integer: bool = False) -> None:
    if key not in section:
        return
    value = section[key]
    if integer:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok:
        ok = minimum <= value <= maximum
    if not ok:
        art = _t("eine ganze Zahl") if integer else _t("eine Zahl")
        raise ValueError(
            _t("config.json: '{sect_name}.{key}' muss {art} {minimum}..{maximum} sein, ist {value!r}", sect_name=sect_name, key=key, art=art, minimum=minimum, maximum=maximum, value=value))


def _check_template_names_key(section: dict, sect_name: str, key: str, *, allow_empty: bool) -> None:
    if key not in section:
        return
    values = section[key]
    ok = isinstance(values, list) and (allow_empty or bool(values))
    if ok:
        ok = all(isinstance(v, str) and _TEMPLATE_NAME_RE.match(v) for v in values)
    if not ok:
        raise ValueError(
            _t("config.json: '{sect_name}.{key}' muss eine Liste gültiger Vorlagennamen ({pattern}) sein, ist {values!r}", sect_name=sect_name, key=key, pattern=_TEMPLATE_NAME_RE.pattern, values=values))


def _check_secret_ref_key(section: dict, sect_name: str, key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if value is None:
        return
    from tapesmith import secretref  # spät, um Zyklen zu vermeiden

    try:
        secretref.check_ref(value)
    except ValueError as exc:
        raise ValueError(
            _t("config.json: '{sect_name}.{key}' ist keine gültige Secret-Referenz: {exc}", sect_name=sect_name, key=key, exc=exc)) from None


def _check_lan(section: dict) -> None:
    _check_bool_key(section, "lan", "enabled")
    if "bind" in section:
        value = section["bind"]
        ok = isinstance(value, str) and bool(value)
        if ok:
            try:
                addr = ipaddress.IPv4Address(value)
            except ValueError:
                ok = False
            else:
                ok = not str(addr).startswith("127.")
        if not ok:
            raise ValueError(
                _t("config.json: 'lan.bind' muss eine IPv4-Adresse sein (nicht 127.x), ist {value!r}", value=value))
    if "allowed_networks" in section:
        networks = section["allowed_networks"]
        if not isinstance(networks, list) or not networks:
            raise ValueError(
                _t("config.json: 'lan.allowed_networks' muss eine nicht-leere Liste von IPv4-Netzen sein, ist {networks!r}", networks=networks))
        for net in networks:
            if not isinstance(net, str):
                raise ValueError(
                    _t("config.json: 'lan.allowed_networks' Einträge müssen Text sein, ist {net!r}", net=net))
            try:
                network = ipaddress.IPv4Network(net, strict=False)
            except ValueError:
                raise ValueError(
                    _t("config.json: 'lan.allowed_networks' enthält ein ungültiges Netz {net!r}", net=net)) from None
            if network.prefixlen < 8 or not network.is_private:
                raise ValueError(
                    _t("config.json: 'lan.allowed_networks' Netz {net!r} muss privat sein und mindestens /8 umfassen (kein 0.0.0.0/0, kein öffentliches Netz)", net=net))
    if "hostnames" in section:
        hostnames = section["hostnames"]
        ok = isinstance(hostnames, list) and all(
            isinstance(h, str) and _HOSTNAME_RE.match(h) for h in hostnames)
        if not ok:
            raise ValueError(
                _t("config.json: 'lan.hostnames' muss eine Liste gültiger Hostnamen (ohne Port) sein, ist {hostnames!r}", hostnames=hostnames))
    if "public_url" in section:
        value = section["public_url"]
        if value is not None:
            ok = (isinstance(value, str) and value.startswith(("http://", "https://"))
                  and " " not in value and "#" not in value)
            if not ok:
                raise ValueError(
                    _t("config.json: 'lan.public_url' muss None oder eine http(s)-URL ohne Leerzeichen/# sein, ist {value!r}", value=value))


def _check_family(section: dict) -> None:
    _check_template_names_key(section, "family", "templates", allow_empty=True)
    _check_range_key(section, "family", "max_copies", minimum=1, maximum=20, integer=True)
    _check_bool_key(section, "family", "freetext_enabled")


def _check_mcp(section: dict) -> None:
    _check_bool_key(section, "mcp", "http")


def _check_hotfolder(section: dict) -> None:
    _check_bool_key(section, "hotfolder", "enabled")
    _check_optional_text_key(section, "hotfolder", "dir")
    _check_range_key(section, "hotfolder", "poll_s", minimum=0.5, maximum=60)
    _check_range_key(section, "hotfolder", "settle_s", minimum=0, maximum=60)
    _check_range_key(section, "hotfolder", "max_bytes", minimum=1000, maximum=50000000, integer=True)


def _check_mqtt(section: dict) -> None:
    _check_bool_key(section, "mqtt", "enabled")
    _check_bool_key(section, "mqtt", "tls")
    if "host" in section:
        value = section["host"]
        ok = value is None or (isinstance(value, str) and bool(value.strip()) and " " not in value)
        if not ok:
            raise ValueError(
                _t("config.json: 'mqtt.host' muss leer (null) oder ein nicht-leerer Text ohne Leerzeichen sein, ist {value!r}", value=value))
    _check_range_key(section, "mqtt", "port", minimum=1, maximum=65535, integer=True)
    if "username" in section:
        value = section["username"]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(
                _t("config.json: 'mqtt.username' muss None oder ein nicht-leerer Text sein, ist {value!r}", value=value))
    _check_range_key(section, "mqtt", "keepalive_s", minimum=5, maximum=3600, integer=True)
    for key in ("base_topic", "discovery_prefix"):
        if key not in section:
            continue
        value = section[key]
        if not isinstance(value, str) or not _MQTT_TOPIC_RE.match(value):
            raise ValueError(
                _t("config.json: 'mqtt.{key}' muss {pattern} entsprechen (keine Wildcards), ist {value!r}", key=key, pattern=_MQTT_TOPIC_RE.pattern, value=value))
    _check_template_names_key(section, "mqtt", "templates", allow_empty=True)
    _check_secret_ref_key(section, "mqtt", "password_ref")


def _check_telegram(section: dict) -> None:
    _check_bool_key(section, "telegram", "enabled")
    for key in ("notify_queue", "notify_offline", "notify_error", "notify_roll"):
        _check_bool_key(section, "telegram", key)
    _check_secret_ref_key(section, "telegram", "token_ref")
    if "chat_id" in section:
        value = section["chat_id"]
        ok = value is None
        if not ok and isinstance(value, int) and not isinstance(value, bool):
            ok = True
        if not ok and isinstance(value, str):
            ok = bool(_CHAT_ID_TEXT_RE.match(value) or _CHAT_ID_CHANNEL_RE.match(value))
        if not ok:
            raise ValueError(
                _t("config.json: 'telegram.chat_id' muss None, eine ganze Zahl oder ein gültiger Kanaltext sein, ist {value!r}", value=value))
    if "quiet_hours" in section:
        value = section["quiet_hours"]
        if value is not None:
            match = _QUIET_HOURS_RE.match(value) if isinstance(value, str) else None
            valid = False
            if match:
                start, end = f"{match.group(1)}:{match.group(2)}", f"{match.group(3)}:{match.group(4)}"
                valid = start != end
            if not valid:
                raise ValueError(
                    _t("config.json: 'telegram.quiet_hours' muss None oder 'HH:MM-HH:MM' sein (Anfang darf nicht gleich Ende sein), ist {value!r}", value=value))
    _check_range_key(section, "telegram", "offline_min", minimum=1, maximum=1440, integer=True)
    _check_range_key(section, "telegram", "queue_stuck_min", minimum=1, maximum=1440, integer=True)
    _check_range_key(section, "telegram", "roll_low_m", minimum=0, maximum=30)


def _check_app(section: dict) -> None:
    for key, allowed in (("language", LANGUAGE_CHOICES), ("theme", THEME_CHOICES)):
        if key in section and section[key] not in allowed:
            text = ", ".join(f"'{v}'" for v in allowed)
            raise ValueError(_t("config.json: 'app.{key}' muss eines von {text} sein, ist {value!r}", key=key, text=text, value=section[key]))


def is_update_source(value) -> bool:
    """Ob `value` eine gültige Update-Quelle ist: `github:<owner>/<repo>`, `file:<Ordner>` (nicht leer)
    oder eine `https://`- bzw. `http://`-Adresse ohne Leerzeichen und ohne `#`."""
    if not isinstance(value, str):
        return False
    if value.startswith("github:"):
        return bool(_GITHUB_SOURCE_RE.match(value))
    if value.startswith("file:"):
        return bool(value[len("file:"):].strip())
    if value.startswith(("https://", "http://")):
        rest = value.split("://", 1)[1]
        return bool(rest) and not any(ch.isspace() for ch in value) and "#" not in value
    return False


def _check_update(section: dict) -> None:
    _check_bool_key(section, "update", "enabled")
    _check_bool_key(section, "update", "auto_install")
    if "source" in section and not is_update_source(section["source"]):
        raise ValueError(
            _t("config.json: 'update.source' muss github:<owner>/<repo>, file:<Ordner> oder eine http(s)-Adresse ohne Leerzeichen/# sein, ist {source!r}", source=section['source']))
    if "channel" in section and section["channel"] not in UPDATE_CHANNELS:
        raise ValueError(
            _t("config.json: 'update.channel' muss 'stable' oder 'beta' sein, ist {channel!r}", channel=section['channel']))
    _check_range_key(section, "update", "check_interval_h", minimum=1, maximum=720, integer=True)
    _check_range_key(section, "update", "idle_min", minimum=1, maximum=1440, integer=True)
    _check_range_key(section, "update", "keep_versions", minimum=1, maximum=5, integer=True)


def _check_modules(section: dict) -> None:
    """`modules.enabled`: Liste von Modulkennungen (Texte). Unbekannte Kennungen bleiben erlaubt
    (Vorwärtskompatibilität) und werden beim Lesen ignoriert."""
    if "enabled" not in section:
        return
    value = section["enabled"]
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(
            _t("config.json: 'modules.enabled' muss eine Liste von Modulkennungen sein, ist {value!r}", value=value))


def validate_config(cfg: dict) -> dict:
    """Prüft `cfg` vollständig (bisherige und sektionierte Schlüssel) und gibt
    es unverändert zurück. Jede vorhandene Sektion muss ein Objekt sein; bekannte Schlüssel
    werden typgeprüft, unbekannte Schlüssel innerhalb einer Sektion ignoriert (Vorwärtskompatibilität)."""
    if cfg.get("mac") is not None:
        cfg["mac"] = normalize_mac(cfg["mac"])
    _check_number(cfg, "idle_timeout_s", minimum=0, inclusive=True)
    _check_number(cfg, "connect_timeout_s", minimum=0, inclusive=False)
    if not isinstance(cfg.get("gui"), dict):
        raise ValueError(_t("config.json: 'gui' muss ein Objekt sein"))
    if not isinstance(cfg.get("tape"), dict):
        raise ValueError(_t("config.json: 'tape' muss ein Objekt sein"))
    _check_optional_text(cfg, "templates_dir")
    _check_cut_pause(cfg)
    _check_gui_screen_px(cfg["gui"])
    _check_gui_grid_dots(cfg["gui"])
    _check_gui_favorites(cfg["gui"])

    daemon = _section(cfg, "daemon")
    if daemon is not None:
        _check_daemon(daemon)

    queue = _section(cfg, "queue")
    if queue is not None:
        _check_queue(queue)

    status = _section(cfg, "status")
    if status is not None:
        _check_number_key(status, "status", "poll_s", minimum=0, inclusive=True)

    hotkey = _section(cfg, "hotkey")
    if hotkey is not None:
        _check_hotkey(hotkey)

    tray = _section(cfg, "tray")
    if tray is not None:
        _check_tray(tray)

    ble = _section(cfg, "ble")
    if ble is not None:
        _check_ble(ble)

    ssh = _section(cfg, "ssh")
    if ssh is not None:
        if "hosts" in ssh:
            _check_ssh_hosts(ssh["hosts"])
        _check_number_key(ssh, "ssh", "timeout_s", minimum=0, inclusive=False)
        _check_bool_key(ssh, "ssh", "strict_host_key")

    archive = _section(cfg, "archive")
    if archive is not None:
        _check_optional_text_key(archive, "archive", "dir")
        _check_bool_key(archive, "archive", "git_commit")

    backup = _section(cfg, "backup")
    if backup is not None:
        _check_optional_text_key(backup, "backup", "dir")
        _check_backup_keep(backup)
        _check_bool_key(backup, "backup", "auto_daily")

    numbering = _section(cfg, "numbering")
    if numbering is not None:
        _check_optional_text_key(numbering, "numbering", "dir")

    web = _section(cfg, "web")
    if web is not None:
        _check_web(web)

    app = _section(cfg, "app")
    if app is not None:
        _check_app(app)

    lan = _section(cfg, "lan")
    if lan is not None:
        _check_lan(lan)

    family = _section(cfg, "family")
    if family is not None:
        _check_family(family)

    mcp = _section(cfg, "mcp")
    if mcp is not None:
        _check_mcp(mcp)

    hotfolder = _section(cfg, "hotfolder")
    if hotfolder is not None:
        _check_hotfolder(hotfolder)

    mqtt = _section(cfg, "mqtt")
    if mqtt is not None:
        _check_mqtt(mqtt)

    telegram = _section(cfg, "telegram")
    if telegram is not None:
        _check_telegram(telegram)

    update = _section(cfg, "update")
    if update is not None:
        _check_update(update)

    modules = _section(cfg, "modules")
    if modules is not None:
        _check_modules(modules)

    return cfg


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = paths.config_path()
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return validate_config(cfg)


def save_config(updates: dict) -> dict:
    """Mischt `updates` in eine bestehende config.json (falls vorhanden) und schreibt sie atomar."""
    path = paths.config_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(updates)
    if data.get("mac") is not None:
        data["mac"] = normalize_mac(data["mac"])
    fileutil.atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    return data
