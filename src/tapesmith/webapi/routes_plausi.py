"""Routen /api/v1/homelab/plausi und /api/v1/homelab/assets/{id}/vault-note.

`POST /homelab/plausi` prüft die Werte einer Vorlage (siehe `integrations.plausi`); der Server
blockiert nie, Fehler einer einzelnen Quelle (Asset-Register kaputt, Vault nicht erreichbar) werden
zu einem `info`-Befund statt zu einem Fehlerstatus. `POST /homelab/assets/{id}/vault-note` legt die
Notiz über `integrations.assetnote` an. Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tapesmith.integrations import scancache
from tapesmith.integrations import settings as settings_mod
from tapesmith.integrations.assetnote import NoteExists, create_note
from tapesmith.integrations.assets import AssetStore
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.integrations.plausi import Context, Finding, check, default_resolver, worst
from tapesmith.integrations.tia606 import KabelRegister
from tapesmith.templates.model import TemplateError
from tapesmith.templates.store import find_template
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.webapi.homelab_common import load_homelab, transport_for
from tapesmith.i18n import _t

router = APIRouter()

DNS_TIMEOUT_S = 2.0
_LEVEL_RANK = {"konflikt": 0, "warnung": 1, "info": 2}


class PlausiBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    values: dict[str, str] = {}
    vault: bool = False


def _timed_resolver(resolver: Callable[[str], list[str]], timeout_s: float) -> Callable[[str], list[str]]:
    """Begrenzt eine DNS-Auflösung auf `timeout_s` (eigener Thread, Zeitüberschreitung -> leer)."""

    def call(host: str) -> list[str]:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(resolver, host)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return []
        finally:
            # kein `with`-Block: dessen __exit__ würde shutdown(wait=True) rufen und auf den
            # ggf. weiterhin hängenden Resolver-Thread warten, das Zeitlimit wäre wirkungslos.
            pool.shutdown(wait=False)

    return call


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: _LEVEL_RANK[f.level])


@router.post("/homelab/plausi")
def plausi_check(body: PlausiBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        find_template(body.template)
    except TemplateError as exc:
        raise NotFound(str(exc)) from exc

    data = load_homelab(ctx)
    findings: list[Finding] = []
    scans = scancache.all_scans()

    assets: AssetStore | None = None
    assets_path = settings_mod.data_dir() / "assets.sqlite3"
    if assets_path.exists():
        try:
            assets = AssetStore()
        except Exception as exc:  # noqa: BLE001 (Quelle isolieren, Server blockiert nie)
            findings.append(Finding("info", None, "quelle_fehlt", _t("Asset-Register nicht lesbar: {exc}", exc=exc)))

    kabel: KabelRegister | None = None
    kabel_path = settings_mod.data_dir() / "kabel.json"
    if kabel_path.exists():
        kabel = KabelRegister()

    vault: VaultClient | None = None
    if body.vault:
        try:
            vault = VaultClient.from_settings(data, transport=transport_for(ctx, "obsidian"))
        except Exception as exc:  # noqa: BLE001 (Quelle isolieren)
            findings.append(Finding("info", None, "quelle_fehlt", _t("Vault nicht erreichbar: {exc}", exc=exc)))

    resolver = None
    if data["plausi"]["dns_check"]:
        base_resolver = ctx.extras.get("resolver") or default_resolver
        timeout = min(float(data["obsidian"].get("timeout_s", 10.0)), DNS_TIMEOUT_S)
        resolver = _timed_resolver(base_resolver, timeout)

    plausi_ctx = Context(scans=scans, networks=data["plausi"]["networks"], assets=assets, kabel=kabel,
                         vault=vault, resolver=resolver)
    try:
        findings.extend(check(body.template, body.values, plausi_ctx))
    finally:
        if assets is not None:
            assets.close()
        if vault is not None:
            vault.close()

    findings = _sorted(findings)
    return {"findings": [asdict(f) for f in findings], "worst": worst(findings)}


@router.post("/homelab/assets/{asset_id}/vault-note")
def assets_vault_note(asset_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with AssetStore() as store:
        asset = store.get(asset_id)
    if asset is None:
        raise NotFound(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
    vault = VaultClient.from_settings(data, transport=transport_for(ctx, "obsidian"))
    try:
        path = create_note(vault, data, asset, today=ctx.now().date())
    except NoteExists as exc:
        return JSONResponse(error_json("Conflict", str(exc)), status_code=409)
    finally:
        vault.close()
    return {"path": path}
