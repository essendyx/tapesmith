"""Findet den ausgehenden Bluetooth-SPP-COM-Port eines Geräts über dessen MAC (Windows-Registry)."""

import re
from dataclasses import dataclass

from tapesmith.config import normalize_mac

SPP_PREFIX = "{00001101-0000-1000-8000-00805f9b34fb}"
_INSTANCE = re.compile(r"&([0-9A-Fa-f]{12})_[0-9A-Fa-f]+$")


@dataclass(frozen=True)
class BtPort:
    port: str
    mac: str
    outgoing: bool


def parse_instance(instance_id: str, port: str) -> BtPort | None:
    match = _INSTANCE.search(instance_id)
    if not match:
        return None
    mac = match.group(1).upper()
    return BtPort(port, mac, mac != "000000000000")


def _read_registry() -> list[tuple[str, str]]:
    """Nur lesend. Ohne Bluetooth (etwa auf Servern und virtuellen Maschinen) fehlt der Schlüssel
    BTHENUM ganz: dann gibt es schlicht keine Ports."""
    import winreg

    rows = []
    root = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
    try:
        bthenum = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
    except FileNotFoundError:
        return rows
    with bthenum:
        for i in range(winreg.QueryInfoKey(bthenum)[0]):
            service = winreg.EnumKey(bthenum, i)
            if not service.lower().startswith(SPP_PREFIX):
                continue
            with winreg.OpenKey(bthenum, service) as svc:
                for j in range(winreg.QueryInfoKey(svc)[0]):
                    instance = winreg.EnumKey(svc, j)
                    try:
                        with winreg.OpenKey(svc, instance + r"\Device Parameters") as params:
                            port, _ = winreg.QueryValueEx(params, "PortName")
                    except OSError:
                        continue
                    rows.append((instance, port))
    return rows


def list_bt_ports(reader=None) -> list[BtPort]:
    rows = (reader or _read_registry)()
    return [p for p in (parse_instance(i, port) for i, port in rows) if p is not None]


def find_outgoing_port(mac: str | None, reader=None) -> str | None:
    """COM-Port des Druckers. Ohne MAC (Standard, solange `p12 setup` keine gespeichert hat):
    der einzige ausgehende Bluetooth-COM-Port, bei mehreren keiner (dann MAC setzen)."""
    if mac is None:
        outgoing = [p for p in list_bt_ports(reader) if p.outgoing]
        return outgoing[0].port if len(outgoing) == 1 else None
    wanted = normalize_mac(mac)
    for p in list_bt_ports(reader):
        if p.outgoing and p.mac == wanted:
            return p.port
    return None
