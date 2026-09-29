"""Cache des letzten SSH-Scans je Host."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from tapesmith.integrations import scancache, settings
from tapesmith.sshscan import DiskRow, parse_output

DATA = Path(__file__).parent / "data" / "ssh"
WHEN = datetime(2026, 9, 28, 10, 0, 0)


def _disks() -> list[DiskRow]:
    lsblk = (DATA / "pmx10-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "pmx10-byid.txt").read_text(encoding="utf-8")
    zpool = (DATA / "pmx10-zpool.txt").read_text(encoding="utf-8")
    stdout = lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool
    return parse_output("pmx10", stdout)[:2]


def test_round_trip():
    disks = _disks()
    assert len(disks) == 2
    record = scancache.save_scan("pmx10", disks, when=WHEN)
    assert record.scanned_at == "2026-09-28T10:00:00"
    loaded = scancache.load_scan("pmx10")
    assert loaded is not None
    assert loaded.disks == tuple(disks)
    assert loaded.scanned_at == "2026-09-28T10:00:00"
    assert loaded.host == "pmx10"
    path = settings.data_dir() / "scans" / "pmx10.json"
    assert json.loads(path.read_text(encoding="utf-8"))["host"] == "pmx10"


def test_missing_and_unknown_keys_are_tolerated():
    folder = settings.data_dir() / "scans"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pmx11.json").write_text(json.dumps({
        "host": "pmx11", "scanned_at": "2026-09-28T09:00:00",
        "disks": [{"host": "pmx11", "device": "sda", "neu": 1}]}), encoding="utf-8")
    record = scancache.load_scan("pmx11")
    disk = record.disks[0]
    assert disk.device == "sda" and disk.serial == "" and disk.pool is None


def test_broken_file_is_none():
    folder = settings.data_dir() / "scans"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pmx10.json").write_text("{kaputt", encoding="utf-8")
    assert scancache.load_scan("pmx10") is None
    assert scancache.load_scan("gibtsnicht") is None


@pytest.mark.parametrize("host", ["../x", "", "..", "a b", "x" * 33])
def test_invalid_host_raises(host):
    with pytest.raises(ValueError):
        scancache.save_scan(host, [])


def test_all_scans_sorted():
    scancache.save_scan("pmx12", [], when=WHEN)
    scancache.save_scan("pmx10", _disks(), when=WHEN)
    folder = settings.data_dir() / "scans"
    (folder / "kaputt.json").write_text("[", encoding="utf-8")
    assert [r.host for r in scancache.all_scans()] == ["pmx10", "pmx12"]
