"""Proxmox-API-Import: Nodes, VMs und LXCs mit IP und durchgereichter Hardware.

Nur lesende GET-Aufrufe über die Proxmox-API (`/api2/json`), Anmeldung mit einem API-Token
(`Authorization: PVEAPIToken=user@realm!name=uuid`), das erst zur Laufzeit über eine
Secret-Referenz gelesen wird. Fehlen Rechte oder läuft der Guest-Agent nicht, bricht nichts ab:
der Gast bekommt einen Hinweis in `ip_note` ("IP unbekannt: ..."). Die Rolle mit genau den
nötigen Leserechten legt `deploy/infra/proxmox-tapesmith-role.sh` an.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from tapesmith.integrations import shortlink
from tapesmith.integrations.credentials import read_secret
from tapesmith.integrations.errors import AuthFailed, UpstreamError
from tapesmith.integrations.httpclient import make_client, parse_json, request_json, request_raw
from tapesmith.i18n import N_, _t

API = "/api2/json"
MAX_GUESTS = 200
KINDS = ("qemu", "lxc")

NOTE_STOPPED = N_("IP unbekannt: gestoppt")
NOTE_AGENT = N_("IP unbekannt: Guest-Agent läuft nicht")
NOTE_AUDIT = N_("IP unbekannt: Recht VM.GuestAgent.Audit fehlt")
NOTE_MONITOR = N_("IP unbekannt: Recht VM.Monitor fehlt")
NOTE_DHCP = N_("IP unbekannt: DHCP")
NOTE_UNKNOWN = N_("IP unbekannt")
SHORTLINK_MISSING = N_("Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Proxmox-Adresse")

ROW_HEADERS = ["typ", "vmid", "name", "ip_kurz", "ip", "node", "host", "link"]
_AGENT_DOWN = ("qemu guest agent is not running", "no qemu guest agent configured")
_PASS_QEMU = [f"hostpci{i}" for i in range(16)] + [f"usb{i}" for i in range(15)]
_PASS_LXC = [f"dev{i}" for i in range(10)]
_NET_KEYS = [f"net{i}" for i in range(10)]
_IDS_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


@dataclass(frozen=True)
class PveHost:
    name: str
    url: str
    token_ref: str
    verify_tls: bool = False


@dataclass(frozen=True)
class Guest:
    host: str
    node: str
    vmid: int
    kind: str
    name: str
    status: str
    tags: tuple[str, ...]
    ips: tuple[str, ...]
    ip_note: str
    passthrough: tuple[str, ...]


@dataclass(frozen=True)
class NodeInfo:
    host: str
    node: str
    status: str
    ip: str | None


def hosts_from_settings(data: dict) -> list[PveHost]:
    """Alle Proxmox-Hosts aus `homelab.json` (`proxmox.hosts`)."""
    hosts = []
    for entry in data.get("proxmox", {}).get("hosts") or []:
        hosts.append(PveHost(name=str(entry["name"]), url=str(entry["url"]).rstrip("/"),
                             token_ref=str(entry.get("token_ref") or ""),
                             verify_tls=bool(entry.get("verify_tls", False))))
    return hosts


def find_host(data: dict, name: str) -> PveHost:
    """Host nach Name; unbekannt: ValueError mit der Liste der eingerichteten Hosts."""
    hosts = hosts_from_settings(data)
    for host in hosts:
        if host.name == name:
            return host
    known = ", ".join(h.name for h in hosts) or "keine"
    raise ValueError(_t("Unbekannter Proxmox-Host '{name}' (eingerichtet: {known}; in homelab.json 'proxmox.hosts' eintragen)", name=name, known=known))


def tls_warnings(host: PveHost) -> list[str]:
    """Warnung, wenn das TLS-Zertifikat des Hosts nicht geprüft wird."""
    return [] if host.verify_tls else [_t("TLS-Zertifikat von {name} wird nicht geprüft", name=host.name)]


def _networks(networks: Sequence[str]) -> list[ipaddress.IPv4Network]:
    result = []
    for net in networks:
        try:
            result.append(ipaddress.IPv4Network(net, strict=False))
        except ValueError:
            continue
    return result


def _usable_ipv4(text: str) -> str | None:
    try:
        ip = ipaddress.ip_address(str(text).split("/")[0].strip())
    except ValueError:
        return None
    if ip.version != 4 or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return None
    return str(ip)


def _sort_ips(ips: Sequence[str], networks: Sequence[str]) -> tuple[str, ...]:
    nets = _networks(networks)
    unique = list(dict.fromkeys(ips))

    def key(item: tuple[int, str]):
        index, ip = item
        addr = ipaddress.IPv4Address(ip)
        return (not any(addr in n for n in nets), not addr.is_private, index)

    return tuple(ip for _, ip in sorted(enumerate(unique), key=key))


def _reason(response: httpx.Response) -> str:
    parts = [response.reason_phrase or ""]
    try:
        parts.append(response.text)
    except Exception:  # noqa: BLE001 (unlesbarer Körper)
        pass
    return " ".join(parts)


def _split_options(value: str) -> dict[str, str]:
    options = {}
    for part in str(value).split(","):
        key, sep, val = part.partition("=")
        if sep:
            options[key.strip()] = val.strip()
    return options


class ProxmoxClient:
    """Lesender Zugriff auf einen Proxmox-Host (nur GET)."""

    def __init__(self, host: PveHost, token: str, *, timeout_s: float = 10.0, transport=None,
                 networks: Sequence[str] = ()):
        self.host = host
        self.service = f"Proxmox {host.name}"
        self.networks = list(networks)
        self._client = make_client(host.url, service=self.service,
                                   headers={"Authorization": f"PVEAPIToken={token}"},
                                   timeout_s=timeout_s, verify=host.verify_tls, transport=transport)

    @classmethod
    def from_settings(cls, data: dict, name: str, *, keyring_module=None, environ=None,
                      transport=None) -> ProxmoxClient:
        """Client für den Host `name` aus `homelab.json`, Token über dessen `token_ref`."""
        host = find_host(data, name)
        token = read_secret(host.token_ref, what=f"Proxmox {name}", keyring_module=keyring_module,
                            environ=environ)
        timeout = float(data.get("proxmox", {}).get("timeout_s") or 10.0)
        networks = data.get("plausi", {}).get("networks") or []
        return cls(host, token, timeout_s=timeout, transport=transport, networks=networks)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ProxmoxClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # Grundaufrufe ------------------------------------------------------------------------------

    def _get(self, path: str, **kw) -> Any:
        body = request_json(self._client, "GET", API + path, service=self.service, **kw)
        if not isinstance(body, dict) or "data" not in body:
            raise UpstreamError(self.service, _t("Antwort unvollständig (data fehlt): {path}", path=path))
        return body["data"]

    def _get_soft(self, path: str) -> Any:
        """Wie `_get`, aber Rechte- und Dienstfehler ergeben None (NotReachable bricht ab)."""
        try:
            return self._get(path)
        except (AuthFailed, UpstreamError):
            return None

    # Nodes -------------------------------------------------------------------------------------

    def _node_ip(self, node: str) -> str | None:
        data = self._get_soft(f"/nodes/{node}/network")
        if not isinstance(data, list):
            return None
        bridges = [i for i in data if isinstance(i, dict) and i.get("type") == "bridge" and i.get("address")]
        for iface in bridges:
            if iface.get("iface") == "vmbr0":
                return str(iface["address"])
        return str(bridges[0]["address"]) if bridges else None

    def nodes(self) -> list[NodeInfo]:
        """Alle Nodes des Hosts bzw. Clusters mit Status und Bridge-IP."""
        data = self._get("/nodes")
        result = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("node"):
                continue
            node = str(item["node"])
            status = str(item.get("status") or "unknown")
            ip = self._node_ip(node) if status == "online" else None
            result.append(NodeInfo(host=self.host.name, node=node, status=status, ip=ip))
        return sorted(result, key=lambda n: n.node)

    # Gäste -------------------------------------------------------------------------------------

    def _agent_ips(self, node: str, vmid: int) -> tuple[tuple[str, ...], str]:
        path = f"{API}/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"
        try:
            response = request_raw(self._client, "GET", path, service=self.service, ok=(200, 403, 500))
        except (AuthFailed, UpstreamError):
            return (), _t(NOTE_UNKNOWN)
        if response.status_code == 403:
            return (), _t(NOTE_MONITOR) if "VM.Monitor" in _reason(response) else _t(NOTE_AUDIT)
        if response.status_code == 500:
            text = _reason(response).lower()
            return (), _t(NOTE_AGENT) if any(m in text for m in _AGENT_DOWN) else _t(NOTE_UNKNOWN)
        try:
            body = parse_json(response, service=self.service)
            interfaces = body["data"]["result"]
        except (UpstreamError, KeyError, TypeError):
            return (), _t(NOTE_UNKNOWN)
        ips = []
        for iface in interfaces if isinstance(interfaces, list) else []:
            for addr in (iface.get("ip-addresses") or []) if isinstance(iface, dict) else []:
                if isinstance(addr, dict) and addr.get("ip-address-type") == "ipv4":
                    ip = _usable_ipv4(addr.get("ip-address", ""))
                    if ip:
                        ips.append(ip)
        return tuple(ips), ("" if ips else _t(NOTE_UNKNOWN))

    def _lxc_live_ips(self, node: str, vmid: int) -> list[str]:
        data = self._get_soft(f"/nodes/{node}/lxc/{vmid}/interfaces")
        ips = []
        for iface in data if isinstance(data, list) else []:
            if isinstance(iface, dict) and iface.get("inet"):
                ip = _usable_ipv4(iface["inet"])
                if ip:
                    ips.append(ip)
        return ips

    @staticmethod
    def _lxc_config_ips(config: Mapping | None) -> tuple[list[str], bool]:
        """(statische IPs aus net0..net9, ob mindestens ein Netz DHCP nutzt)."""
        ips, dhcp = [], False
        for key in _NET_KEYS:
            value = (config or {}).get(key)
            if not value:
                continue
            ip = _split_options(value).get("ip", "")
            if ip.lower() == "dhcp":
                dhcp = True
                continue
            usable = _usable_ipv4(ip) if ip else None
            if usable:
                ips.append(usable)
        return ips, dhcp

    def _config(self, node: str, kind: str, vmid: int, cache: dict) -> Mapping | None:
        key = (kind, vmid)
        if key not in cache:
            data = self._get_soft(f"/nodes/{node}/{kind}/{vmid}/config")
            cache[key] = data if isinstance(data, dict) else None
        return cache[key]

    def _guest_ips(self, node: str, kind: str, vmid: int, running: bool,
                   cache: dict) -> tuple[tuple[str, ...], str]:
        if kind == "qemu":
            if not running:
                return (), _t(NOTE_STOPPED)
            return self._agent_ips(node, vmid)
        if running:
            live = self._lxc_live_ips(node, vmid)
            if live:
                return tuple(live), ""
        static, dhcp = self._lxc_config_ips(self._config(node, kind, vmid, cache))
        if static:
            return tuple(static), ""
        if not running:
            return (), _t(NOTE_STOPPED)
        return (), _t(NOTE_DHCP) if dhcp else _t(NOTE_UNKNOWN)

    def _passthrough(self, node: str, kind: str, vmid: int, cache: dict) -> tuple[str, ...]:
        config = self._config(node, kind, vmid, cache) or {}
        keys = _PASS_QEMU if kind == "qemu" else _PASS_LXC
        return tuple(f"{key}: {config[key]}" for key in keys if config.get(key))

    def guests(self, *, with_ips: bool = True, with_passthrough: bool = True) -> list[Guest]:
        """VMs und LXCs des Hosts, sortiert nach VMID (höchstens 200, sonst ValueError)."""
        data = self._get("/cluster/resources", params={"type": "vm"})
        items = [i for i in (data if isinstance(data, list) else [])
                 if isinstance(i, dict) and i.get("type") in KINDS and i.get("vmid") is not None
                 and not i.get("template")]
        if len(items) > MAX_GUESTS:
            raise ValueError(_t("Proxmox {name}: {count} Gäste, höchstens {max_guests} werden gelesen", name=self.host.name, count=len(items), max_guests=MAX_GUESTS))
        result = []
        for item in sorted(items, key=lambda i: int(i["vmid"])):
            vmid = int(item["vmid"])
            kind = str(item["type"])
            node = str(item.get("node") or "")
            status = str(item.get("status") or "unknown")
            cache: dict = {}
            ips: tuple[str, ...] = ()
            note = ""
            if with_ips:
                ips, note = self._guest_ips(node, kind, vmid, status == "running", cache)
                ips = _sort_ips(ips, self.networks)
            passthrough = self._passthrough(node, kind, vmid, cache) if with_passthrough else ()
            tags = tuple(t for t in re.split(r"[;, ]+", str(item.get("tags") or "")) if t)
            result.append(Guest(host=self.host.name, node=node, vmid=vmid, kind=kind,
                                name=str(item.get("name") or f"{kind}-{vmid}"), status=status,
                                tags=tags, ips=ips, ip_note=note, passthrough=passthrough))
        return result


# Filter und Zeilen -----------------------------------------------------------------------------

def parse_ids(ids: str) -> set[int]:
    """ID-Liste wie "100-110,115" als Menge; ungültig: ValueError."""
    result: set[int] = set()
    for part in str(ids).split(","):
        if not part.strip():
            continue
        match = _IDS_RE.match(part)
        if not match:
            raise ValueError(_t("Ungültige ID-Liste '{ids}' (Form 100-110,115)", ids=ids))
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end < start or end - start > 100000:
            raise ValueError(_t("Ungültiger ID-Bereich '{strip}'", strip=part.strip()))
        result.update(range(start, end + 1))
    if not result:
        raise ValueError(_t("Ungültige ID-Liste '{ids}' (Form 100-110,115)", ids=ids))
    return result


def filter_guests(guests: Sequence[Guest], *, status: str | None = None, kind: str | None = None,
                  ids: str | None = None, name: str | None = None) -> list[Guest]:
    """Gäste filtern nach Status, Art (qemu|lxc), ID-Liste und Namens-Teilstring."""
    if kind is not None and kind not in KINDS:
        raise ValueError(_t("Unbekannte Art '{kind}' (erlaubt: qemu, lxc)", kind=kind))
    wanted = parse_ids(ids) if ids else None
    needle = name.casefold() if name else None
    result = []
    for guest in guests:
        if status and guest.status != status:
            continue
        if kind and guest.kind != kind:
            continue
        if wanted is not None and guest.vmid not in wanted:
            continue
        if needle and needle not in guest.name.casefold():
            continue
        result.append(guest)
    return result


def short_ip(ip: str | None, networks: Sequence[str]) -> str:
    """Kurz-IP ".39" für Adressen in einem der /24-Heimnetze, sonst die volle Adresse."""
    if not ip:
        return ""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return ip
    for net in _networks(networks):
        if net.prefixlen == 24 and addr in net:
            return "." + ip.rsplit(".", 1)[1]
    return ip


def guest_rows(guests: Sequence[Guest], *, networks: Sequence[str],
               links: Mapping[int, str] | None = None) -> tuple[list[str], list[list[str]]]:
    """Tabelle für die Vorlagen `vm-lxc` bzw. `vm-lxc-qr` (Kopf `ROW_HEADERS`)."""
    links = links or {}
    rows = []
    for g in guests:
        ip = g.ips[0] if g.ips else ""
        rows.append(["VM" if g.kind == "qemu" else "LXC", str(g.vmid), g.name, short_ip(ip, networks),
                     ip, g.node, g.host, links.get(g.vmid, "")])
    return list(ROW_HEADERS), rows


def guest_link_id(guest: Guest) -> str:
    """Kurz-ID eines Gastes, z. B. "PMX10-111"."""
    host = re.sub(r"[^0-9A-Z-]", "-", guest.host.upper())
    return f"{host}-{guest.vmid}"


def console_url(host: PveHost, guest: Guest) -> str:
    """Adresse des Gastes in der Proxmox-Oberfläche."""
    return f"{host.url}/#v1:0:={guest.kind}%2F{guest.vmid}"


def guest_links(data: dict, host: PveHost, guests: Sequence[Guest], *, keyring_module=None,
                environ=None, transport=None) -> tuple[dict[int, str], list[str]]:
    """QR-Inhalte je VMID: Kurz-Link (Dienst eingerichtet) oder Konsolen-URL plus Warnung."""
    if not shortlink.configured(data):
        return {g.vmid: console_url(host, g) for g in guests}, [_t(SHORTLINK_MISSING)]
    links: dict[int, str] = {}
    if not guests:
        return links, []
    with shortlink.ShortlinkClient.from_settings(data, keyring_module=keyring_module, environ=environ,
                                                 transport=transport) as client:
        for g in guests:
            links[g.vmid] = shortlink.link_for(data, guest_link_id(g), console_url(host, g),
                                               note=f"{g.name} ({g.kind} {g.vmid})", client=client)
    return links, []


def guest_json(guest: Guest, networks: Sequence[str]) -> dict:
    """Gast als JSON (Tupel als Listen) plus `ip_kurz`."""
    return {"host": guest.host, "node": guest.node, "vmid": guest.vmid, "kind": guest.kind,
            "name": guest.name, "status": guest.status, "tags": list(guest.tags), "ips": list(guest.ips),
            "ip_note": guest.ip_note, "passthrough": list(guest.passthrough),
            "ip_kurz": short_ip(guest.ips[0] if guest.ips else None, networks)}


def node_json(node: NodeInfo) -> dict:
    return {"host": node.host, "node": node.node, "status": node.status, "ip": node.ip}
