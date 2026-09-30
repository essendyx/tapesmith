"""Demo-Antworten externer Dienste für Screenshots und Rauchtest.

Die Modulseiten (Proxmox, Home Assistant, Paperless, Obsidian-Vault, Assets, Kleinanzeigen, Kabel)
und die SSH-Reiter der Seite Datenträger zeigen ihre Listen erst mit einem erreichbaren Dienst. Das
Screenshot-Werkzeug beantwortet diese Anfragen im Browser (Playwright `page.route`) mit den frei
erfundenen Daten hier, damit die Aufnahmen realistisch volle Listen zeigen. Es wird nie ein echter
Dienst angefragt; alle Adressen liegen in den Dokumentationsnetzen (192.0.2.0/24, example.com).

`demo_response(method, path, query)` ist rein (kein Browser, kein Netz) und liefert das JSON einer
Antwort oder `None` (dann geht die Anfrage unverändert an den Demo-Dienst).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs

HOST = "pmx10"

HOMELAB_CHECK: dict[str, Any] = {"services": [
    {"id": "proxmox", "label": "Proxmox", "configured": True, "token_set": True, "detail": "1 Host"},
    {"id": "paperless", "label": "Paperless", "configured": True, "token_set": True, "detail": "Token vorhanden"},
    {"id": "homeassistant", "label": "Home Assistant", "configured": True, "token_set": True, "detail": "Token vorhanden"},
    {"id": "obsidian", "label": "Obsidian", "configured": True, "token_set": None, "detail": "Vault-Ordner"},
    {"id": "shortlink", "label": "Kurz-Link-Dienst", "configured": True, "token_set": True, "detail": "l.example.com"},
]}

PVE_HOSTS: dict[str, Any] = {"hosts": [
    {"name": HOST, "url": "https://192.0.2.60:8006", "verify_tls": True, "token_set": True,
     "token_describe": "Token in der Windows-Anmeldeinformationsverwaltung"},
]}


def _guest(vmid: int, kind: str, name: str, status: str, ips: list[str], passthrough: list[str] | None = None,
           note: str = "") -> dict[str, Any]:
    return {"host": HOST, "node": HOST, "vmid": vmid, "kind": kind, "name": name, "status": status, "tags": [],
            "ips": ips, "ip_note": note, "passthrough": passthrough or [],
            "ip_kurz": ips[0].rsplit(".", 1)[-1] if ips else ""}


PVE_GUESTS: dict[str, Any] = {
    "host": HOST,
    "nodes": [{"host": HOST, "node": HOST, "status": "online", "ip": "192.0.2.60"}],
    "guests": [
        _guest(100, "qemu", "opnsense", "running", ["192.0.2.1"], ["hostpci0: 0000:03:00.0 (NIC)"]),
        _guest(101, "lxc", "pihole", "running", ["192.0.2.53"]),
        _guest(102, "lxc", "frigate", "running", ["192.0.2.70"], ["dev0: /dev/dri/renderD128"]),
        _guest(103, "qemu", "homeassistant", "running", ["192.0.2.80"], ["usb0: host=10c4:ea60 (Zigbee)"]),
        _guest(110, "lxc", "paperless", "running", ["192.0.2.90"]),
        _guest(111, "lxc", "webapp1", "stopped", [], note="IP unbekannt: Gast gestoppt"),
        _guest(120, "qemu", "win11-lab", "stopped", [], note="IP unbekannt: kein Gast-Agent"),
    ],
    "warnings": [],
}


def _battery(entity: str, device: str, area: str, level: int | None, battery: str, low: bool = False) -> dict[str, Any]:
    return {"entity_id": entity, "device": device, "area": area, "level": level, "low": low,
            "battery_type": battery, "type_source": "Gerätedatenbank" if battery else "",
            "manufacturer": "", "model": ""}


BATTERIES: dict[str, Any] = {
    "devices": [
        _battery("sensor.rauchmelder_flur_battery", "Rauchmelder Flur", "Flur", 8, "CR123A", low=True),
        _battery("sensor.fensterkontakt_bad_battery", "Fensterkontakt Bad", "Bad", 17, "CR2032"),
        _battery("sensor.thermostat_wohnzimmer_battery", "Thermostat Wohnzimmer", "Wohnzimmer", 46, "2× AA"),
        _battery("sensor.bewegungsmelder_keller_battery", "Bewegungsmelder Keller", "Keller", 71, "CR2450"),
        _battery("sensor.tuersensor_haustuer_battery", "Türsensor Haustür", "Flur", 93, ""),
        _battery("sensor.wetterstation_battery", "Wetterstation Garten", "Garten", None, "2× AAA"),
    ],
    "todo_entity": "todo.wartung",
    "warnings": [],
}

ASN_NEXT: dict[str, Any] = {"paperless_next": 1284, "local_next": "ASN01284", "next": "ASN01284", "prefix": "ASN",
                            "width": 5, "hint": ""}


def _doc(doc_id: int, title: str, created: str, correspondent: str, asn: int) -> dict[str, Any]:
    return {"id": doc_id, "title": title, "created": created, "correspondent": correspondent, "asn": asn,
            "custom": {}, "url": f"https://paperless.example.com/documents/{doc_id}/details"}


PAPERLESS_DOCUMENTS: dict[str, Any] = {"documents": [
    _doc(412, "Rechnung Kaffeemaschine", "2026-01-31", "Elektromarkt", 1201),
    _doc(398, "Rechnung NAS DS923+", "2025-11-14", "Hardwareversand", 1188),
    _doc(377, "Rechnung Akkuschrauber", "2025-08-02", "Baumarkt", 1164),
    _doc(351, "Rechnung Router", "2025-05-19", "Netzwerkladen", 1139),
]}

VAULT_NOTES: dict[str, Any] = {
    "folders": ["Hosts", "Dienste", "Netzwerk"],
    "notes": ["Hosts/pmx10.md", "Hosts/nas.md", "Hosts/opnsense.md", "Dienste/Paperless.md", "Dienste/Pi-hole.md",
              "Netzwerk/Patchpanel.md"],
}
VAULT_NOTE: dict[str, Any] = {
    "path": "Hosts/pmx10.md",
    "title": "pmx10",
    "values": {"host": "pmx10", "ip": "192.0.2.60", "rolle": "Proxmox VE", "standort": "Keller Rack 1",
               "sn": "112233274913"},
    "tables": [{"heading": "Platten", "headers": ["slot", "modell", "sn"],
                "rows": [["SSD-1", "Samsung 870 EVO", "274913"], ["SSD-2", "Samsung 870 EVO", "274916"],
                         ["SSD-3", "Crucial MX500", "274919"]]}],
}


def _asset(num: int, name: str, category: str, place: str, sn: str, host: str, status: str = "aktiv") -> dict[str, Any]:
    ident = f"HL-{num:04d}"
    return {"id": ident, "bezeichnung": name, "kategorie": category, "standort": place, "seriennummer": sn,
            "host": host, "ziel": f"https://wiki.example.com/assets/{ident}", "paperless_doc": None,
            "status": status, "notiz": "", "created": "2026-08-01T10:00:00", "updated": "2026-08-01T10:00:00"}


ASSETS: dict[str, Any] = {
    "assets": [
        _asset(1, "Proxmox-Server", "Server", "Keller Rack 1", "112233274913", "pmx10"),
        _asset(2, "NAS DS923+", "Speicher", "Keller Rack 1", "2280QVR123456", "nas"),
        _asset(3, "Switch 24 Port", "Netzwerk", "Keller Rack 1", "S24-889120", ""),
        _asset(4, "USV 1500 VA", "Strom", "Keller Rack 1", "3B2210X04512", ""),
        _asset(5, "Access Point OG", "Netzwerk", "Flur OG", "AP-771203", ""),
        _asset(6, "Patchkabel Cat6 3m", "Kabel", "Kiste Kabel", "", "", status="ausgemustert"),
    ],
    "range": {"prefix": "HL-", "width": 4, "next": "HL-0007", "check_digit": False},
    "shortlink": True,
}


def _artikel(num: int, title: str, price: str, place: str, status: str = "verfügbar", name: str = "",
             date: str = "") -> dict[str, Any]:
    ident = f"KA-{num:03d}"
    return {"id": ident, "titel": title, "preis": price, "anzeige": f"https://kleinanzeigen.example.com/{ident}",
            "status": status, "name": name, "datum": date, "ort": place, "notiz": "",
            "created": "2026-09-20T10:00:00", "updated": "2026-09-20T10:00:00"}


KLEINANZEIGEN: dict[str, Any] = {
    "items": [
        _artikel(1, "Monitorarm", "25 €", "Keller Regal 2"),
        _artikel(2, "Bürostuhl", "60 €", "Büro", status="reserviert", name="Hubert", date="04.10.2026"),
        _artikel(3, "Raspberry Pi 4 (4 GB)", "45 €", "Kiste Elektronik"),
        _artikel(4, "Stehlampe", "15 €", "Dachboden", status="verkauft", name="Anna", date="27.09.2026"),
        _artikel(5, "Gigabit-Switch 8 Port", "20 €", "Keller Regal 2"),
    ],
    "next": "KA-006",
    "shortlink": True,
}

KABEL_REGISTER: dict[str, Any] = {"entries": [
    {"id": f"K-{n:03d}", "quelle": q, "ziel": z, "kabeltyp": typ, "quelle_import": imp, "created": "2026-09-01T10:00:00"}
    for n, q, z, typ, imp in (
        (17, "SW1/P12", "pmx10/eno1", "Cat6", "netbox"),
        (18, "SW1/P13", "pmx20/eno2", "Cat6", "netbox"),
        (19, "SW1/P14", "pmx10/eno3", "Cat6", "netbox"),
        (20, "SW2/P01", "nas/eth0", "Cat6a", "schema"),
        (21, "SW2/P02", "nas/eth1", "Cat6a", "schema"),
        (22, "PP1/05", "AP-OG", "Cat7", "frei"),
    )
]}


def _disk(device: str, model: str, serial: str, size: str, pool: str | None, vdev: str | None) -> dict[str, Any]:
    return {"host": HOST, "device": device, "model": model, "serial": serial, "size": size, "tran": "sata",
            "wwn": "", "by_id": f"ata-{model.replace(' ', '_')}_{serial}", "pool": pool, "vdev": vdev}


SSH_DISKS: list[dict[str, Any]] = [
    _disk("sda", "Samsung SSD 870 EVO 1TB", "S6PNNL0T274913", "1 TB", "rpool", "mirror-0"),
    _disk("sdb", "Samsung SSD 870 EVO 1TB", "S6PNNL0T274916", "1 TB", "rpool", "mirror-0"),
    _disk("sdc", "WDC WD40EFZX-68AWUN0", "WD-WX12D80274919", "4 TB", "tank", "raidz1-0"),
    _disk("sdd", "WDC WD40EFZX-68AWUN0", "WD-WX12D80274921", "4 TB", "tank", "raidz1-0"),
    _disk("sde", "WDC WD40EFZX-68AWUN0", "WD-WX12D80274926", "4 TB", None, None),
]
SSH_SCAN: dict[str, Any] = {"host": HOST, "disks": SSH_DISKS}


def _pool_dev(name: str, state: str, note: str, by_id: str | None) -> dict[str, Any]:
    return {"pool": "tank", "vdev": "raidz1-0", "name": name, "state": state, "read": "0", "write": "0",
            "cksum": "0" if state == "ONLINE" else "12", "note": note, "was_path": None, "by_id": by_id,
            "partition": None, "device": None}


ZFS_SCAN: dict[str, Any] = {
    "host": HOST,
    "scanned_at": "2026-09-30T09:12:00",
    "previous_scanned_at": "2026-09-23T09:10:00",
    "disks": SSH_DISKS,
    "pools": [{"name": "tank", "state": "DEGRADED", "errors": "No known data errors", "devices": []}],
    "problems": [
        _pool_dev("ata-WDC_WD40EFZX-68AWUN0_WD-WX12D80274921", "FAULTED", "zu viele Prüfsummenfehler",
                  "ata-WDC_WD40EFZX-68AWUN0_WD-WX12D80274921"),
    ],
    "candidates": [{"disk": SSH_DISKS[4], "reason": "gleiche Größe, in keinem Pool"}],
}

# (Methode, Pfad als regulärer Ausdruck, Antwort). Nur Dienste außerhalb der Demo; alles andere
# beantwortet der echte Demo-Dienst.
ROUTES: tuple[tuple[str, str, Any], ...] = (
    ("GET", r"/api/v1/homelab/check", HOMELAB_CHECK),
    ("GET", r"/api/v1/homelab/proxmox/hosts", PVE_HOSTS),
    ("POST", r"/api/v1/homelab/proxmox/guests", PVE_GUESTS),
    ("GET", r"/api/v1/homelab/ha/batteries", BATTERIES),
    ("GET", r"/api/v1/homelab/paperless/asn/next", ASN_NEXT),
    ("GET", r"/api/v1/homelab/paperless/documents", PAPERLESS_DOCUMENTS),
    ("GET", r"/api/v1/homelab/vault/notes", VAULT_NOTES),
    ("GET", r"/api/v1/homelab/vault/note", VAULT_NOTE),
    ("GET", r"/api/v1/homelab/assets", ASSETS),
    ("GET", r"/api/v1/homelab/ka", KLEINANZEIGEN),
    ("GET", r"/api/v1/homelab/kabel/register", KABEL_REGISTER),
    ("POST", r"/api/v1/ssh/scan", SSH_SCAN),
    ("POST", r"/api/v1/homelab/zfs/scan", ZFS_SCAN),
)
_COMPILED = tuple((method, re.compile(pattern + r"$"), body) for method, pattern, body in ROUTES)

# Adressen, die der Browser für die Demo-Antworten abfangen muss (mit oder ohne Query).
INTERCEPT_PATTERN = re.compile(r"^https?://[^/]+(" + "|".join(p for _m, p, _b in ROUTES) + r")(\?.*)?$")


def demo_response(method: str, path: str, query: str = "") -> Any | None:
    """Demo-JSON für `method` `path` (ohne Query) oder `None` (echter Demo-Dienst antwortet)."""
    for want, pattern, body in _COMPILED:
        if want == method.upper() and pattern.match(path):
            if body is ASSETS and query:
                return _filter_assets(parse_qs(query))
            if body is KLEINANZEIGEN and query:
                return _filter_ka(parse_qs(query))
            return body
    return None


def _filter_assets(params: dict[str, list[str]]) -> dict[str, Any]:
    status = (params.get("status") or [""])[0]
    needle = (params.get("q") or params.get("query") or [""])[0].lower()
    assets = [a for a in ASSETS["assets"] if (not status or a["status"] == status)
              and (not needle or needle in " ".join(str(v) for v in a.values()).lower())]
    return {**ASSETS, "assets": assets}


def _filter_ka(params: dict[str, list[str]]) -> dict[str, Any]:
    status = (params.get("status") or [""])[0]
    return {**KLEINANZEIGEN, "items": [i for i in KLEINANZEIGEN["items"] if not status or i["status"] == status]}
