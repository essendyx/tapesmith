"""Routen /api/v1/homelab/proxmox.

`GET /homelab/proxmox/hosts` listet die eingerichteten Hosts (ohne Token-Werte),
`POST /homelab/proxmox/guests` liest Nodes und Gäste eines Hosts (nur GET gegen Proxmox),
`POST /homelab/proxmox/table` legt die gewählten Gäste als Tabelle für den Serien-Dialog ab
(Vorlage `vm-lxc-qr` mit Links, sonst `vm-lxc`). Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from tapesmith.integrations import credentials, proxmox
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.homelab_common import keyring_for, load_homelab, pending_table, transport_for
from tapesmith.i18n import _t

router = APIRouter()


class GuestsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    status: str | None = None
    kind: Literal["qemu", "lxc"] | None = None
    ids: str | None = None
    name: str | None = None


class TableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    vmids: list[int] = Field(min_length=1)
    links: bool = False


def _client(ctx: ApiContext, data: dict, host: str) -> proxmox.ProxmoxClient:
    return proxmox.ProxmoxClient.from_settings(data, host, keyring_module=keyring_for(ctx),
                                               transport=transport_for(ctx, "proxmox"))


def _networks(data: dict) -> list[str]:
    return list(data.get("plausi", {}).get("networks") or [])


@router.get("/homelab/proxmox/hosts")
def get_proxmox_hosts(ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    keyring = keyring_for(ctx)
    return {"hosts": [{"name": h.name, "url": h.url, "verify_tls": h.verify_tls,
                       "token_set": credentials.has_secret(h.token_ref, keyring_module=keyring),
                       "token_describe": credentials.describe_ref(h.token_ref)}
                      for h in proxmox.hosts_from_settings(data)]}


@router.post("/homelab/proxmox/guests")
def post_proxmox_guests(body: GuestsBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    host = proxmox.find_host(data, body.host)
    with _client(ctx, data, body.host) as client:
        nodes = client.nodes()
        guests = client.guests()
    guests = proxmox.filter_guests(guests, status=body.status or None, kind=body.kind,
                                   ids=body.ids or None, name=body.name or None)
    networks = _networks(data)
    return {"host": host.name, "nodes": [proxmox.node_json(n) for n in nodes],
            "guests": [proxmox.guest_json(g, networks) for g in guests],
            "warnings": proxmox.tls_warnings(host)}


@router.post("/homelab/proxmox/table")
def post_proxmox_table(body: TableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    host = proxmox.find_host(data, body.host)
    with _client(ctx, data, body.host) as client:
        by_id = {g.vmid: g for g in client.guests()}
    missing = [v for v in body.vmids if v not in by_id]
    if missing:
        raise ValueError(_t("VMID nicht gefunden auf {name}: {items}", name=host.name, items=', '.join(map(str, missing))))
    selected = [by_id[v] for v in dict.fromkeys(body.vmids)]
    warnings = proxmox.tls_warnings(host)
    links: dict[int, str] = {}
    if body.links:
        links, link_warnings = proxmox.guest_links(data, host, selected, keyring_module=keyring_for(ctx),
                                                   transport=transport_for(ctx, "shortlink"))
        warnings += link_warnings
    headers, rows = proxmox.guest_rows(selected, networks=_networks(data), links=links)
    pending_id = pending_table(ctx, headers, rows, f"Proxmox {host.name}")
    return {"pending_id": pending_id, "template": "vm-lxc-qr" if body.links else "vm-lxc",
            "count": len(rows), "warnings": warnings}
