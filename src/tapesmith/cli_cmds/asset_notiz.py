"""Plugin-Befehl 'p12 asset-notiz': Vault-Notiz aus einem Asset anlegen.

`p12 asset-notiz ID` legt die Notiz `Assets/<ID>` über den MCP an (nie überschreibend) und gibt
den Pfad aus. `TRANSPORT` ersetzt Tests.
"""

from __future__ import annotations

import argparse
from datetime import date

from tapesmith.cli_cmds.base import CliContext
from tapesmith.integrations import cliprint, settings
from tapesmith.integrations.assetnote import create_note
from tapesmith.integrations.assets import AssetStore
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.i18n import N_, _t

COMMAND = "asset-notiz"
HELP = N_("Vault-Notiz aus einem Asset anlegen")

# Für Tests: httpx-Transport des Vault-Clients.
TRANSPORT = None


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", metavar="ID")


def _run(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    with AssetStore() as store:
        asset = store.get(args.id)
    if asset is None:
        raise KeyError(_t("Asset {id!r} gibt es nicht", id=args.id))
    vault = VaultClient.from_settings(data, transport=TRANSPORT)
    try:
        path = create_note(vault, data, asset, today=date.today())
    finally:
        vault.close()
    ctx.out(path)
    return 0


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return cliprint.run_guarded(ctx, lambda: _run(args, ctx))
