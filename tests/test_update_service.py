"""`UpdateService` mit `file:`-Quelle in tmp_path, Testschlüssel, Fake-Runner und Fake-Spawn,
dazu Ende zu Ende bis zum Umschalten (Gesundheit über Fake) und der Qt-Freiheit des Pakets."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from tapesmith.install import junction, layout
from tapesmith.update import apply
from tapesmith.update import state as state_mod
from tapesmith.update.errors import UpdateError
from tapesmith.update.service import UpdateService
from update_fakes import FakeRun, install_layout, make_test_key, publish_dir

REPO_ROOT = Path(__file__).resolve().parent.parent


class Spawn:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return 99


class FakeDaemon:
    def __init__(self, busy=False, idle_since=0.0):
        self._busy = busy
        self._idle = idle_since

    def busy(self):
        return self._busy

    def idle_since(self):
        return self._idle


def _cfg(source: str, **update) -> dict:
    return {"update": {"source": source, "channel": "stable", "idle_min": 10, **update}}


def _service(tmp_path, *, installed=True, cfg=None, keys=None, run=None, clock=None, heartbeat=None,
             versions=("0.1.0",)):
    private, test_keys = make_test_key()
    feed = tmp_path / "feed"
    root = tmp_path / "root"
    if installed:
        install_layout(root, versions=versions)
    exe = root / "versions" / versions[-1] / "Tapesmith.exe" if installed else Path(sys.executable)
    spawn = Spawn()
    config = cfg if cfg is not None else _cfg(f"file:{feed}")
    svc = UpdateService(lambda: config, keys_loader=lambda: test_keys if keys is None else keys, root=root,
                        spawn=spawn, run=run or FakeRun(), now=lambda: datetime(2026, 10, 2, 8, 0, 0),
                        executable=str(exe), clock=clock or (lambda: 10_000.0),
                        heartbeat=heartbeat or (lambda: None), app_version=lambda: "0.1.0")
    return svc, private, feed, root, spawn


def test_nicht_installiert_status_und_install(tmp_path):
    svc, private, feed, _root, spawn = _service(tmp_path, installed=False)
    publish_dir(feed, "0.2.1", private)
    st = svc.status()
    assert st.installed is False and st.root is None and st.current == "0.1.0"
    assert st.can_rollback is False
    checked = svc.check()
    assert checked.available["version"] == "0.2.1"
    assert checked.state == "idle"
    for call in (lambda: svc.start_install("0.2.1"), lambda: svc.prepare("0.2.1"), svc.start_rollback):
        with pytest.raises(UpdateError) as info:
            call()
        assert info.value.code == "update.not_installed"
    assert spawn.calls == []


def test_installiert_check_prepare_start_install(tmp_path):
    svc, private, feed, root, spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private, notes="Viel Neues")
    assert svc.installed()
    st = svc.check()
    assert st.installed is True and st.current == "0.1.0" and st.root == str(root)
    assert st.available == {"version": "0.2.1", "notes": "Viel Neues", "published": "2026-10-01T12:00:00Z",
                            "size": (feed / "Tapesmith-portable-0.2.1.zip").stat().st_size}
    assert st.last_check == "2026-10-02T08:00:00"
    assert st.source == f"file:{feed}" and st.channel == "stable"

    target = svc.prepare("0.2.1")
    assert target == root / "versions" / "0.2.1"
    assert (target / "Tapesmith.exe").read_bytes() == b"neue-exe"
    assert not (root / "versions" / "0.2.1.staging").exists()
    assert list((root / "downloads").iterdir()) == []
    assert "0.2.1" in layout.read_state(root).versions
    assert svc.status().state == "ready"

    argv = svc.start_install("0.2.1", reopen_route="/einstellungen?abschnitt=updates")
    assert spawn.calls == [argv]
    assert argv[:5] == [str(root / "versions" / "0.1.0" / "Tapesmith.exe"), "--update-apply", "--version",
                        "0.2.1", "--root"]
    assert argv[-2:] == ["--reopen-route", "/einstellungen?abschnitt=updates"]
    assert svc.status().state == "installing"
    # state.json liegt im App-Verzeichnis und trägt die Felder, die die Tray-App liest
    import json

    saved = json.loads(state_mod.state_path().read_text(encoding="utf-8"))
    assert state_mod.state_path().parent.name == "update"
    assert saved["installed"] is True and saved["available"]["version"] == "0.2.1"
    assert saved["state"] == "installing"


def test_ende_zu_ende_file_quelle_bis_umschalten(tmp_path):
    svc, private, feed, root, spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private)
    svc.check()
    svc.prepare("0.2.1")
    argv = svc.start_install("0.2.1")
    version = argv[argv.index("--version") + 1]
    started = []
    result = apply.apply_update(version, root=Path(argv[argv.index("--root") + 1]), stopper=lambda: True,
                                lister=lambda: [], spawn=lambda a: started.append(a) or 1,
                                health=lambda: {"version": "0.2.1"}, sleep=lambda s: None, keep=2)
    assert result == "ok"
    assert junction.read_junction(layout.current_link(root)).name == "0.2.1"
    svc.executable = str(root / "versions" / "0.2.1" / "Tapesmith.exe")
    st = svc.status()
    assert st.current == "0.2.1" and st.previous == "0.1.0" and st.can_rollback is True
    assert st.available is None and st.state == "idle"
    rollback = svc.start_rollback()
    assert rollback[0] == str(root / "versions" / "0.2.1" / "Tapesmith.exe")
    assert "--rollback" in rollback


def test_kein_update_bei_gleicher_version_bzw_leerer_quelle(tmp_path):
    svc, private, feed, _root, _spawn = _service(tmp_path)
    feed.mkdir()
    assert svc.check().available is None
    publish_dir(feed, "0.1.0", private)
    assert svc.check().available is None


def test_failed_version_wird_nicht_angeboten(tmp_path):
    svc, private, feed, root, _spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private)
    st = layout.read_state(root)
    st.failed.append("0.2.1")
    layout.write_state(st, root)
    assert svc.check().available is None
    with pytest.raises(UpdateError, match="früher gescheitert"):
        svc.prepare("0.2.1")


def test_beta_nur_im_beta_kanal(tmp_path):
    svc, private, feed, _root, _spawn = _service(tmp_path)
    publish_dir(feed, "0.3.0-beta.1", private, channel="beta")
    assert svc.check().available is None
    svc.cfg_loader = lambda: _cfg(f"file:{feed}", channel="beta")
    assert svc.check().available["version"] == "0.3.0-beta.1"


def test_ohne_schluessel_kein_update(tmp_path):
    svc, private, feed, _root, _spawn = _service(tmp_path, keys=[])
    publish_dir(feed, "0.2.1", private)
    with pytest.raises(UpdateError) as info:
        svc.check()
    assert info.value.code == "update.no_trusted_key"
    st = svc.status()
    assert st.state == "failed" and st.error["code"] == "update.no_trusted_key"
    assert st.last_check == "2026-10-02T08:00:00"


def test_fremde_signatur_abgelehnt(tmp_path):
    svc, _private, feed, _root, _spawn = _service(tmp_path)
    other, _keys = make_test_key()
    publish_dir(feed, "0.2.1", other)
    with pytest.raises(UpdateError) as info:
        svc.check()
    assert info.value.code == "update.signature_invalid"


def test_veraendertes_zip_checksum_mismatch(tmp_path):
    svc, private, feed, root, _spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private, tamper_zip=True)
    svc.check()
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.2.1")
    assert info.value.code == "update.checksum_mismatch"
    assert not (root / "versions" / "0.2.1").exists()
    assert svc.status().error["code"] == "update.checksum_mismatch"


def test_selbsttest_scheitert_version_failed(tmp_path):
    svc, private, feed, root, _spawn = _service(tmp_path, run=FakeRun("Selbsttest fehlgeschlagen"))
    publish_dir(feed, "0.2.1", private)
    svc.check()
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.2.1")
    assert info.value.code == "update.apply_failed"
    assert not (root / "versions" / "0.2.1.staging").exists()
    assert "0.2.1" in layout.read_state(root).failed


def test_prepare_ohne_vorherigen_check_und_bereits_bereit(tmp_path):
    svc, private, feed, _root, _spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private)
    run = FakeRun()
    svc.run = run
    svc.prepare("0.2.1")
    assert len(run.calls) == 1
    svc.prepare("0.2.1")
    assert len(run.calls) == 1
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.9.0")
    assert info.value.code == "update.download_failed"


def test_start_install_ohne_bereitstellung_und_rollback_ohne_vorige(tmp_path):
    svc, *_ = _service(tmp_path)
    with pytest.raises(UpdateError, match="nicht bereitgestellt"):
        svc.start_install("0.2.1")
    with pytest.raises(UpdateError, match="Keine vorige"):
        svc.start_rollback()


def test_quelle_nicht_erreichbar(tmp_path):
    svc, *_ = _service(tmp_path, cfg=_cfg(f"file:{tmp_path / 'gibtsnicht'}"))
    with pytest.raises(UpdateError) as info:
        svc.check()
    assert info.value.code == "update.source_unreachable"


def test_idle_ok_regeln(tmp_path):
    now = 10_000.0
    beat = {"t": None}
    svc, *_ = _service(tmp_path, clock=lambda: now, heartbeat=lambda: beat["t"])
    assert svc.idle_ok(None) is False
    assert svc.idle_ok(FakeDaemon(busy=True)) is False
    assert svc.idle_ok(FakeDaemon(idle_since=None)) is False
    assert svc.idle_ok(FakeDaemon(idle_since=now - 9 * 60)) is False
    assert svc.idle_ok(FakeDaemon(idle_since=now - 11 * 60)) is True
    beat["t"] = now - 30
    assert svc.idle_ok(FakeDaemon(idle_since=now - 11 * 60)) is False
    beat["t"] = now - 121
    assert svc.idle_ok(FakeDaemon(idle_since=now - 11 * 60)) is True
    assert svc.status(FakeDaemon(idle_since=now - 11 * 60)).idle_ok is True


def test_update_paket_importiert_kein_qt():
    modules = ["tapesmith.update", "tapesmith.update.errors", "tapesmith.update.manifest",
               "tapesmith.update.signing", "tapesmith.update.sources", "tapesmith.update.download",
               "tapesmith.update.stage", "tapesmith.update.apply", "tapesmith.update.service",
               "tapesmith.update.state", "tapesmith.automation.update", "tapesmith.webapi.routes_update",
               "tapesmith.cli_cmds.update"]
    code = "\n".join(f"import {m}" for m in modules) + "\nimport sys\nprint('PySide6' in sys.modules)\n"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(REPO_ROOT), capture_output=True,
                            text=True, check=True)
    assert result.stdout.strip() == "False", result.stdout + result.stderr


# ---------- Addon ----------

class FakeUpdateService:
    def __init__(self, available=None, idle=False, installed=True):
        self.available = available
        self.idle = idle
        self._installed = installed
        self.calls: list[tuple] = []

    def installed(self):
        return self._installed

    def check(self):
        self.calls.append(("check",))
        return state_mod.UpdateStatus(available=self.available)

    def prepare(self, version):
        self.calls.append(("prepare", version))

    def idle_ok(self, service):
        self.calls.append(("idle_ok",))
        return self.idle

    def start_install(self, version):
        self.calls.append(("start_install", version))

    def status(self):
        return state_mod.UpdateStatus(state="ready")


class AddonFacade:
    service = FakeDaemon()

    def config(self):
        return {}


def test_addon_create_none_bei_aus_bzw_nicht_installiert():
    from tapesmith.automation import update as addon_mod

    assert addon_mod.create(AddonFacade(), {"update": {"enabled": False}}) is None
    not_installed = FakeUpdateService(installed=False)
    assert addon_mod.create(AddonFacade(), {}, service_factory=lambda loader: not_installed) is None
    # unter pytest ohne TAPESMITH_INSTALL_ROOT: nicht installiert
    assert addon_mod.create(AddonFacade(), {}) is None
    # Standard: aus, bis der Benutzer der automatischen Prüfung zustimmt (keine Verbindung ohne Zustimmung)
    assert addon_mod.create(AddonFacade(), {}, service_factory=lambda loader: FakeUpdateService()) is None
    addon = addon_mod.create(AddonFacade(), {"update": {"enabled": True}},
                             service_factory=lambda loader: FakeUpdateService())
    assert addon is not None and addon.name == "update"


def test_rueckfrage_nur_installiert_unentschieden_und_aus(tmp_path):
    feed = tmp_path / "feed"
    svc, *_ = _service(tmp_path, cfg=_cfg(f"file:{feed}"))
    st = svc.status()
    assert st.enabled is False and st.consent_needed is True
    for update in ({"asked": True}, {"enabled": True}, {"enabled": False, "asked": True}):
        svc, *_ = _service(tmp_path / str(len(update)) / str(sorted(update.items())), cfg=_cfg(f"file:{feed}", **update))
        assert svc.status().consent_needed is False, update
    portable, *_ = _service(tmp_path / "portabel", installed=False, cfg=_cfg(f"file:{feed}"))
    assert portable.status().consent_needed is False


def test_addon_pruefung_nach_5_min_installation_erst_im_leerlauf():
    from tapesmith.automation.update import UpdateAddon

    clock = {"t": 0.0}
    svc = FakeUpdateService(available={"version": "0.2.1"})
    addon = UpdateAddon(AddonFacade(), {"update": {"auto_install": True, "check_interval_h": 24}}, svc,
                        clock=lambda: clock["t"])
    addon.tick()
    clock["t"] = 299.0
    addon.tick()
    assert svc.calls == []
    clock["t"] = 300.0
    addon.tick()
    assert svc.calls == [("check",), ("prepare", "0.2.1"), ("idle_ok",)]
    clock["t"] = 330.0
    addon.tick()
    assert svc.calls.count(("idle_ok",)) == 1  # höchstens alle 60 s
    clock["t"] = 360.0
    svc.idle = True
    addon.tick()
    assert svc.calls[-1] == ("start_install", "0.2.1")
    assert addon.status()["name"] == "update" and addon.status()["state"] == "ready"
    clock["t"] = 300.0 + 24 * 3600
    addon.tick()
    assert svc.calls.count(("check",)) == 2


def test_addon_ohne_auto_install_nur_pruefen():
    from tapesmith.automation.update import UpdateAddon

    clock = {"t": 0.0}
    svc = FakeUpdateService(available={"version": "0.2.1"})
    addon = UpdateAddon(AddonFacade(), {}, svc, clock=lambda: clock["t"])
    addon.tick()
    clock["t"] = 301.0
    addon.tick()
    assert svc.calls == [("check",)]
    assert "0.2.1" in addon.status()["detail"]


def test_addon_thread_start_stop():
    from tapesmith.automation.update import UpdateAddon

    addon = UpdateAddon(AddonFacade(), {}, FakeUpdateService(), poll_s=0.01)
    addon.start()
    assert addon.status()["running"] is True
    addon.stop()
    assert addon.status()["running"] is False
