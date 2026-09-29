"""Proxmox-Import, Client, Filter, Zeilen. Nur MockTransport, nie echtes Netz."""

import warnings

import httpx
import pytest

from homelab_fakes import connect_error_transport, load_json, mock_transport, token_file
from tapesmith.integrations import proxmox
from tapesmith.integrations.errors import NotReachable, TokenMissing
from tapesmith.integrations.proxmox import (
    Guest,
    ProxmoxClient,
    PveHost,
    console_url,
    filter_guests,
    find_host,
    guest_link_id,
    guest_rows,
    hosts_from_settings,
    short_ip,
)

NETS = ["192.0.2.0/24"]
TOKEN = "tapesmith@pve!label=abc"


def _routes(**overrides) -> dict:
    base = "/api2/json/nodes/pmx10"
    routes = {
        "GET /api2/json/nodes": load_json("proxmox/nodes.json"),
        f"GET {base}/network": load_json("proxmox/network-pmx10.json"),
        "GET /api2/json/cluster/resources?type=vm": load_json("proxmox/resources.json"),
        f"GET {base}/qemu/111/agent/network-get-interfaces": load_json("proxmox/agent-111.json"),
        f"GET {base}/qemu/111/config": load_json("proxmox/qemu-config-111.json"),
        f"GET {base}/qemu/120/config": load_json("proxmox/qemu-config-120.json"),
        f"GET {base}/lxc/102/interfaces": load_json("proxmox/lxc-102-interfaces.json"),
        f"GET {base}/lxc/102/config": load_json("proxmox/lxc-102-config.json"),
        f"GET {base}/lxc/103/interfaces": load_json("proxmox/lxc-103-interfaces.json"),
        f"GET {base}/lxc/103/config": load_json("proxmox/lxc-103-config.json"),
    }
    routes.update(overrides)
    return routes


def _settings(tmp_path, *, token: str | None = TOKEN, verify_tls: bool = False) -> dict:
    ref = token_file(tmp_path, "pve", token) if token is not None else f"file:{tmp_path / 'fehlt'}"
    return {
        "proxmox": {"hosts": [{"name": "pmx10", "url": "https://192.0.2.60:8006",
                               "token_ref": ref, "verify_tls": verify_tls}], "timeout_s": 10.0},
        "plausi": {"networks": NETS, "dns_check": True},
    }


def _client(tmp_path, routes=None, calls=None, **kw) -> ProxmoxClient:
    transport = mock_transport(_routes() if routes is None else routes, calls=calls)
    return ProxmoxClient.from_settings(_settings(tmp_path, **kw), "pmx10", transport=transport)


def _by_id(guests):
    return {g.vmid: g for g in guests}


def test_hosts_from_settings_and_find_host(tmp_path):
    data = _settings(tmp_path)
    hosts = hosts_from_settings(data)
    assert hosts == [PveHost(name="pmx10", url="https://192.0.2.60:8006",
                             token_ref=data["proxmox"]["hosts"][0]["token_ref"], verify_tls=False)]
    assert find_host(data, "pmx10").name == "pmx10"
    with pytest.raises(ValueError, match="pmx10"):
        find_host(data, "pmx30")


def test_auth_header_sent(tmp_path):
    calls: list[httpx.Request] = []
    with _client(tmp_path, calls=calls) as client:
        client.nodes()
    assert calls
    assert all(c.headers["Authorization"] == f"PVEAPIToken={TOKEN}" for c in calls)
    assert all(c.method == "GET" for c in calls)


def test_nodes_with_bridge_ip(tmp_path):
    with _client(tmp_path) as client:
        nodes = client.nodes()
    assert [(n.host, n.node, n.status, n.ip) for n in nodes] == [("pmx10", "pmx10", "online", "192.0.2.60")]


def test_nodes_network_error_gives_none(tmp_path):
    routes = _routes(**{"GET /api2/json/nodes/pmx10/network": (403, {"data": None})})
    with _client(tmp_path, routes) as client:
        assert client.nodes()[0].ip is None


def test_guests_ips_and_passthrough(tmp_path):
    calls: list[httpx.Request] = []
    with _client(tmp_path, calls=calls) as client:
        guests = client.guests()
    assert [g.vmid for g in guests] == [102, 103, 111, 120]
    g = _by_id(guests)
    assert g[111].ips == ("192.0.2.39",) and g[111].ip_note == ""
    assert g[111].kind == "qemu" and g[111].tags == ("ai", "gpu") and g[111].host == "pmx10"
    assert g[102].ips == ("192.0.2.47",) and g[102].kind == "lxc"
    assert g[103].ips == ("192.0.2.55",) and g[103].ip_note == ""
    assert g[120].ips == () and g[120].ip_note == "IP unbekannt: gestoppt"
    assert g[111].passthrough == ("hostpci0: 0000:01:00.0,pcie=1", "usb0: host=1-2")
    assert g[102].passthrough == ("dev0: /dev/nvidia0", "dev1: /dev/dri/renderD128,gid=104")
    assert g[103].passthrough == ()
    paths = [c.url.path for c in calls]
    assert not any("/qemu/120/agent" in p for p in paths)
    assert all(c.method == "GET" for c in calls)


