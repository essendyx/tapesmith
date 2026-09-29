"""CLI-Integration `p12 platte`: `status`/`plan`/`label`, `SshError` -> Exit 5.

Kein echter SSH-Aufruf: `RUNNER` wird durch einen Fake ersetzt (Muster `test_cli_disks.py`).
"""

import json
from pathlib import Path

from tapesmith import cli, paths
from tapesmith.cli_cmds import platte as platte_cmd

DATA = Path(__file__).parent / "data" / "zfs"


def _fake_stdout(zpool: str) -> str:
    lsblk = (DATA / "degraded-lsblk.json").read_text(encoding="utf-8")
    byid = (DATA / "degraded-byid.txt").read_text(encoding="utf-8")
    zpool_text = (DATA / zpool).read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool_text


DEGRADED_STDOUT = _fake_stdout("degraded-zpool.txt")
OLD_NAME = "/dev/disk/by-id/ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456-part3"


def _write_config(updates: dict) -> None:
    path = paths.config_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(updates)
    path.write_text(json.dumps(data), encoding="utf-8")


def _setup_host(tmp_path, monkeypatch, *, stdout: str = DEGRADED_STDOUT):
    key = tmp_path / "id_ed25519_test"
    key.write_text("fake-key", encoding="utf-8")
    cfg = {"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root", "key": str(key)}]}}
    _write_config(cfg)

    def fake_runner(argv, timeout):
        return 0, stdout, ""

    monkeypatch.setattr(platte_cmd, "RUNNER", fake_runner)
    return key


def test_status_listet_faulted_und_sdc(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    code = cli.main(["platte", "status", "pmx10"])
    out = capsys.readouterr().out
    assert code == 0
    assert "FAULTED" in out
    assert "sdc" in out


def test_plan_mit_changelog_schreibt_datei(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    changelog = tmp_path / "f.md"
    code = cli.main(["platte", "plan", "pmx10", "--alt", OLD_NAME, "--neu", "sdc",
                     "--slot", "SSD-1", "--changelog", str(changelog)])
    out = capsys.readouterr().out
    assert code == 0
    assert "zpool replace rpool" in out
    assert changelog.is_file()
    assert "[[Hosts/pmx10]]" in changelog.read_text(encoding="utf-8")


def test_label_preview_erzeugt_zwei_pngs(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    preview = tmp_path / "p.png"
    code = cli.main(["platte", "label", "pmx10", "--alt", OLD_NAME, "--neu", "sdc",
                     "--slot", "SSD-1", "--preview", str(preview)])
    err = capsys.readouterr().err
    assert code == 0
    assert (tmp_path / "p-alt.png").is_file()
    assert (tmp_path / "p-neu.png").is_file()
    assert not preview.is_file()
    assert "nicht eingebbar" not in err


def test_label_nur_alt_mit_datum(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)
    preview = tmp_path / "p.png"
    code = cli.main(["platte", "label", "pmx10", "--alt", OLD_NAME, "--neu", "sdc",
                     "--slot", "SSD-1", "--nur", "alt", "--datum", "01.10.2026", "--preview", str(preview)])
    assert code == 0
    assert (tmp_path / "p-alt.png").is_file()
    assert not (tmp_path / "p-neu.png").exists()


def test_ssh_fehler_ist_exit_5(app_home, tmp_path, monkeypatch, capsys):
    _setup_host(tmp_path, monkeypatch)

    def fake_runner(argv, timeout):
        return 255, "", "Permission denied (publickey)."

    monkeypatch.setattr(platte_cmd, "RUNNER", fake_runner)
    code = cli.main(["platte", "status", "pmx10"])
    err = capsys.readouterr().err
    assert code == 5
    assert "Anmeldung abgelehnt" in err
