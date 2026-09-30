"""CLI-Integration `tapesmith disks`: `hosts`/`scan`/`print`, zentrale Zähler,
`SshError` -> Exit 5. Kein echter SSH-Aufruf: `RUNNER` wird durch einen Fake ersetzt."""

import json
from datetime import datetime
from pathlib import Path

from tapesmith import cli, numbering, paths
from tapesmith.cli_cmds import disks as disks_cmd
from tapesmith.dataimport.batch import build_batch, commit_counters
from tapesmith.device.profile import load_profile
from tapesmith.sshscan import parse_output, rows_for_template
from tapesmith.templates.fill import CounterStore
from tapesmith.templates.model import template_from_dict

DATA = Path(__file__).parent / "data" / "ssh"

COUNTER_TEMPLATE = {
    "schema_version": 2, "name": "disks-counter-test", "description": "",
    "fields": [
        {"id": "host", "label": "Host", "type": "input"},
        {"id": "slot", "label": "Slot", "type": "input"},
        {"id": "sn", "label": "SN", "type": "input", "clean": "serial"},
        {"id": "nr", "label": "Nummer", "type": "counter", "format": "{:03d}"},
    ],
    "layout": {"lines": ["{host} {slot}", "{sn} {nr}"]},
}


def _fake_stdout() -> str:
    lsblk = (DATA / "pmx10-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "pmx10-byid.txt").read_text(encoding="utf-8")
    zpool = (DATA / "pmx10-zpool.txt").read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool


def _write_config(updates: dict) -> None:
    path = paths.config_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(updates)
    path.write_text(json.dumps(data), encoding="utf-8")


def _setup_host(tmp_path, monkeypatch, *, extra_cfg: dict | None = None):
    key = tmp_path / "id_ed25519_test"
    key.write_text("fake-key", encoding="utf-8")
    cfg = {"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root",
                              "key": str(key)}]}}
    if extra_cfg:
        cfg.update(extra_cfg)
    _write_config(cfg)

    def fake_runner(argv, timeout):
        return 0, _fake_stdout(), ""

    monkeypatch.setattr(disks_cmd, "RUNNER", fake_runner)
    return key


# 9. hosts / scan ------------------------------------------------------------------------------

def test_hosts_lists_configured_host(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["disks", "hosts"])
    out = capsys.readouterr().out
    assert code == 0
    assert "pmx10" in out


def test_scan_lists_rows_with_serial(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["disks", "scan", "pmx10"])
    out = capsys.readouterr().out
    assert code == 0
    assert "S5Y1NX0R123456" in out


def test_scan_json_is_parseable(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["disks", "scan", "pmx10", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert len(data) == 3
    assert {d["device"] for d in data} == {"sda", "sdb", "nvme0n1"}


# 10. print: --device/--slot/--dry-run, --preview, unbekanntes --device ------------------------

def test_print_dry_run_with_device_filter_and_slot(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["disks", "print", "pmx10", "--device", "sda,nvme0n1",
                     "--slot", "sda=SSD-1", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "2 Labels" in out


def test_print_preview_writes_png_without_printing(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    preview = tmp_path / "v.png"
    code = cli.main(["disks", "print", "pmx10", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()
    assert not (paths.app_dir() / "counters.json").exists()


def test_print_unknown_device_is_exit_1(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["disks", "print", "pmx10", "--device", "sdz", "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "sdz" in err


# 11. SshError -> Exit 5 -------------------------------------------------------------------------

def test_scan_permission_denied_is_exit_5_with_plain_text(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)

    def fake_runner(argv, timeout):
        return 255, "", "Permission denied (publickey)."

    monkeypatch.setattr(disks_cmd, "RUNNER", fake_runner)
    code = cli.main(["disks", "scan", "pmx10"])
    err = capsys.readouterr().err
    assert code == 5
    assert "Anmeldung abgelehnt" in err


def test_print_host_unreachable_is_exit_5(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)

    def fake_runner(argv, timeout):
        return 255, "", "Could not resolve hostname pmx10: Name or service not known"

    monkeypatch.setattr(disks_cmd, "RUNNER", fake_runner)
    code = cli.main(["disks", "print", "pmx10", "--dry-run"])
    err = capsys.readouterr().err
    assert code == 5
    assert "nicht erreichbar" in err


# 11a. Zentrale Zähler ---------------------------------------------------------------------

def test_print_dry_run_uses_central_counter_store_once_and_shares_instance_with_build_batch(
        app_home, tmp_path, monkeypatch):
    _setup_host(tmp_path, monkeypatch, extra_cfg={"numbering": {"dir": str(tmp_path / "zentral")}})

    real_counter_store = numbering.counter_store
    calls: list[dict] = []

    def spy_counter_store(cfg):
        store = real_counter_store(cfg)
        calls.append({"cfg": cfg, "store": store})
        return store

    monkeypatch.setattr(disks_cmd.numbering, "counter_store", spy_counter_store)

    real_build_batch = disks_cmd.build_batch
    build_batch_stores = []

    def spy_build_batch(*args, **kwargs):
        build_batch_stores.append(kwargs.get("counters"))
        return real_build_batch(*args, **kwargs)

    monkeypatch.setattr(disks_cmd, "build_batch", spy_build_batch)

    code = cli.main(["disks", "print", "pmx10", "--dry-run"])
    assert code == 0

    assert len(calls) == 1
    assert calls[0]["cfg"].get("numbering", {}).get("dir") == str(tmp_path / "zentral")
    store = calls[0]["store"]
    assert build_batch_stores == [store]
    assert store.path == tmp_path / "zentral" / "counters.json"


def test_print_commits_counters_to_central_store_matching_reference_run(app_home, tmp_path, monkeypatch):
    _setup_host(tmp_path, monkeypatch, extra_cfg={"numbering": {"dir": str(tmp_path / "zentral")}})
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)

    tpl_path = tmp_path / "disks-counter-test.tapesmith.json"
    tpl_path.write_text(json.dumps(COUNTER_TEMPLATE), encoding="utf-8")

    job = tmp_path / "out.bin"
    code = cli.main(["--transport", f"file:{job}", "disks", "print", "pmx10",
                     "--template", str(tpl_path), "--yes"])
    assert code == 0
    assert job.exists() and job.stat().st_size > 0

    central_counters = tmp_path / "zentral" / "counters.json"
    assert central_counters.exists()
    assert not (paths.app_dir() / "counters.json").exists()

    # Referenzlauf: gleicher Ablauf (build_batch + commit_counters) mit frischem Store.
    disks = parse_output("pmx10", _fake_stdout())
    rows = rows_for_template(disks)
    template = template_from_dict(COUNTER_TEMPLATE)
    ref_store = CounterStore(tmp_path / "ref" / "counters.json")
    plan = build_batch(template, rows, load_profile(), now=datetime.now(), counters=ref_store)
    commit_counters(plan, ref_store)

    assert json.loads(central_counters.read_text(encoding="utf-8")) == json.loads(
        (tmp_path / "ref" / "counters.json").read_text(encoding="utf-8"))