def test_guests_without_ips_and_passthrough_only_lists(tmp_path):
    calls: list[httpx.Request] = []
    with _client(tmp_path, calls=calls) as client:
        guests = client.guests(with_ips=False, with_passthrough=False)
    assert len(guests) == 4
    assert [c.url.path for c in calls] == ["/api2/json/cluster/resources"]
    assert all(g.ips == () and g.passthrough == () for g in guests)


def test_agent_403_is_permission_note(tmp_path):
    routes = _routes(**{"GET /api2/json/nodes/pmx10/qemu/111/agent/network-get-interfaces":
                        (403, {"data": None})})
    with _client(tmp_path, routes) as client:
        g = _by_id(client.guests())[111]
    assert g.ips == ()
    assert g.ip_note == "IP unbekannt: Recht VM.GuestAgent.Audit fehlt"


def test_agent_403_pve8_monitor(tmp_path):
    def handler(request):
        return httpx.Response(403, json={"data": None},
                              extensions={"reason_phrase": b"Permission check failed (/vms/111, VM.Monitor)"})

    routes = _routes(**{"GET /api2/json/nodes/pmx10/qemu/111/agent/network-get-interfaces": handler})
    with _client(tmp_path, routes) as client:
        g = _by_id(client.guests())[111]
    assert g.ip_note == "IP unbekannt: Recht VM.Monitor fehlt"


@pytest.mark.parametrize("message", ["QEMU guest agent is not running", "No QEMU guest agent configured"])
def test_agent_500_not_running(tmp_path, message):
    routes = _routes(**{"GET /api2/json/nodes/pmx10/qemu/111/agent/network-get-interfaces":
                        (500, {"data": None, "message": message + "\n"})})
    with _client(tmp_path, routes) as client:
        guests = client.guests()
    g = _by_id(guests)[111]
    assert g.ips == ()
    assert g.ip_note == "IP unbekannt: Guest-Agent läuft nicht"
    assert len(guests) == 4


def test_agent_other_error_is_plain_unknown(tmp_path):
    routes = _routes(**{"GET /api2/json/nodes/pmx10/qemu/111/agent/network-get-interfaces":
                        (500, {"data": None, "message": "irgendwas"})})
    with _client(tmp_path, routes) as client:
        assert _by_id(client.guests())[111].ip_note == "IP unbekannt"


def test_lxc_dhcp_note(tmp_path):
    config = load_json("proxmox/lxc-103-config.json")
    config["data"]["net0"] = "name=eth0,bridge=vmbr0,ip=dhcp,type=veth"
    routes = _routes(**{"GET /api2/json/nodes/pmx10/lxc/103/config": config})
    with _client(tmp_path, routes) as client:
        g = _by_id(client.guests())[103]
    assert g.ips == ()
    assert g.ip_note == "IP unbekannt: DHCP"


def test_ips_sorted_home_network_first(tmp_path):
    agent = load_json("proxmox/agent-111.json")
    agent["data"]["result"].insert(1, {"name": "docker0", "ip-addresses": [
        {"ip-address": "172.17.0.1", "ip-address-type": "ipv4", "prefix": 16},
        {"ip-address": "169.254.3.3", "ip-address-type": "ipv4", "prefix": 16}]})
    routes = _routes(**{"GET /api2/json/nodes/pmx10/qemu/111/agent/network-get-interfaces": agent})
    with _client(tmp_path, routes) as client:
        assert _by_id(client.guests())[111].ips == ("192.0.2.39", "172.17.0.1")


def test_too_many_guests(tmp_path):
    many = {"data": [{"type": "lxc", "vmid": 1000 + i, "name": f"g{i}", "node": "pmx10", "status": "stopped"}
                     for i in range(201)]}
    routes = _routes(**{"GET /api2/json/cluster/resources?type=vm": many})
    with _client(tmp_path, routes) as client, pytest.raises(ValueError, match="200"):
        client.guests()


def test_connect_error_is_not_reachable(tmp_path):
    client = ProxmoxClient.from_settings(_settings(tmp_path), "pmx10", transport=connect_error_transport())
    with client, pytest.raises(NotReachable):
        client.guests()


