"""`p12 mcp`: MCP-Server für Claude Code (stdio) und Anleitung zur Einrichtung.

Ohne Option läuft der stdio-Server; vorher wird nichts auf stdout geschrieben, weil dort nur das
MCP-Protokoll stehen darf. Der Prozess druckt nie selbst, sondern über den lokalen Druckdienst.
"""

import argparse
import sys

from tapesmith.cli_cmds.base import CliContext
from tapesmith.config import setting
from tapesmith.i18n import N_, _t

COMMAND = "mcp"
HELP = N_("MCP-Server für Claude (stdio); --config zeigt die Einrichtung")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", action="store_true",
                        help=_t("Einrichtung für Claude Code anzeigen (startet nichts)"))


def stdio_command() -> str:
    return f'claude mcp add p12 -- "{sys.executable}" -m tapesmith.cli mcp'


def http_url(cfg: dict) -> str:
    return f"http://127.0.0.1:{setting(cfg, 'web.port')}/mcp"


def http_command(cfg: dict) -> str:
    return (f"claude mcp add --transport http p12-http {http_url(cfg)} "
            '--header "Authorization: Bearer <TOKEN>"')


def _show_config(ctx: CliContext) -> int:
    cfg = ctx.load_config()
    ctx.out(_t("MCP-Server für Claude Code einrichten (stdio, empfohlen auf diesem PC):"))
    ctx.out(f"  {stdio_command()}")
    ctx.out("")
    if setting(cfg, "mcp.http"):
        ctx.out(_t("Alternativ über HTTP (Druckdienst muss laufen):"))
        ctx.out(f"  {http_command(cfg)}")
        ctx.out(_t("  <TOKEN> vorher anlegen mit: p12 token add Claude --rolle drucken"))
    else:
        ctx.out(_t("MCP über HTTP ist aus (mcp.http = false); einschalten mit: p12 config set mcp.http true"))
    ctx.out("")
    ctx.out(_t("Gedruckt wird nur nach einer Vorschau (label_preview) und mit confirm=true (label_print)."))
    return 0


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    if args.config:
        return _show_config(ctx)
    from tapesmith.mcpserver import server

    server.run_stdio()
    return 0
