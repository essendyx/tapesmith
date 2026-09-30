"""Demo-Antworten externer Dienste für das Screenshot-Werkzeug (`tools/demo_services.py`)."""

from __future__ import annotations

import ipaddress
import json
import re

import tools.demo_services as demo_services
import tools.screenshots as screenshots


def test_demo_response_liefert_listen_fuer_alle_modulseiten():
    assert len(demo_services.demo_response("POST", "/api/v1/homelab/proxmox/guests")["guests"]) >= 5
    assert len(demo_services.demo_response("GET", "/api/v1/homelab/ha/batteries")["devices"]) >= 5
    assert len(demo_services.demo_response("GET", "/api/v1/homelab/assets")["assets"]) >= 5
    assert len(demo_services.demo_response("GET", "/api/v1/homelab/ka")["items"]) >= 5
    assert len(demo_services.demo_response("GET", "/api/v1/homelab/kabel/register")["entries"]) >= 5
    assert len(demo_services.demo_response("POST", "/api/v1/ssh/scan")["disks"]) >= 4
    assert demo_services.demo_response("POST", "/api/v1/homelab/zfs/scan")["problems"]
    check = demo_services.demo_response("GET", "/api/v1/homelab/check")
    assert all(service["configured"] for service in check["services"])


def test_demo_response_filtert_status_und_laesst_andere_anfragen_durch():
    active = demo_services.demo_response("GET", "/api/v1/homelab/assets", "status=aktiv")
    assert active["assets"] and all(a["status"] == "aktiv" for a in active["assets"])
    reserved = demo_services.demo_response("GET", "/api/v1/homelab/ka", "status=reserviert")
    assert [i["status"] for i in reserved["items"]] == ["reserviert"]
    # Methode, Unterpfade und echte Demo-Endpunkte gehen an den Demo-Dienst
    assert demo_services.demo_response("POST", "/api/v1/homelab/assets") is None
    assert demo_services.demo_response("GET", "/api/v1/homelab/assets/HL-0001/label") is None
    assert demo_services.demo_response("GET", "/api/v1/history") is None


def test_intercept_pattern_faengt_nur_externe_dienste_ab():
    base = "http://127.0.0.1:8712"
    assert demo_services.INTERCEPT_PATTERN.search(f"{base}/api/v1/homelab/assets?status=aktiv")
    assert demo_services.INTERCEPT_PATTERN.search(f"{base}/api/v1/ssh/scan")
    assert not demo_services.INTERCEPT_PATTERN.search(f"{base}/api/v1/events")
    assert not demo_services.INTERCEPT_PATTERN.search(f"{base}/api/v1/history?limit=50")
    assert not demo_services.INTERCEPT_PATTERN.search(f"{base}/api/v1/homelab/assets/HL-0001/label")


def test_demo_daten_nutzen_nur_dokumentationsnetze_und_example_com():
    text = json.dumps([body for _m, _p, body in demo_services.ROUTES], ensure_ascii=False)
    for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        assert ipaddress.ip_address(ip) in ipaddress.ip_network("192.0.2.0/24"), ip
    for host in re.findall(r"https?://([^/:\"]+)", text):
        assert host.endswith("example.com") or host.startswith("192.0.2."), host


def test_interaktionen_der_modulseiten_sind_registriert():
    extra = {route.key: route for route in screenshots.EXTRA_ROUTES}
    main = {route.key: route for route in screenshots.MAIN_ROUTES}
    assert main["datentraeger"].interact == "ssh_scan"
    assert extra["datentraeger-plattentausch"].interact == "zfs_scan"
    assert extra["homelab-vault"].interact == "vault_note"
    assert extra["homelab-kabel"].path == "/homelab/kabel?tab=register"
    for key in ("ssh_scan", "zfs_scan", "proxmox_load", "vault_note"):
        assert key in screenshots.INTERACTIONS