def test_missing_token(tmp_path):
    with pytest.raises(TokenMissing, match="Proxmox pmx10"):
        ProxmoxClient.from_settings(_settings(tmp_path, token=None), "pmx10", transport=mock_transport({}))


def test_verify_false_emits_no_python_warning():
    host = PveHost(name="pmx10", url="https://192.0.2.1:8006", token_ref="env:X", verify_tls=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ProxmoxClient(host, "x").close()


def test_tls_warnings():
    host = PveHost(name="pmx10", url="https://192.0.2.1:8006", token_ref="env:X")
    assert proxmox.tls_warnings(host) == ["TLS-Zertifikat von pmx10 wird nicht geprüft"]
    assert proxmox.tls_warnings(PveHost("pmx10", "https://x", "env:X", verify_tls=True)) == []


def _guest(vmid, kind="qemu", name="x", status="running", ips=("192.0.2.10",)):
    return Guest(host="pmx10", node="pmx10", vmid=vmid, kind=kind, name=name, status=status, tags=(),
                 ips=ips, ip_note="", passthrough=())


def test_filter_guests():
    guests = [_guest(100), _guest(105, "lxc", "Frigate"), _guest(111, name="webapp1"),
              _guest(120, status="stopped"), _guest(130, "lxc", "frigate2", "stopped")]
    assert [g.vmid for g in filter_guests(guests, ids="100-110,120")] == [100, 105, 120]
    assert [g.vmid for g in filter_guests(guests, status="running")] == [100, 105, 111]
    assert [g.vmid for g in filter_guests(guests, kind="lxc")] == [105, 130]
    assert [g.vmid for g in filter_guests(guests, name="FRI")] == [105, 130]
    assert [g.vmid for g in filter_guests(guests, name="FRI", status="stopped")] == [130]
    with pytest.raises(ValueError):
        filter_guests(guests, ids="abc")
    with pytest.raises(ValueError):
        filter_guests(guests, kind="vm")


def test_short_ip():
    assert short_ip("192.0.2.39", NETS) == ".39"
    assert short_ip("10.0.0.5", NETS) == "10.0.0.5"
    assert short_ip(None, NETS) == ""
    assert short_ip("10.1.0.5", ["10.0.0.0/8"]) == "10.1.0.5"


def test_guest_rows_link_id_console():
    g = Guest(host="pmx10", node="pmx10", vmid=111, kind="qemu", name="webapp1", status="running",
              tags=(), ips=("192.0.2.39",), ip_note="", passthrough=())
    lxc = _guest(102, "lxc", "frigate", ips=())
    headers, rows = guest_rows([g, lxc], networks=NETS, links={111: "HTTPS://L.EXAMPLE.COM/PMX10-111"})
    assert headers == ["typ", "vmid", "name", "ip_kurz", "ip", "node", "host", "link"]
    assert rows[0] == ["VM", "111", "webapp1", ".39", "192.0.2.39", "pmx10", "pmx10",
                       "HTTPS://L.EXAMPLE.COM/PMX10-111"]
    assert rows[1] == ["LXC", "102", "frigate", "", "", "pmx10", "pmx10", ""]
    assert guest_link_id(g) == "PMX10-111"
    host = PveHost("pmx10", "https://192.0.2.60:8006", "env:X")
    assert console_url(host, g) == "https://192.0.2.60:8006/#v1:0:=qemu%2F111"


def test_guest_links_without_shortlink(tmp_path):
    data = _settings(tmp_path)
    data["shortlink"] = {"base_url": None, "admin_url": None, "token_ref": "env:NOPE", "timeout_s": 10.0}
    host = find_host(data, "pmx10")
    links, warns = proxmox.guest_links(data, host, [_guest(111)])
    assert links == {111: "https://192.0.2.60:8006/#v1:0:=qemu%2F111"}
    assert warns == ["Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Proxmox-Adresse"]


def test_guest_links_with_shortlink(tmp_path):
    data = _settings(tmp_path)
    data["shortlink"] = {"base_url": "https://l.example.com", "admin_url": None,
                         "token_ref": token_file(tmp_path, "sl"), "timeout_s": 10.0}
    calls: list[httpx.Request] = []

    def put(request):
        return httpx.Response(200, json={"id": "PMX10-111", "target": "x", "note": "", "created": "",
                                         "updated": "", "hits": 0})

    transport = mock_transport({"PUT /api/links/PMX10-111": put}, calls=calls)
    links, warns = proxmox.guest_links(data, find_host(data, "pmx10"), [_guest(111, name="webapp1")],
                                       transport=transport)
    assert links == {111: "HTTPS://L.EXAMPLE.COM/PMX10-111"}
    assert warns == []
    assert b"webapp1 (qemu 111)" in calls[0].content
