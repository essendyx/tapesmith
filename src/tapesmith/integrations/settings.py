"""Einstellungsdatei `homelab.json` der Homelab-Integrationen.

Eigene Datei neben `config.json`, damit die Integrationen die Kern-Konfiguration nicht anfassen. Gespeichert
werden nur Abweichungen von `DEFAULTS`; beim Laden wird je Sektion flach verschmolzen. Token-Werte
stehen nie in der Datei, nur Secret-Referenzen (`credentials`).
"""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tapesmith import paths
from tapesmith.fileutil import atomic_write_text
from tapesmith.integrations import credentials
from tapesmith.i18n import _t

FILE_NAME = "homelab.json"

DEFAULTS = {
    # Homelab-Integrationen sind ohne Angaben aus: keine Adressen, keine Token-Pfade vorgegeben.
    "paperless": {"url": None, "public_url": None, "token_ref": None,
                  "asn_range": "asn", "asn_prefix": "ASN", "asn_width": 5,
                  "warranty_fields": {"kaufdatum": "Kaufdatum", "garantie_monate": "Garantie Monate",
                                      "garantie_bis": "Garantie bis"},
                  "timeout_s": 10.0},
    "proxmox": {"hosts": [], "timeout_s": 10.0},
    "obsidian": {"mcp_url": None, "vault_dir": None,
                 "attachments_dir": "Anhänge/Labels", "folders": ["Hosts", "Dienste"],
                 "append_after_print": False, "timeout_s": 10.0},
    "shortlink": {"base_url": None, "admin_url": None,
                  "token_ref": None, "timeout_s": 10.0},
    "homeassistant": {"url": None, "token_ref": None,
                      "todo_entity": None, "battery_below": 101, "timeout_s": 10.0},
    "assets": {"range": "asset", "prefix": "HL-", "width": 4, "check_digit": False},
    "kleinanzeigen": {"range": "ka", "prefix": "KA-", "width": 3},
    "kabel": {"range": "kabel", "prefix": "K-", "width": 3,
              "tia_pattern": "{rack}.U{unit:02}:P{port:02}"},
    "plausi": {"networks": ["192.168.0.0/16"], "dns_check": True},
}

_URL_KEYS = {"paperless.url", "paperless.public_url", "obsidian.mcp_url", "shortlink.base_url",
             "shortlink.admin_url", "homeassistant.url"}
_WIDTH_KEYS = {"paperless.asn_width", "assets.width", "kleinanzeigen.width", "kabel.width"}
_RANGE_KEYS = {"paperless.asn_range", "assets.range", "kleinanzeigen.range", "kabel.range"}
_PREFIX_KEYS = {"paperless.asn_prefix", "assets.prefix", "kleinanzeigen.prefix", "kabel.prefix"}
_BOOL_KEYS = {"assets.check_digit", "obsidian.append_after_print", "plausi.dns_check"}
_TOKEN_SECTIONS = ("paperless", "shortlink", "homeassistant")

_RANGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PREFIX_RE = re.compile(r"^[A-Z0-9-]{0,12}$")
_TODO_RE = re.compile(r"^todo\.[a-z0-9_]+$")
_HOST_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_HOST_KEYS = ("name", "url", "token_ref", "verify_tls")
_WARRANTY_KEYS = ("kaufdatum", "garantie_monate", "garantie_bis")

SERVICE_LABELS = {"paperless": "Paperless", "proxmox": "Proxmox", "obsidian": "Obsidian",
                  "homeassistant": "Home Assistant", "shortlink": "Kurz-Link-Dienst"}


