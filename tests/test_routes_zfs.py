"""Routen `/api/v1/homelab/zfs/scan` und `/plan`."""

from datetime import datetime
from pathlib import Path

from homelab_fakes import router_client
from webapi_fakes import close_ctx

from tapesmith.templates.fill import input_fields
from tapesmith.templates.store import find_template
from tapesmith.templates import fill as fill_mod
from tapesmith import numbering
from tapesmith.webapi import routes_zfs

DATA = Path(__file__).parent / "data" / "zfs"


def _fake_stdout(zpool: str) -> str:
    lsblk = (DATA / "degraded-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "degraded-byid.txt").read_text(encoding="utf-8")
    zpool_text = (DATA / zpool).read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool_text


DEGRADED_STDOUT = _fake_stdout("degraded-zpool.txt")


def _ssh_config(tmp_path):
    key_path = tmp_path / "id_ed25519_test"
    key_path.write_text("fake-key", encoding="utf-8")
    cfg = {"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root",
                              "port": 22, "key": str(key_path)}],
                  "timeout_s": 5, "strict_host_key": True}}
    return cfg


def test_scan_liefert_probleme_und_kandidaten(tmp_path):
    cfg = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg, ssh_runner=runner)
    try:
        r = client.post("/api/v1/homelab/zfs/scan", json={"host": "pmx10"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["host"] == "pmx10"
        assert len(data["problems"]) == 1
        assert data["problems"][0]["state"] == "FAULTED"
        assert [c["disk"]["device"] for c in data["candidates"]] == ["sdc"]
    finally:
        close_ctx(ctx)


def test_plan_nach_scan_liefert_befehl_und_labels(tmp_path):
    cfg = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg, ssh_runner=runner,
                                now=lambda: datetime(2026, 9, 28, 9, 0, 0))
    try:
        r = client.post("/api/v1/homelab/zfs/scan", json={"host": "pmx10"})
        assert r.status_code == 200, r.text
        old_name = r.json()["problems"][0]["name"]

        r2 = client.post("/api/v1/homelab/zfs/plan",
                         json={"host": "pmx10", "old": old_name, "new_device": "sdc", "slot": "SSD-1"})
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["command"].startswith("zpool replace rpool ")
        assert data["old_label"]["template"] == "platte-defekt"
        assert data["old_label"]["values"]["datum"] == "28.09.2026"
        assert data["new_label"]["template"] == "datentraeger"
    finally:
        close_ctx(ctx)


def test_plan_ohne_scan_ist_422(tmp_path):
    cfg = _ssh_config(tmp_path)
    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg)
    try:
        r = client.post("/api/v1/homelab/zfs/plan",
                        json={"host": "pmx10", "old": "x", "new_device": "sdc", "slot": "SSD-1"})
        assert r.status_code == 422
    finally:
        close_ctx(ctx)


def test_scan_mit_ssh_fehler_ist_502(tmp_path):
    cfg = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 255, "", "Permission denied (publickey)."

    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg, ssh_runner=runner)
    try:
        r = client.post("/api/v1/homelab/zfs/scan", json={"host": "pmx10"})
        assert r.status_code == 502
        assert r.json()["error"]["kind"] == "SSH"
    finally:
        close_ctx(ctx)


def test_scan_unbekannter_host_ist_404(tmp_path):
    cfg = _ssh_config(tmp_path)
    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg)
    try:
        r = client.post("/api/v1/homelab/zfs/scan", json={"host": "unbekannt"})
        assert r.status_code == 404
    finally:
        close_ctx(ctx)


def test_plan_labels_are_printable(tmp_path):
    cfg = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    client, ctx = router_client(tmp_path, routes_zfs.router, config=cfg, ssh_runner=runner,
                                now=lambda: datetime(2026, 9, 28, 9, 0, 0))
    try:
        r = client.post("/api/v1/homelab/zfs/scan", json={"host": "pmx10"})
        old_name = r.json()["problems"][0]["name"]
        r2 = client.post("/api/v1/homelab/zfs/plan",
                         json={"host": "pmx10", "old": old_name, "new_device": "sdc", "slot": "SSD-1"})
        data = r2.json()
        cfg_dict = ctx.config()
        counters = numbering.counter_store(cfg_dict)
        for key in ("old_label", "new_label"):
            template = find_template(data[key]["template"])
            values = data[key]["values"]
            allowed = {f.id for f in input_fields(template)}
            assert set(values) <= allowed
            fill_mod.resolve_values(template, values, datetime(2026, 9, 28), counters)
        assert data["old_label"]["values"]["datum"] == "28.09.2026"
    finally:
        close_ctx(ctx)
