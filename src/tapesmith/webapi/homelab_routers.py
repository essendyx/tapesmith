"""Registrierung der Homelab-Router.

Eine Stelle für alle Homelab-Router, damit `webapi/app.py` nur einen Aufruf braucht. Die
Reihenfolge ist fest: Router mit festen Pfaden unter `/homelab/assets/...` kommen vor
Routen mit Pfadparametern, Kollisionen prüft `tests/test_e2e_homelab.py`.
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter, FastAPI

from tapesmith.webapi import homelab_common

ROUTER_MODULES = ("routes_homelab", "routes_zfs", "routes_proxmox", "routes_paperless", "routes_vault",
                  "routes_assets", "routes_kleinanzeigen", "routes_kabel", "routes_ha", "routes_codescan",
                  "routes_plausi")


def routers() -> list[APIRouter]:
    """Die `router`-Objekte aller Homelab-Routermodule in fester Reihenfolge."""
    return [importlib.import_module(f"tapesmith.webapi.{name}").router for name in ROUTER_MODULES]


def install(app: FastAPI, prefix: str) -> None:
    """Fehler-Handler für `IntegrationError` und alle Homelab-Router unter `prefix` einhängen."""
    homelab_common.install_integration_handler(app)
    for router in routers():
        app.include_router(router, prefix=prefix)