class SettingsError(ValueError):
    """Ungültige Einstellungen; `errors` enthält alle Meldungen einzeln."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def settings_path() -> Path:
    """Pfad der Einstellungsdatei: `<App-Verzeichnis>/homelab.json`."""
    return paths.app_dir() / FILE_NAME


def data_dir() -> Path:
    """Laufzeitdaten der Integrationen: `<App-Verzeichnis>/homelab` (wird angelegt)."""
    path = paths.app_dir() / "homelab"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------- Prüfung ----------

def _msg(key: str, text: str) -> str:
    return f"homelab.json: '{key}' {text}"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _url_problem(value: Any, *, https_only: bool = False) -> str | None:
    schemes = ("https://",) if https_only else ("http://", "https://")
    if not isinstance(value, str) or not value.startswith(schemes) or len(value) <= len(schemes[-1]):
        art = "https-URL" if https_only else _t("URL mit http:// oder https://")
        return _t("muss eine {art} sein", art=art)
    if any(ch.isspace() for ch in value) or "#" in value:
        return _t("darf keine Leerzeichen und kein '#' enthalten")
    if value.endswith("/"):
        return _t("darf nicht mit '/' enden")
    return None


def _ref_problem(value: Any) -> str | None:
    try:
        credentials.check_ref(value)
    except ValueError as exc:
        return _t("muss eine gültige Secret-Referenz sein (keyring:<dienst>/<benutzer>, file:<pfad>, env:<NAME>): {exc}", exc=exc)
    return None


def _rel_path_problem(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return _t("muss ein nicht leerer Pfad sein")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return _t("muss ein relativer Pfad sein")
    if ".." in normalized.split("/"):
        return _t("darf kein '..' enthalten")
    return None


def _check_hosts(value: Any) -> list[str]:
    key = "proxmox.hosts"
    if not isinstance(value, list):
        return [_msg(key, _t("muss eine Liste sein"))]
    errors: list[str] = []
    seen: set[str] = set()
    for i, host in enumerate(value, start=1):
        where = _t("Eintrag {i}", i=i)
        if not isinstance(host, dict):
            errors.append(_msg(key, _t("{where} muss ein Objekt sein", where=where)))
            continue
        for extra in host:
            if extra not in _HOST_KEYS:
                errors.append(_msg(key, _t("{where}: unbekannter Schlüssel '{extra}'", where=where, extra=extra)))
        name = host.get("name")
        if not isinstance(name, str) or not _HOST_NAME_RE.match(name):
            errors.append(_msg(key, _t("{where}: Name muss 1 bis 32 Zeichen aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich sein", where=where)))
        elif name.lower() in seen:
            errors.append(_msg(key, _t("{where}: Name '{name}' ist doppelt", where=where, name=name)))
        else:
            seen.add(name.lower())
        problem = _url_problem(host.get("url"), https_only=True)
        if problem:
            errors.append(_msg(key, f"{where}: url {problem}"))
        # Ohne Token (noch nicht gesetzt) ist ein Host gültig; das Token setzt die Oberfläche.
        problem = None if host.get("token_ref") is None else _ref_problem(host.get("token_ref"))
        if problem:
            errors.append(_msg(key, f"{where}: token_ref {problem}"))
        if not isinstance(host.get("verify_tls", False), bool):
            errors.append(_msg(key, _t("{where}: verify_tls muss true oder false sein", where=where)))
    return errors


def _check_value(key: str, value: Any, default: Any) -> list[str]:
    section, _, name = key.partition(".")
    if key == "proxmox.hosts":
        return _check_hosts(value)
    if key in _URL_KEYS:
        if value is None and default is None:
            return []
        problem = _url_problem(value)
        return [_msg(key, problem)] if problem else []
    if name == "token_ref":
        if value is None:
            return []
        problem = _ref_problem(value)
        return [_msg(key, problem)] if problem else []
    if name == "timeout_s":
        if not _is_number(value) or not 1 <= value <= 120:
            return [_msg(key, _t("muss eine Zahl von 1 bis 120 sein"))]
        return []
    if key in _WIDTH_KEYS:
        if not _is_int(value) or not 0 <= value <= 12:
            return [_msg(key, _t("muss eine ganze Zahl von 0 bis 12 sein"))]
        return []
    if key in _RANGE_KEYS:
        if not isinstance(value, str) or not _RANGE_RE.match(value):
            return [_msg(key, _t("muss 1 bis 32 Zeichen aus A-Z, a-z, 0-9, Unterstrich, Bindestrich haben"))]
        return []
    if key in _PREFIX_KEYS:
        if not isinstance(value, str) or not _PREFIX_RE.match(value):
            return [_msg(key, _t("muss ein Text bis 12 Zeichen aus A-Z, 0-9 und Bindestrich sein (Großbuchstaben)"))]
        return []
    if key in _BOOL_KEYS:
        return [] if isinstance(value, bool) else [_msg(key, _t("muss true oder false sein"))]
    if key == "homeassistant.battery_below":
        if not _is_int(value) or not 1 <= value <= 101:
            return [_msg(key, _t("muss eine ganze Zahl von 1 bis 101 sein"))]
        return []
    if key == "homeassistant.todo_entity":
        if value is None or (isinstance(value, str) and _TODO_RE.match(value)):
            return []
        return [_msg(key, _t("muss leer sein oder die Form todo.<name> haben"))]
    if key == "obsidian.folders":
        if not isinstance(value, list) or not value:
            return [_msg(key, _t("muss eine nicht leere Liste von Ordnernamen sein"))]
        errors = []
        for folder in value:
            if (not isinstance(folder, str) or not folder.strip() or folder.startswith(("/", "\\"))
                    or ".." in folder.replace("\\", "/").split("/")):
                errors.append(_msg(key, _t("enthält ungültigen Ordner {folder!r} (ohne '..', ohne führenden '/')", folder=folder)))
        return errors
    if key == "obsidian.vault_dir":
        if value is None or (isinstance(value, str) and value.strip()):
            return []
        return [_msg(key, _t("muss leer (null) oder ein Pfad sein"))]
    if key == "obsidian.attachments_dir":
        problem = _rel_path_problem(value)
        return [_msg(key, problem)] if problem else []
    if key == "plausi.networks":
        if not isinstance(value, list) or not value:
            return [_msg(key, _t("muss eine nicht leere Liste von IPv4-Netzen sein"))]
        errors = []
        for net in value:
            try:
                if not isinstance(net, str):
                    raise ValueError
                ipaddress.IPv4Network(net, strict=False)
            except ValueError:
                errors.append(_msg(key, _t("enthält kein gültiges IPv4-Netz: {net!r}", net=net)))
        return errors
    if key == "paperless.warranty_fields":
        if (not isinstance(value, dict) or set(value) != set(_WARRANTY_KEYS)
                or not all(isinstance(v, str) and v.strip() for v in value.values())):
            return [_msg(key, _t("muss ein Objekt mit den Texten kaufdatum, garantie_monate, garantie_bis sein"))]
        return []
    if key == "kabel.tia_pattern":
        if not isinstance(value, str) or not value.strip():
            return [_msg(key, _t("muss ein nicht leerer Text sein"))]
        return []
    return []


def validate(data: dict) -> list[str]:
    """Prüft vollständige Einstellungen und gibt alle Meldungen zurück (leer = gültig)."""
    if not isinstance(data, dict):
        return [_t("homelab.json: muss ein JSON-Objekt sein")]
    errors: list[str] = []
    for section, defaults in DEFAULTS.items():
        values = data.get(section, defaults)
        if not isinstance(values, dict):
            errors.append(_msg(section, _t("muss ein Objekt sein")))
            continue
        for name, default in defaults.items():
            if name in values:
                errors.extend(_check_value(f"{section}.{name}", values[name], default))
        for name in values:
            if name not in defaults:
                errors.append(_t("homelab.json: unbekannter Schlüssel '{section}.{name}'", section=section, name=name))
    for section in data:
        if section not in DEFAULTS:
            errors.append(_t("homelab.json: unbekannter Schlüssel '{section}'", section=section))
    return errors


# ---------- Laden und Speichern ----------

def _merge(file_data: dict) -> dict:
    result = copy.deepcopy(DEFAULTS)
    for section, values in file_data.items():
        if section in DEFAULTS and isinstance(values, dict):
            result[section] = {**result[section], **copy.deepcopy(values)}
        else:
            result[section] = copy.deepcopy(values)
    return result


def _read_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(_t("{file_name}: kein gültiges JSON ({exc})", file_name=FILE_NAME, exc=exc)) from exc
    if not isinstance(data, dict):
        raise ValueError(_t("{file_name}: muss ein JSON-Objekt sein", file_name=FILE_NAME))
    return data


def load_settings(path: Path | None = None) -> dict:
    """Lädt `homelab.json`, verschmolzen mit `DEFAULTS`. Ungültig: ValueError mit allen Meldungen."""
    path = settings_path() if path is None else Path(path)
    data = _merge(_read_file(path))
    errors = validate(data)
    if errors:
        raise SettingsError(errors)
    return data


def load_unchecked(path: Path | None = None) -> dict:
    """Wie `load_settings`, aber ohne Prüfung (für Reparaturen und das Setzen einzelner Werte)."""
    path = settings_path() if path is None else Path(path)
    return _merge(_read_file(path))


def setting(data: dict, key: str):
    """Wert zu `"sektion.schlüssel"`; unbekannt: KeyError."""
    section, sep, name = key.partition(".")
    if not sep or section not in data or not isinstance(data[section], dict) or name not in data[section]:
        raise KeyError(_t("Unbekannte Einstellung '{key}'", key=key))
    return data[section][name]


def _differences(data: dict) -> dict:
    diff: dict = {}
    for section, defaults in DEFAULTS.items():
        changed = {name: value for name, value in data[section].items()
                   if name not in defaults or value != defaults[name]}
        if changed:
            diff[section] = changed
    return diff


def update_settings(changes: Mapping[str, Any], *, path: Path | None = None) -> dict:
    """Wendet mehrere Änderungen gemeinsam an, prüft alles und schreibt in einem Vorgang.

    Ungültig: `SettingsError` (ValueError) mit allen Meldungen, Datei bleibt unverändert."""
    path = settings_path() if path is None else Path(path)
    # Ohne Vorab-Prüfung laden, damit eine ungültige Datei über Änderungen reparierbar bleibt.
    data = _merge(_read_file(path))
    errors: list[str] = []
    for key, value in changes.items():
        section, sep, name = key.partition(".")
        if not sep or section not in DEFAULTS or name not in DEFAULTS[section]:
            errors.append(_t("homelab.json: unbekannter Schlüssel '{key}'", key=key))
            continue
        data[section][name] = copy.deepcopy(value)
    errors.extend(validate(data))
    if errors:
        raise SettingsError(errors)
    atomic_write_text(path, json.dumps(_differences(data), indent=2, ensure_ascii=False) + "\n")
    return data


def set_setting(key: str, value, *, path: Path | None = None) -> dict:
    """Setzt einen Wert (Listen werden ganz ersetzt), prüft und speichert atomar."""
    return update_settings({key: value}, path=path)


# ---------- Öffentliche Sicht und Prüfung ----------

def _token_info(ref: str | None, **kw) -> dict:
    return {"token_describe": credentials.describe_ref(ref),
            "token_set": credentials.has_secret(ref, **kw)}


def public_view(data: dict, *, keyring_module=None, environ=None) -> dict:
    """Einstellungen ohne Token-Werte, je Referenz mit `token_describe` und `token_set`."""
    kw = {"keyring_module": keyring_module, "environ": environ}
    view = copy.deepcopy(data)
    for section, values in view.items():
        if isinstance(values, dict) and "token_ref" in values:
            values.update(_token_info(values["token_ref"], **kw))
    for host in view.get("proxmox", {}).get("hosts", []):
        if isinstance(host, dict):
            host.update(_token_info(host.get("token_ref"), **kw))
    return view


def _service(service_id: str, label: str, configured: bool, token_set: bool | None, detail: str) -> dict:
    return {"id": service_id, "label": label, "configured": configured, "token_set": token_set,
            "detail": detail}


def _token_detail(ref: str | None, token_set: bool) -> str:
    state = _t("Token vorhanden") if token_set else _t("Token fehlt")
    return f"{state} ({credentials.describe_ref(ref)})"


def check_services(data: dict, *, keyring_module=None, environ=None) -> list[dict]:
    """Prüfung je Dienst ohne Netz: eingerichtet, Token vorhanden, Hinweis."""
    kw = {"keyring_module": keyring_module, "environ": environ}
    services: list[dict] = []

    paperless = data["paperless"]
    token_set = credentials.has_secret(paperless.get("token_ref"), **kw)
    services.append(_service("paperless", "Paperless", bool(paperless.get("url")), token_set,
                             f"{paperless.get('url')} · {_token_detail(paperless.get('token_ref'), token_set)}"))

    hosts = data["proxmox"].get("hosts") or []
    if not hosts:
        services.append(_service("proxmox", "Proxmox", False, None, _t("Keine Proxmox-Hosts eingetragen")))
    for host in hosts:
        token_set = credentials.has_secret(host.get("token_ref"), **kw)
        services.append(_service(f"proxmox:{host.get('name')}", f"Proxmox {host.get('name')}",
                                 bool(host.get("url")), token_set,
                                 f"{host.get('url')} · {_token_detail(host.get('token_ref'), token_set)}"))

    obsidian = data["obsidian"]
    mcp_url, vault_dir = obsidian.get("mcp_url"), obsidian.get("vault_dir")
    detail = _t("{mcp_url} · ohne Token (nur LAN)", mcp_url=mcp_url) if mcp_url else (_t("Vault-Ordner {vault_dir}", vault_dir=vault_dir) if vault_dir
                                                                  else _t("obsidian.mcp_url fehlt"))
    services.append(_service("obsidian", "Obsidian", bool(mcp_url or vault_dir), None, detail))

    ha = data["homeassistant"]
    token_set = credentials.has_secret(ha.get("token_ref"), **kw)
    services.append(_service("homeassistant", "Home Assistant", bool(ha.get("url")), token_set,
                             f"{ha.get('url')} · {_token_detail(ha.get('token_ref'), token_set)}"))

    link = data["shortlink"]
    base_url = link.get("base_url")
    token_set = credentials.has_secret(link.get("token_ref"), **kw)
    detail = (f"{base_url} · {_token_detail(link.get('token_ref'), token_set)}" if base_url
              else _t("shortlink.base_url fehlt (QR-Codes enthalten dann die lange Adresse)"))
    services.append(_service("shortlink", _t("Kurz-Link-Dienst"), bool(base_url), token_set, detail))
    return services
