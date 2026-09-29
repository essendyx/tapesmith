"""Routen /api/v1/access: Tokens, Einstellungen, Secrets, Telegram-Test.

Nur Rolle `admin` (zusätzlich zur Rollen-Tabelle aus `webapi.access` über `require_role`). Verwaltet die
Sektionen `lan`, `family`, `mcp`, `hotfolder`, `mqtt`, `telegram`, API-Tokens
(`tapesmith.apitokens`) und die Secret-Referenzen aus `tapesmith.secretref`.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tapesmith import config as config_mod
from tapesmith import netinfo, paths, secretref
from tapesmith.automation import telegram
from tapesmith.templates.store import list_templates
from tapesmith.webapi.access import ROLE_FAMILY, require_role
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound
from tapesmith.i18n import N_, _t

router = APIRouter(dependencies=[Depends(require_role("admin"))])

log = logging.getLogger(__name__)

ACCESS_SECTIONS = ("lan", "family", "mcp", "hotfolder", "mqtt", "telegram")
ACCESS_KEYS = tuple(f"{s}.{k}" for s in ACCESS_SECTIONS for k in config_mod.SECTION_DEFAULTS[s])

_TOKEN_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_SECRET_NAMES = ("mqtt", "telegram")
_SECRET_REF_KEY = {"mqtt": "mqtt.password_ref", "telegram": "telegram.token_ref"}
_NO_FILE_SECRET = N_("Wert in der Datei bzw. Umgebungsvariable pflegen")


class PatchAccessBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    changes: dict[str, Any]


class CreateTokenBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    role: str


class SetSecretBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str


class TelegramTestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------- AccessJson ----------

def _section_dict(cfg: dict, section: str) -> dict:
    return {key: config_mod.setting(cfg, f"{section}.{key}") for key in config_mod.SECTION_DEFAULTS[section]}


def _has_secret(ref: str | None, keyring_module) -> bool:
    if not ref:
        return False
    try:
        return secretref.has_secret(ref, keyring_module=keyring_module)
    except Exception:  # noqa: BLE001 (jede Ausnahme beim Prüfen gilt als "nicht gesetzt")
        return False


def access_json(ctx: ApiContext) -> dict:
    cfg = ctx.config()
    keyring_module = ctx.extras.get("keyring")
    addresses = ctx.extras.get("addresses")

    lan_section = _section_dict(cfg, "lan")
    family_section = _section_dict(cfg, "family")
    mcp_section = _section_dict(cfg, "mcp")
    hotfolder_section = _section_dict(cfg, "hotfolder")
    mqtt_section = _section_dict(cfg, "mqtt")
    telegram_section = _section_dict(cfg, "telegram")

    lan_config = ctx.extras.get("lan_config")
    if lan_config is None:
        lan_config = dict(config_mod.SECTION_DEFAULTS["lan"])

    local_addresses = list(addresses) if addresses is not None else netinfo.local_ipv4_addresses()

    templates = sorted(list_templates(), key=lambda t: t.name)

    addons_manager = ctx.extras.get("addons")
    addon_statuses = addons_manager.statuses() if addons_manager is not None else []

    hotfolder_dir = hotfolder_section["dir"]
    effective_dir = hotfolder_dir if hotfolder_dir else str(paths.app_dir() / "hotfolder")

    return {
        "lan": {
            **lan_section,
            "active": bool(ctx.lan.enabled) and not ctx.extras.get("lan_error"),
            "restart_needed": lan_section != lan_config,
            "listen": list(ctx.extras.get("listen", [f"127.0.0.1:{ctx.port}"])),
            "base_urls": netinfo.lan_base_urls(cfg, addresses),
        },
        "local_addresses": local_addresses,
        "tokens": [t.to_json() for t in ctx.tokens.list()],
        "family": {
            **family_section,
            "available": [{"name": t.name, "description": t.description} for t in templates],
        },
        "mcp": {
            **mcp_section,
            "url": f"http://127.0.0.1:{ctx.port}/mcp",
            "stdio_command": f"{sys.executable} -m tapesmith.cli mcp",
        },
        "hotfolder": {**hotfolder_section, "effective_dir": effective_dir},
        "mqtt": {
            **mqtt_section,
            "password_describe": secretref.describe_ref(mqtt_section["password_ref"]),
            "password_set": _has_secret(mqtt_section["password_ref"], keyring_module),
        },
        "telegram": {
            **telegram_section,
            "token_describe": secretref.describe_ref(telegram_section["token_ref"]),
            "token_set": _has_secret(telegram_section["token_ref"], keyring_module),
        },
        "addons": addon_statuses,
    }


# ---------- Routen ----------

@router.get("/access", summary="Zugriffsdaten abrufen")
def get_access(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return access_json(ctx)


@router.patch("/access/settings", summary="LAN-, Familien-, MCP-, Hotfolder-, MQTT- und Telegram-Einstellungen ändern")
def patch_access_settings(body: PatchAccessBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    current = config_mod.load_config()
    candidate = dict(current)
    touched: dict[str, dict] = {}
    for key, value in body.changes.items():
        if key not in ACCESS_KEYS:
            raise ValueError(_t("Unbekannter Schlüssel '{key}' (nicht in ACCESS_KEYS)", key=key))
        section_name, _, sub_key = key.partition(".")
        existing = candidate.get(section_name)
        section = dict(existing) if isinstance(existing, dict) else {}
        section[sub_key] = value
        candidate[section_name] = section
        touched[section_name] = section
    config_mod.validate_config(candidate)
    for section_name, section in touched.items():
        config_mod.save_config({section_name: section})
    ctx.service.request_reload()
    ctx.publish("config", {"keys": list(body.changes.keys())})
    return access_json(ctx)


@router.post("/access/tokens", summary="API-Token anlegen")
def post_access_tokens(body: CreateTokenBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    info, secret = ctx.tokens.create(body.name, body.role)
    log.info("API-Token angelegt: %s (%s)", info.name, info.id)
    family_urls: list[str] = []
    if info.role == ROLE_FAMILY:
        cfg = ctx.config()
        # Ohne lan.enabled ist der Dienst aus dem Heimnetz nicht erreichbar, ein Link waere
        # irrefuehrend (dasselbe gilt fuer "p12 token add", cli_cmds/token.py).
        if config_mod.setting(cfg, "lan.enabled"):
            addresses = ctx.extras.get("addresses")
            family_urls = [f"{base}/familie#t={secret}" for base in netinfo.lan_base_urls(cfg, addresses)]
    return {"token": info.to_json(), "secret": secret, "family_urls": family_urls}


@router.delete("/access/tokens/{token_id}", summary="API-Token löschen")
def delete_access_token(token_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if not _TOKEN_ID_RE.match(token_id):
        raise NotFound(_t("Token '{token_id}' unbekannt", token_id=token_id))
    try:
        info = ctx.tokens.revoke(token_id)
    except KeyError as exc:
        raise NotFound(_t("Token '{token_id}' unbekannt", token_id=token_id)) from exc
    log.info("API-Token gelöscht: %s (%s)", info.name, info.id)
    return {}


@router.put("/access/secrets/{name}", summary="Geheimwert (MQTT-Passwort, Telegram-Token) setzen")
def put_access_secret(name: str, body: SetSecretBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if name not in _SECRET_NAMES:
        raise NotFound(_t("Secret '{name}' unbekannt (erlaubt: {items})", name=name, items=', '.join(_SECRET_NAMES)))
    cfg = ctx.config()
    ref = config_mod.setting(cfg, _SECRET_REF_KEY[name])
    if not ref or not str(ref).startswith("keyring:"):
        raise ValueError(_t(_NO_FILE_SECRET))
    if not body.value:
        raise ValueError(_t("Wert darf nicht leer sein"))
    secretref.write_secret(ref, body.value, keyring_module=ctx.extras.get("keyring"))
    return {"set": True, "describe": secretref.describe_ref(ref)}


@router.post("/access/telegram/test", summary="Telegram-Testnachricht senden")
def post_access_telegram_test(_body: TelegramTestBody | None = None,
                              ctx: ApiContext = Depends(get_ctx)) -> dict:
    ok, error = telegram.send_test(ctx.config(), http_post=ctx.extras.get("http_post"),
                                   keyring_module=ctx.extras.get("keyring"))
    return {"ok": ok, "error": error}
