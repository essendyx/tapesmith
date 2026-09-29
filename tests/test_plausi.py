"""Plausibilitätsprüfung vor dem Druck."""

import pytest

from obsidian_fakes import MCP_URL, FakeMcp
from tapesmith.integrations import scancache
from tapesmith.integrations.assets import AssetStore
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.integrations.plausi import Context, check, default_resolver, worst
from tapesmith.integrations.tia606 import KabelEntry, KabelRegister
from tapesmith.sshscan import DiskRow


def _disk(host: str, device: str, serial: str, **kw) -> DiskRow:
    values = {"host": host, "device": device, "model": "Model X", "serial": serial, "size": "1T",
             "tran": "sata", "wwn": "", "by_id": None, "pool": None, "vdev": None}
    values.update(kw)
    return DiskRow(**values)


def _ctx(**kw) -> Context:
    base = {"scans": (), "networks": ["192.0.2.0/24"]}
    base.update(kw)
    return Context(**base)


def test_sn_on_other_host_is_conflict():
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "ABC123DEF456")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123DEF456"}, ctx)
    conflicts = [f for f in findings if f.level == "konflikt"]
    assert len(conflicts) == 1
    assert conflicts[0].code == "sn_anderer_host"
    assert "pmx20" in conflicts[0].message
    assert "sdb" in conflicts[0].message


def test_sn_on_same_host_no_conflict():
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "ABC123DEF456")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123DEF456"}, ctx)
    assert not any(f.level == "konflikt" for f in findings)


def test_shortened_serial_is_ambiguous():
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "AAA111DEF456"), _disk("pmx10", "sdb", "BBB222DEF456")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", {"sn": "AAA111DEF456"}, ctx)
    warn = [f for f in findings if f.code == "sn_kuerzung_mehrdeutig"]
    assert len(warn) == 1
    assert "sdb" in warn[0].message


def test_no_scans_gives_info_quelle_fehlt():
    findings = check("datentraeger", {"sn": "ABC123"}, _ctx())
    assert [f.code for f in findings] == ["quelle_fehlt"]
    assert findings[0].level == "info"


def test_unknown_sn_with_scans_gives_info():
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "AAA111DEF456")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", {"sn": "ZZZ999"}, ctx)
    assert [f.code for f in findings] == ["sn_unbekannt"]
    assert findings[0].level == "info"
    assert "pmx10" in findings[0].message


def test_ip_outside_network_warns():
    findings = check("host-ip", {"ip": "10.1.2.3"}, _ctx())
    assert [f.code for f in findings] == ["ip_ausserhalb"]
    assert findings[0].level == "warnung"


def test_ip_kurz_expanded_within_network():
    findings = check("host-ip", {"ip_kurz": ".39"}, _ctx())
    assert findings == []


def test_ip_invalid():
    findings = check("host-ip", {"ip": "999.1.1.1"}, _ctx())
    assert [f.code for f in findings] == ["ip_ungueltig"]


def test_dns_mismatch_warns():
    findings = check("host-ip", {"host": "pmx10", "ip": "192.0.2.61"},
                     _ctx(resolver=lambda name: ["192.0.2.60"]))
    assert [f.code for f in findings] == ["dns_abweichung"]
    assert "192.0.2.60" in findings[0].message
    assert "192.0.2.61" in findings[0].message


def test_dns_empty_resolution_is_info():
    findings = check("host-ip", {"host": "unbekannt-host"}, _ctx(resolver=lambda name: []))
    assert [f.code for f in findings] == ["dns_unbekannt"]
    assert findings[0].level == "info"


def test_dns_disabled_without_resolver_no_findings():
    findings = check("host-ip", {"host": "pmx10", "ip": "192.0.2.61"}, _ctx(resolver=None))
    assert findings == []


def test_default_resolver_uses_socket(monkeypatch):
    calls = []

    def fake_getaddrinfo(host, port, family):
        calls.append(host)
        return [(family, None, None, "", ("192.0.2.60", 0))]

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    assert default_resolver("pmx10") == ["192.0.2.60"]
    assert calls == ["pmx10"]


def test_default_resolver_returns_empty_on_error(monkeypatch):
    def raises(host, port, family):
        raise OSError("nicht auflösbar")

    monkeypatch.setattr("socket.getaddrinfo", raises)
    assert default_resolver("nirgendwo") == []


def test_asset_verworfen_is_conflict(tmp_path):
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        store.add_existing("HL-0001", bezeichnung="Test")
        store.update("HL-0001", status="verworfen")
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        findings = check("asset-kurz", {"nummer": "HL-0001"}, _ctx(assets=store))
    assert [f.code for f in findings] == ["asset_verworfen"]
    assert findings[0].level == "konflikt"


def test_asset_with_other_serial_warns(tmp_path):
    # ohne SSH-Scans meldet die SN-Prüfung zusätzlich "quelle_fehlt" (info); die Reihenfolge ist
    # konflikt, warnung, info.
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        store.add_existing("HL-0001", seriennummer="OTHERSN")
        findings = check("asset-kurz", {"nummer": "HL-0001", "sn": "ABC123"}, _ctx(assets=store))
    assert [f.code for f in findings] == ["asset_andere_sn", "quelle_fehlt"]
    assert findings[0].level == "warnung"
    assert findings[1].level == "info"


