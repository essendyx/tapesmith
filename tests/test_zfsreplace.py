"""Assistent „Platte tauschen": Pools parsen, Kandidaten erkennen, Ersatzbefehl planen.

Keine echte SSH-Verbindung: Fake-Ausgaben aus `tests/data/zfs/` und injizierte Fake-Runner.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from tapesmith.integrations import scancache, zfsreplace
from tapesmith.sshscan import SshError, SshHost, parse_output
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.store import find_template

DATA = Path(__file__).parent / "data" / "zfs"


def _fake_stdout(zpool: str) -> str:
    lsblk = (DATA / "degraded-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "degraded-byid.txt").read_text(encoding="utf-8")
    zpool_text = (DATA / zpool).read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool_text


DEGRADED_STDOUT = _fake_stdout("degraded-zpool.txt")
UNAVAIL_STDOUT = _fake_stdout("unavail-zpool.txt")


def _host(tmp_path: Path) -> SshHost:
    key = tmp_path / "id_ed25519_test"
    key.write_text("fake-key", encoding="utf-8")
    return SshHost(name="pmx10", host="192.0.2.60", user="root", port=22, key=str(key))


# 1. parse_pools -----------------------------------------------------------------------------

def test_parse_pools_erkennt_beide_pools_und_zustaende():
    pools = zfsreplace.parse_pools(DEGRADED_STDOUT)
    by_name = {p.name: p for p in pools}
    assert set(by_name) == {"rpool", "tank"}
    assert by_name["rpool"].state == "DEGRADED"
    assert by_name["tank"].state == "ONLINE"
    assert by_name["rpool"].errors == "No known data errors"


def test_faulted_blatt_hat_byid_partition_device_und_note():
    pools = zfsreplace.parse_pools(DEGRADED_STDOUT)
    rpool = next(p for p in pools if p.name == "rpool")
    faulted = next(d for d in rpool.devices if d.state == "FAULTED")
    assert faulted.by_id == "ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456"
    assert faulted.partition == "part3"
    assert faulted.device == "sda"
    assert faulted.note == "too many errors"
    assert faulted.vdev == "mirror-0"


def test_dev_sdb3_hat_kein_byid():
    pools = zfsreplace.parse_pools(DEGRADED_STDOUT)
    rpool = next(p for p in pools if p.name == "rpool")
    sdb = next(d for d in rpool.devices if d.name == "/dev/sdb3")
    assert sdb.by_id is None
    assert sdb.device == "sdb"
    assert sdb.state == "ONLINE"


def test_unavail_zeile_hat_guid_als_name_und_was_path():
    pools = zfsreplace.parse_pools(UNAVAIL_STDOUT)
    rpool = next(p for p in pools if p.name == "rpool")
    unavail = next(d for d in rpool.devices if d.state == "UNAVAIL")
    assert unavail.name == "9876543210987654321"
    assert unavail.was_path == "/dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-WCC7K1234567-part1"
    assert unavail.by_id == "ata-WDC_WD40EFRX-68N32N0_WD-WCC7K1234567"
    assert unavail.partition == "part1"
    assert unavail.vdev == "raidz1-0"


def test_unavail_build_plan_nutzt_guid_im_befehl(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, UNAVAIL_STDOUT, ""

    ov, _stdout = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh")
    plan = zfsreplace.build_plan(ov, "9876543210987654321", "sdc", slot="SSD-1", today=date(2026, 9, 28))
    assert "9876543210987654321" in plan.command
    assert plan.command == (
        "zpool replace rpool 9876543210987654321 "
        "/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R999999"
    )


# 2. problem_devices --------------------------------------------------------------------------

def test_problem_devices_liefert_nur_blaetter():
    pools = zfsreplace.parse_pools(DEGRADED_STDOUT)
    problems = zfsreplace.problem_devices(pools)
    names = {d.name for d in problems}
    assert names == {"/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3"}
    assert "mirror-0" not in names
    assert "rpool" not in names


# 3. candidates --------------------------------------------------------------------------------

def test_candidates_ohne_vorigen_scan():
    disks = parse_output("pmx10", DEGRADED_STDOUT)
    cands = zfsreplace.candidates(disks, None)
    assert [c.disk.device for c in cands] == ["sdc"]
    assert cands[0].reason == "in keinem Pool"


def test_candidates_mit_vorigem_scan_ohne_sdc():
    disks = parse_output("pmx10", DEGRADED_STDOUT)
    previous = [d for d in disks if d.device != "sdc"]
    cands = zfsreplace.candidates(disks, previous)
    assert [c.disk.device for c in cands] == ["sdc"]
    assert cands[0].reason == "neu seit dem letzten Scan"


# 4. overview mit Fake-Runner ------------------------------------------------------------------

def test_overview_speichert_scan_und_liest_vorigen(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    assert scancache.load_scan("pmx10") is None
    ov1, stdout1 = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh",
                                       now=lambda: datetime(2026, 9, 20, 8, 0, 0))
    assert stdout1 == DEGRADED_STDOUT
    assert ov1.previous_scanned_at is None
    assert scancache.load_scan("pmx10") is not None

    ov2, _stdout2 = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh",
                                        now=lambda: datetime(2026, 9, 28, 8, 0, 0))
    assert ov2.previous_scanned_at == "2026-09-20T08:00:00"
    assert ov2.scanned_at == "2026-09-28T08:00:00"


# 5. Vorlage platte-defekt: datum als input-Feld ------------------------------------------------

def test_old_label_resolves(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    ov, _stdout = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh")
    plan = zfsreplace.build_plan(
        ov, "/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3", "sdc",
        slot="SSD-1", today=date(2026, 9, 28),
    )
    template = find_template("platte-defekt")
    assert template.field("datum").type == "input"
    counters = CounterStore(tmp_path / "counters.json")
    resolved = resolve_values(template, plan.old_label, datetime(2026, 9, 28), counters)
    assert resolved.values["datum"] == "28.09.2026"

    dt_template = find_template("datentraeger")
    resolved_new = resolve_values(dt_template, plan.new_label, datetime(2026, 9, 28), counters)
    assert resolved_new.values["sn"]


# 6. build_plan: Befehl, Hinweise, Changelog, Fehlerfälle ---------------------------------------

def _plan_for_degraded(tmp_path, *, old="/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3",
                       new="sdc"):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    ov, _stdout = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh")
    return zfsreplace.build_plan(ov, old, new, slot="SSD-1", today=date(2026, 9, 28))


def test_build_plan_befehl_hinweis_und_changelog(tmp_path):
    plan = _plan_for_degraded(tmp_path)
    assert plan.command == (
        "zpool replace rpool /dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3 "
        "/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R999999"
    )
    assert any("partitioniert" in h for h in plan.hints)
    assert "[[Hosts/pmx10]]" in plan.changelog_md
    assert "\u2013" not in plan.changelog_md and "\u2014" not in plan.changelog_md
    assert plan.old_label["sn"] == "S5Y1NX0R123456"


def test_build_plan_altes_geraet_online_wirft_value_error(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    ov, _stdout = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh")
    with pytest.raises(ValueError):
        zfsreplace.build_plan(ov, "/dev/sdb3", "sdc", slot="SSD-1", today=date(2026, 9, 28))


def test_build_plan_neue_platte_schon_im_pool_wirft_value_error(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 0, DEGRADED_STDOUT, ""

    ov, _stdout = zfsreplace.overview(host, runner=fake_runner, ssh_exe="ssh")
    with pytest.raises(ValueError):
        zfsreplace.build_plan(
            ov, "/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3", "sdb",
            slot="SSD-1", today=date(2026, 9, 28),
        )


# 7. scan_raw mit SSH-Fehler ---------------------------------------------------------------------

def test_scan_raw_mit_returncode_255_wirft_ssh_error(tmp_path):
    host = _host(tmp_path)

    def fake_runner(argv, timeout):
        return 255, "", "Permission denied (publickey)."

    with pytest.raises(SshError) as excinfo:
        zfsreplace.scan_raw(host, runner=fake_runner, ssh_exe="ssh")
    assert "Anmeldung abgelehnt" in str(excinfo.value)
