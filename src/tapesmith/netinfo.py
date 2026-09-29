"""Netzinfo: lokale IPv4-Adressen, Netzprüfung, Basis-URLs fürs LAN."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Sequence

from tapesmith import config


def local_ipv4_addresses(resolver=socket.getaddrinfo, hostname: str | None = None) -> list[str]:
    """Lokale IPv4-Adressen (ohne 127.x), sortiert und eindeutig. Fehler ergibt `[]`."""
    name = hostname if hostname is not None else socket.gethostname()
    try:
        infos = resolver(name, None, socket.AF_INET)
    except OSError:
        return []
    addresses = set()
    for info in infos:
        ip = info[4][0]
        if not ip.startswith("127."):
            addresses.add(ip)
    return sorted(addresses)


def host_name() -> str:
    return socket.gethostname()


def in_networks(ip: str, networks: Sequence[str]) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    for net in networks:
        try:
            network = ipaddress.IPv4Network(net, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


def lan_addresses(cfg: dict, addresses: Sequence[str] | None = None) -> list[str]:
    """`lan.bind` != `0.0.0.0`: nur diese Adresse; sonst lokale Adressen aus `lan.allowed_networks`."""
    bind = config.setting(cfg, "lan.bind")
    if bind and bind != "0.0.0.0":
        return [bind]
    candidates = list(addresses) if addresses is not None else local_ipv4_addresses()
    networks = config.setting(cfg, "lan.allowed_networks")
    return [ip for ip in candidates if in_networks(ip, networks)]


def lan_base_urls(cfg: dict, addresses: Sequence[str] | None = None) -> list[str]:
    """`lan.public_url` (ohne Schluss-/) zuerst, dann `http://<ip>:<web.port>` je LAN-Adresse."""
    urls: list[str] = []
    public_url = config.setting(cfg, "lan.public_url")
    if public_url:
        urls.append(public_url.rstrip("/"))
    port = config.setting(cfg, "web.port")
    for ip in lan_addresses(cfg, addresses):
        urls.append(f"http://{ip}:{port}")
    return urls