def test_serial_assigned_to_other_asset_warns(tmp_path):
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        store.add_existing("HL-0007", seriennummer="ABC123")
        findings = check("datentraeger", {"sn": "ABC123"}, _ctx(assets=store))
    assert [f.code for f in findings] == ["sn_asset", "quelle_fehlt"]
    assert "HL-0007" in findings[0].message


def test_by_id_serial_assigned_to_other_asset_warns(tmp_path):
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        store.add_existing("HL-0007", seriennummer="ABC123DEF456")
        findings = check("datentraeger", {"sn": "ata-Samsung_SSD_860_ABC123DEF456"}, _ctx(assets=store))
    codes = [f.code for f in findings]
    assert "sn_asset" in codes
    assert "HL-0007" in findings[codes.index("sn_asset")].message

def test_unknown_asset_is_info(tmp_path):
    with AssetStore(tmp_path / "assets.sqlite3") as store:
        findings = check("asset-kurz", {"nummer": "HL-9999"}, _ctx(assets=store))
    assert [f.code for f in findings] == ["asset_unbekannt"]
    assert findings[0].level == "info"


def test_kabel_registered_is_info(tmp_path):
    reg = KabelRegister(tmp_path / "kabel.json")
    reg.add([KabelEntry(id="K-001", quelle="", ziel="", kabeltyp="", quelle_import="manuell",
                        created="2026-09-28T10:00:00")])
    findings = check("kabelfahne", {"kabel_id": "K-001"}, _ctx(kabel=reg))
    assert [f.code for f in findings] == ["kabel_vergeben"]
    assert findings[0].level == "info"


def test_kabel_unregistered_no_finding(tmp_path):
    reg = KabelRegister(tmp_path / "kabel.json")
    findings = check("kabelfahne", {"kabel_id": "K-999"}, _ctx(kabel=reg))
    assert findings == []


def test_vault_hit_on_other_host_warns():
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "ABC123")])
    fake = FakeMcp({"vault_search": [{"path": "Hosts/pmx20.md", "line": 3, "text": "SN ABC123"}]})
    with VaultClient(MCP_URL, transport=fake.transport()) as vault:
        findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123"}, _ctx(vault=vault, scans=scancache.all_scans()))
    assert [f.code for f in findings] == ["sn_im_vault_anderer_host"]
    assert findings[0].level == "warnung"


def test_vault_hit_on_same_host_no_finding():
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "ABC123")])
    fake = FakeMcp({"vault_search": [{"path": "Hosts/pmx10.md", "line": 3, "text": "SN ABC123"}]})
    with VaultClient(MCP_URL, transport=fake.transport()) as vault:
        findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123"}, _ctx(vault=vault, scans=scancache.all_scans()))
    assert findings == []


def test_vault_unreachable_is_info():
    import httpx

    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "ABC123")])

    def handler(request):
        raise httpx.ConnectError("nein", request=request)

    with VaultClient(MCP_URL, transport=httpx.MockTransport(handler)) as vault:
        findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123"},
                         _ctx(vault=vault, scans=scancache.all_scans()))
    assert [f.code for f in findings] == ["quelle_fehlt"]
    assert findings[0].level == "info"



def test_vault_unreachable_is_info_even_without_host():
    import httpx

    def handler(request):
        raise httpx.ConnectError("nein", request=request)

    with VaultClient(MCP_URL, transport=httpx.MockTransport(handler)) as vault:
        findings = check("garantie", {"sn": "ABC123"}, _ctx(vault=vault))
    assert any(f.code == "quelle_fehlt" and "Vault" in f.message for f in findings)


def test_vault_searched_without_host_but_no_host_warning():
    fake = FakeMcp({"vault_search": [{"path": "Hosts/pmx20.md", "line": 3, "text": "SN ABC123"}]})
    with VaultClient(MCP_URL, transport=fake.transport()) as vault:
        findings = check("datentraeger", {"host": "", "sn": "ABC123"}, _ctx(vault=vault))
    assert "sn_im_vault_anderer_host" not in [f.code for f in findings]
    assert any(name == "vault_search" for name, _ in fake.tool_calls), "Vault muss auch ohne Host-Feld abgefragt werden"

def test_worst_and_sort_order():
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "ABC123DEF456")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", {"host": "pmx10", "sn": "ABC123DEF456", "ip": "10.0.0.1"}, ctx)
    assert worst(findings) == "konflikt"
    assert [f.level for f in findings] == sorted([f.level for f in findings],
                                                  key=lambda level: {"konflikt": 0, "warnung": 1, "info": 2}[level])


def test_worst_none_without_findings():
    assert worst([]) is None


@pytest.mark.parametrize("case", [
    ({"host": "pmx10", "sn": "X"}, {}),
])
def test_no_message_contains_a_dash(case):
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "X")])
    ctx = _ctx(scans=scancache.all_scans())
    findings = check("datentraeger", case[0], ctx)
    for f in findings:
        assert "\u2013" not in f.message
        assert "\u2014" not in f.message
