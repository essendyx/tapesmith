"""Datenträger-Assistent und SSH-Disk-Scanner über die Web-API."""

from pathlib import Path

import pytest

from tapesmith.drives import DriveInfo
from webapi_fakes import close_ctx, make_client

DATA = Path(__file__).parent / "data" / "ssh"


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


# ---------- Datenträger ----------

class FakeDrivesBackend:
    def __init__(self, drives: dict[str, dict]):
        self._drives = drives

    def roots(self) -> list[str]:
        return list(self._drives)

    def drive_type(self, root: str) -> int:
        return self._drives[root]["type"]

    def volume(self, root: str) -> tuple[str, str]:
        d = self._drives[root]
        return d["label"], d["fs"]

    def space(self, root: str) -> tuple[int, int]:
        d = self._drives[root]
        return d["total"], d["free"]

    def bus(self, root: str) -> str:
        return self._drives[root]["bus"]


def test_drives_with_fake_backend(tmp_path):
    from tapesmith.drives import DRIVE_REMOVABLE

    backend = FakeDrivesBackend({
        "E:\\": {"type": DRIVE_REMOVABLE, "label": "FOTOS 2025", "fs": "exFAT",
                "total": 64_000_000_000, "free": 1_000_000_000, "bus": "usb"},
    })
    client, ctx = make_client(tmp_path, drives_backend=backend)
    try:
        r = client.get("/api/v1/drives")
        assert r.status_code == 200
        drives = r.json()["drives"]
        assert len(drives) == 1
        drive = drives[0]
        assert drive["root"] == "E:\\"
        assert drive["size_text"] == "64 GB"
        assert drive["suggestion"] == ["Fotos 2025", "64 GB · exFAT"]
    finally:
        close_ctx(ctx)


def test_drive_info_dataclass_smoke():
    # nur zur Erinnerung, dass DriveInfo importierbar bleibt (Kernmodul, keine Web-Logik)
    info = DriveInfo(root="E:\\", label="X", size_bytes=1, free_bytes=1, filesystem="",
                     bus="unbekannt", removable=True)
    assert info.root == "E:\\"


# ---------- SSH ----------

def _fake_ssh_stdout() -> str:
    lsblk = (DATA / "pmx10-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "pmx10-byid.txt").read_text(encoding="utf-8")
    zpool = (DATA / "pmx10-zpool.txt").read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool


def _ssh_config(tmp_path) -> tuple[dict, Path]:
    key_path = tmp_path / "id_test_key"
    key_path.write_text("dummy-key", encoding="utf-8")
    cfg = {"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root",
                              "port": 22, "key": str(key_path)}],
                  "timeout_s": 5, "strict_host_key": True}}
    return cfg, key_path


def test_ssh_hosts(tmp_path):
    cfg, _key = _ssh_config(tmp_path)
    client, ctx = make_client(tmp_path, config=cfg)
    try:
        r = client.get("/api/v1/ssh/hosts")
        assert r.status_code == 200
        hosts = r.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["name"] == "pmx10"
        assert hosts[0]["host"] == "192.0.2.60"
        assert hosts[0]["key"] == str(_key)
    finally:
        close_ctx(ctx)


def test_ssh_scan_ok(tmp_path):
    cfg, _key = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 0, _fake_ssh_stdout(), ""

    client, ctx = make_client(tmp_path, config=cfg, ssh_runner=runner)
    try:
        r = client.post("/api/v1/ssh/scan", json={"host": "pmx10"})
        assert r.status_code == 200, r.text
        disks = r.json()["disks"]
        assert {d["device"] for d in disks} == {"sda", "sdb", "nvme0n1"}
        sda = next(d for d in disks if d["device"] == "sda")
        assert sda["serial"] == "S5Y1NX0R123456"
    finally:
        close_ctx(ctx)


def test_ssh_scan_error_is_502(tmp_path):
    cfg, _key = _ssh_config(tmp_path)

    def runner(argv, timeout):
        return 1, "", "boom: Verbindung abgelehnt"

    client, ctx = make_client(tmp_path, config=cfg, ssh_runner=runner)
    try:
        r = client.post("/api/v1/ssh/scan", json={"host": "pmx10"})
        assert r.status_code == 502
        assert r.json()["error"]["kind"] == "SSH"
        assert "boom" in r.json()["error"]["message"]
    finally:
        close_ctx(ctx)


def test_ssh_scan_unknown_host_is_404(tmp_path):
    cfg, _key = _ssh_config(tmp_path)
    client, ctx = make_client(tmp_path, config=cfg)
    try:
        r = client.post("/api/v1/ssh/scan", json={"host": "nirgendwo"})
        assert r.status_code == 404
    finally:
        close_ctx(ctx)


def _two_disks() -> list[dict]:
    return [
        {"host": "pmx10", "device": "sda", "model": "Samsung SSD 870 EVO", "serial": "S5Y1NX0R123456",
         "size": "931.5G", "tran": "sata", "wwn": "", "by_id": None, "pool": None, "vdev": None},
        {"host": "pmx10", "device": "sdb", "model": "WDC WD40EFRX", "serial": "WD-WCC7K1ABCDEF",
         "size": "3.7T", "tran": "sata", "wwn": "", "by_id": None, "pool": None, "vdev": None},
    ]


def test_ssh_series_plan(api):
    client, _ctx = api
    body = {"host": "pmx10", "disks": _two_disks(), "slots": {"sda": "SSD-1", "sdb": "SSD-2"},
           "chain": False, "cut_marks": True}
    r = client.post("/api/v1/ssh/series", json=body)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["count"] == 2
    assert len(plan["previews"]) == 2
    assert plan["errors"] == []
    assert plan["mapping"] == {} and plan["headers"] == []


def test_ssh_series_print(api):
    client, _ctx = api
    body = {"host": "pmx10", "disks": _two_disks(), "slots": {"sda": "SSD-1", "sdb": "SSD-2"},
           "chain": False, "cut_marks": True}
    r = client.post("/api/v1/ssh/series/print", json=body)
    assert r.status_code == 200, r.text
    outcome = r.json()
    assert outcome["status"] == "ok"
    assert outcome["history_id"] is not None
