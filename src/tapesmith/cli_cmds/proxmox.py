"""Plugin-Befehl 'p12 proxmox': VMs und LXCs aus der Proxmox-API lesen und als Serie drucken.

Unterbefehle: `hosts` (eingerichtete Hosts, Token vorhanden), `list HOST` (Gäste mit IP bzw.
Hinweis und durchgereichter Hardware) und `print HOST` (Serie über `vm-lxc`, mit `--links` über
`vm-lxc-qr` mit QR auf den Kurz-Link bzw. die Proxmox-Oberfläche). Gegen Proxmox gehen nur
GET-Anfragen. `TRANSPORT` und `SHORTLINK_TRANSPORT` ersetzen Tests durch MockTransports.
"""

from __future__ import annotations

import argparse
import json

from tapesmith.cli_cmds.base import CliContext
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import cliprint, credentials, proxmox, settings
from tapesmith.i18n import N_, _t

COMMAND = "proxmox"
HELP = N_("VMs und LXCs aus Proxmox lesen und als Label-Serie drucken")

TRANSPORT = None
SHORTLINK_TRANSPORT = None

DEFAULT_TEMPLATE = "vm-lxc"
QR_TEMPLATE = "vm-lxc-qr"
_KIND = {"vm": "qemu", "lxc": "lxc"}


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("host", metavar="HOST", help=_t("Name aus homelab.json 'proxmox.hosts'"))
    parser.add_argument("--status", choices=["running", "stopped"], help=_t("nur laufende bzw. gestoppte"))
    parser.add_argument("--typ", choices=["vm", "lxc"], help=_t("nur VMs bzw. LXCs"))
    parser.add_argument("--ids", metavar=_t("LISTE"), help=_t("VMIDs, z. B. 100-110,115"))
    parser.add_argument("--name", metavar="TEXT", help=_t("Namens-Teilstring (ohne Groß-/Kleinschreibung)"))


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="proxmox_cmd", required=True)
    sub.add_parser("hosts", help=_t("eingerichtete Proxmox-Hosts anzeigen"))
    p_list = sub.add_parser("list", help=_t("VMs und LXCs eines Hosts anzeigen"))
    _add_filters(p_list)
    p_list.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))
    p_print = sub.add_parser("print", help=_t("VMs und LXCs als Label-Serie drucken"))
    _add_filters(p_print)
    p_print.add_argument("--links", action="store_true",
                         help=_t("QR mit Kurz-Link bzw. Proxmox-Adresse (Vorlage vm-lxc-qr)"))
    cliprint.add_series_options(p_print, template=DEFAULT_TEMPLATE)


def _hosts(ctx: CliContext) -> int:
    hosts = proxmox.hosts_from_settings(settings.load_settings())
    if not hosts:
        ctx.out(_t("Keine Proxmox-Hosts eingerichtet (homelab.json 'proxmox.hosts')"))
        return EXIT_OK
    for host in hosts:
        token = "ok" if credentials.has_secret(host.token_ref) else "fehlt"
        tls = _t("geprüft") if host.verify_tls else _t("nicht geprüft")
        ctx.out(f"{host.name}  {host.url}  TLS {tls}  Token {token} ({credentials.describe_ref(host.token_ref)})")
    return EXIT_OK


def _load(args: argparse.Namespace, ctx: CliContext) -> tuple[dict, proxmox.PveHost, list[proxmox.Guest]]:
    data = settings.load_settings()
    host = proxmox.find_host(data, args.host)
    with proxmox.ProxmoxClient.from_settings(data, args.host, transport=TRANSPORT) as client:
        guests = client.guests()
    for warning in proxmox.tls_warnings(host):
        ctx.err(_t("Warnung: {warning}", warning=warning))
    guests = proxmox.filter_guests(guests, status=args.status, kind=_KIND.get(args.typ) if args.typ else None,
                                   ids=args.ids, name=args.name)
    return data, host, guests


def _networks(data: dict) -> list[str]:
    return list(data.get("plausi", {}).get("networks") or [])


def _list(args: argparse.Namespace, ctx: CliContext) -> int:
    data, host, guests = _load(args, ctx)
    networks = _networks(data)
    if args.json:
        ctx.out(json.dumps({"host": host.name, "guests": [proxmox.guest_json(g, networks) for g in guests]},
                           ensure_ascii=False, indent=2))
        return EXIT_OK
    if not guests:
        ctx.out(_t("Keine Gäste gefunden"))
        return EXIT_OK
    table = [("VMID", "Typ", _t("Name"), "Status", "IP", "Passthrough")]
    for g in guests:
        ip = ", ".join(g.ips) if g.ips else g.ip_note
        table.append((str(g.vmid), "VM" if g.kind == "qemu" else "LXC", g.name, g.status, ip,
                      "; ".join(g.passthrough)))
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]) - 1)]
    for row in table:
        ctx.out("  ".join(cell.ljust(w) for cell, w in zip(row, widths)) + "  " + row[-1])
    return EXIT_OK


def _print(args: argparse.Namespace, ctx: CliContext) -> int:
    data, host, guests = _load(args, ctx)
    if not guests:
        ctx.err(_t("Keine Gäste für diesen Filter gefunden"))
        return EXIT_ERROR
    links: dict[int, str] = {}
    template = args.template
    if args.links:
        links, warnings = proxmox.guest_links(data, host, guests, transport=SHORTLINK_TRANSPORT)
        for warning in warnings:
            ctx.err(_t("Warnung: {warning}", warning=warning))
        if template == DEFAULT_TEMPLATE:
            template = QR_TEMPLATE
    headers, rows = proxmox.guest_rows(guests, networks=_networks(data), links=links)
    return cliprint.print_rows(ctx, args, template, [dict(zip(headers, row)) for row in rows])


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    cmd = args.proxmox_cmd
    if cmd == "hosts":
        return _hosts(ctx)
    if cmd == "list":
        return _list(args, ctx)
    if cmd == "print":
        return _print(args, ctx)
    raise ValueError(_t("Unbekannter Unterbefehl 'proxmox {cmd}'", cmd=cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return cliprint.run_guarded(ctx, lambda: _dispatch(args, ctx))
