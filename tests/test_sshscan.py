"""SSH-Disk-Scanner: `parse_output`, `ssh_argv`, `hosts_from_config`, `scan_host`,
`rows_for_template`/`disks_to_table` und die Integration mit `build_batch`.

Keine echte SSH-Verbindung: alle Tests arbeiten mit aufgezeichneten Fake-Ausgaben
(`tests/data/ssh/`) und injizierten Fake-Runnern/-Uhren.
"""

from datetime import datetime
from pathlib import Path

import pytest

from tapesmith.dataimport.batch import build_batch
from tapesmith.device.profile import load_profile
from tapesmith.sshscan import (
    DiskRow,
    SshError,
    SshHost,
    disks_to_table,
    find_host,
    hosts_from_config,
    parse_output,
    rows_for_template,
    scan_host,
    ssh_argv,
)
from tapesmith.templates.fill import CounterStore
from tapesmith.templates.store import find_template

DATA = Path(__file__).parent / "data" / "ssh"


def _fake_stdout(byid: str | None = None, zpool: str | None = None) -> str:
    lsblk = (DATA / "pmx10-lsblk.json").read_text(encoding="utf-8")
    byid_text = byid if byid is not None else (DATA / "pmx10-byid.txt").read_text(encoding="utf-8")
    zpool_text = zpool if zpool is not None else (DATA / "pmx10-zpool.txt").read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid_text + "\n@@ZPOOL@@\n" + zpool_text


LS_L_BYID = """total 0
lrwxrwxrwx 1 root root  9 Sep 26 10:00 ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456 -> ../../sda
lrwxrwxrwx 1 root root 10 Sep 26 10:00 ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part1 -> ../../sda1
lrwxrwxrwx 1 root root  9 Sep 26 10:00 wwn-0x5002538f -> ../../sda
lrwxrwxrwx 1 root root  9 Sep 26 10:00 ata-WDC_WD40EFRX-68N32N0_WD-WCC7K1ABCDEF -> ../../sdb
lrwxrwxrwx 1 root root 13 Sep 26 10:00 nvme-eui.002538b111b2c3d4 -> ../../nvme0n1
lrwxrwxrwx 1 root root 13 Sep 26 10:00 nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T987654 -> ../../nvme0n1
lrwxrwxrwx 1 root root 13 Sep 26 10:00 nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T987654_1 -> ../../nvme0n1
"""


# 1. parse_output: lsblk-JSON + find-Format + zpool ------------------------------------------

def test_parse_output_finds_three_disks_with_byid_and_pool():
    disks = parse_output("pmx10", _fake_stdout())
    by_device = {d.device: d for d in disks}

    assert set(by_device) == {"sda", "sdb", "nvme0n1"}

    sda = by_device["sda"]
    assert sda.by_id == "ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456"
    assert sda.pool == "rpool"
    assert sda.vdev == "mirror-0"

    sdb = by_device["sdb"]
    assert sdb.pool == "rpool"
    assert sdb.vdev == "mirror-0"

    nvme = by_device["nvme0n1"]
    assert nvme.by_id == "nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T987654"
    assert nvme.serial == "S5GXNX0T987654"
    assert nvme.pool == "tank"
    assert nvme.vdev is None


# 2. ls -l-Format, kein Pool -------------------------------------------------------------------

def test_parse_output_accepts_ls_l_format_and_no_pool_without_zpool_content():
    disks = parse_output("pmx10", _fake_stdout(byid=LS_L_BYID, zpool=""))
    by_device = {d.device: d for d in disks}

    assert by_device["sda"].by_id == "ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456"
    assert by_device["sdb"].by_id == "ata-WDC_WD40EFRX-68N32N0_WD-WCC7K1ABCDEF"
    assert by_device["nvme0n1"].by_id == "nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T987654"
    for disk in disks:
        assert disk.pool is None
        assert disk.vdev is None


# 3. ungültiges JSON ---------------------------------------------------------------------------

def test_parse_output_invalid_json_raises_ssh_error():
    stdout = "kein json\n@@BYID@@\n\n@@ZPOOL@@\n"
    with pytest.raises(SshError):
        parse_output("pmx10", stdout)


# 4. ssh_argv ------------------------------------------------------------------------------------

