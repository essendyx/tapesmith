"""Tests für `tapesmith.netinfo`."""

from tapesmith import netinfo


def _fake_resolver(addresses):
    def resolver(host, port, family):
        return [(family, None, None, "", (a, 0)) for a in addresses]
    return resolver


def test_local_ipv4_addresses_filtert_loopback_und_sortiert():
    resolver = _fake_resolver(["192.0.2.50", "127.0.0.1", "172.20.0.1"])
    assert netinfo.local_ipv4_addresses(resolver=resolver) == ["172.20.0.1", "192.0.2.50"]


def test_local_ipv4_addresses_fehler_ergibt_leere_liste():
    def resolver(host, port, family):
        raise OSError("kein Netz")
    assert netinfo.local_ipv4_addresses(resolver=resolver) == []


def test_lan_addresses_filtert_auf_erlaubte_netze():
    cfg = {"lan": {"bind": "0.0.0.0", "allowed_networks": ["192.0.2.0/24"]}}
    addresses = ["192.0.2.50", "10.0.0.5", "172.20.0.1"]
    assert netinfo.lan_addresses(cfg, addresses=addresses) == ["192.0.2.50"]


def test_lan_addresses_mit_festem_bind():
    cfg = {"lan": {"bind": "192.0.2.9", "allowed_networks": ["192.0.2.0/24"]}}
    assert netinfo.lan_addresses(cfg, addresses=["192.0.2.50"]) == ["192.0.2.9"]


def test_lan_base_urls_public_url_zuerst_dann_ip():
    cfg = {
        "lan": {"bind": "0.0.0.0", "allowed_networks": ["192.0.2.0/24"], "public_url": "http://p12.lan/"},
        "web": {"port": 8712},
    }
    urls = netinfo.lan_base_urls(cfg, addresses=["192.0.2.50"])
    assert urls == ["http://p12.lan", "http://192.0.2.50:8712"]


def test_lan_base_urls_ohne_public_url():
    cfg = {"lan": {"bind": "0.0.0.0", "allowed_networks": ["192.0.2.0/24"]}, "web": {"port": 8712}}
    assert netinfo.lan_base_urls(cfg, addresses=["192.0.2.50"]) == ["http://192.0.2.50:8712"]


def test_in_networks():
    assert netinfo.in_networks("192.0.2.50", ["192.0.2.0/24"]) is True
    assert netinfo.in_networks("10.0.0.5", ["192.0.2.0/24"]) is False
    assert netinfo.in_networks("abc", ["192.0.2.0/24"]) is False


def test_host_name():
    assert isinstance(netinfo.host_name(), str)