def test_ssh_argv_uses_batchmode_and_expands_key_path(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\testuser")
    host = SshHost(name="pmx10", host="192.0.2.60", user="root", port=22,
                   key=r"%USERPROFILE%\.ssh\id_ed25519_homelab")
    argv = ssh_argv(host, ssh_exe=r"C:\Windows\System32\OpenSSH\ssh.exe", timeout_s=20.0)

    assert r"C:\Users\testuser\.ssh\id_ed25519_homelab" in argv
    idx_i = argv.index("-i")
    assert argv[idx_i + 1] == r"C:\Users\testuser\.ssh\id_ed25519_homelab"
    assert "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=yes" in argv
    idx_dashdash = argv.index("--")
    assert argv[idx_dashdash + 1] == "root@192.0.2.60"
    assert argv[-1] == argv[-1]  # REMOTE_SCRIPT ist das letzte Element
    from tapesmith.sshscan import REMOTE_SCRIPT
    assert argv[-1] == REMOTE_SCRIPT


def test_ssh_argv_accept_new_when_not_strict():
    host = SshHost(name="pmx10", host="192.0.2.60", key="/tmp/key")
    argv = ssh_argv(host, ssh_exe="ssh", timeout_s=5.0, strict_host_key=False)
    assert "StrictHostKeyChecking=accept-new" in argv


# 5. hosts_from_config -----------------------------------------------------------------------

def test_hosts_from_config_valid():
    cfg = {"ssh": {"hosts": [
        {"name": "pmx10", "host": "192.0.2.60", "user": "root", "port": 22, "key": "/tmp/k"},
    ]}}
    hosts = hosts_from_config(cfg)
    assert hosts == [SshHost(name="pmx10", host="192.0.2.60", user="root", port=22, key="/tmp/k")]
    assert find_host(cfg, "pmx10") == hosts[0]
    with pytest.raises(ValueError):
        find_host(cfg, "unbekannt")


@pytest.mark.parametrize("host_entry", [
    {"name": "pmx10", "host": "-oProxyCommand=calc", "key": "/tmp/k"},
    {"name": "pmx10", "host": "1.2.3.4", "user": "root;rm", "key": "/tmp/k"},
    {"name": "pmx10", "host": "1.2.3.4", "port": 0, "key": "/tmp/k"},
])
def test_hosts_from_config_rejects_invalid_entries(host_entry):
    with pytest.raises(ValueError):
        hosts_from_config({"ssh": {"hosts": [host_entry]}})


def test_hosts_from_config_rejects_duplicate_name():
    entry = {"name": "pmx10", "host": "1.2.3.4", "key": "/tmp/k"}
    with pytest.raises(ValueError):
        hosts_from_config({"ssh": {"hosts": [entry, dict(entry)]}})


# 6. scan_host mit Fake-Runner ------------------------------------------------------------------

def _host(tmp_path: Path) -> tuple[SshHost, Path]:
    key = tmp_path / "id_ed25519_test"
    key.write_text("fake-key", encoding="utf-8")
    return SshHost(name="pmx10", host="192.0.2.60", user="root", port=22, key=str(key)), key


def test_scan_host_success_with_fake_runner(tmp_path):
    host, _key = _host(tmp_path)
    stdout = _fake_stdout()

    def fake_runner(argv, timeout):
        return 0, stdout, ""

    disks = scan_host(host, runner=fake_runner, ssh_exe="ssh")
    assert {d.device for d in disks} == {"sda", "sdb", "nvme0n1"}


def test_scan_host_permission_denied_becomes_login_hint(tmp_path):
    host, key = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 255, "", "Permission denied (publickey)."

    with pytest.raises(SshError) as excinfo:
        scan_host(host, runner=fake_runner, ssh_exe="ssh")
    assert "Anmeldung abgelehnt" in str(excinfo.value)
    assert str(key) in str(excinfo.value)


def test_scan_host_host_key_unknown(tmp_path):
    host, _key = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 255, "", "Host key verification failed."

    with pytest.raises(SshError) as excinfo:
        scan_host(host, runner=fake_runner, ssh_exe="ssh")
    assert "Host-Schlüssel unbekannt" in str(excinfo.value)


def test_scan_host_missing_key_does_not_call_runner(tmp_path):
    host, _key = _host(tmp_path)
    called = []

    def fake_runner(argv, timeout):
        called.append(argv)
        return 0, "", ""

    with pytest.raises(SshError):
        scan_host(host, runner=fake_runner, ssh_exe="ssh", key_exists=lambda p: False)
    assert called == []


# 7. rows_for_template / disks_to_table ----------------------------------------------------------

def test_rows_for_template_and_disks_to_table():
    disks = parse_output("pmx10", _fake_stdout())
    rows = rows_for_template(disks, slots={"sda": "SSD-1"})
    by_device = {d.device: r for d, r in zip(disks, rows)}
    assert by_device["sda"]["slot"] == "SSD-1"
    assert by_device["sdb"]["slot"] == "sdb"

    table = disks_to_table(disks)
    assert table.headers == ("host", "slot", "sn", "model", "device", "by_id", "pool", "vdev", "size")
    assert table.source == "SSH pmx10"


# 8. Integration mit build_batch ------------------------------------------------------------

def test_build_batch_with_disk_rows_produces_error_free_labels(tmp_path):
    disks = parse_output("pmx10", _fake_stdout())
    rows = rows_for_template(disks)
    template = find_template("datentraeger")
    profile = load_profile()
    counters = CounterStore(tmp_path / "counters.json")

    plan = build_batch(template, rows, profile, now=datetime(2026, 9, 27), counters=counters)

    assert not plan.errors
    assert len(plan.labels) == 3
