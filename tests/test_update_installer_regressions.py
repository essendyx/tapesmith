"""Regressionstests für Update, Installer und Deinstallation.

Nur Temp-Ordner und Fakes: nie echte Registry, echtes Startmenü, echte Prozesse oder
`%APPDATA%\\Tapesmith` (TAPESMITH_HOME kommt aus der autouse-Fixture `app_home`)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tapesmith.install import installer, junction, layout, processes, uninstaller
from tapesmith.install.shortcuts import FakeShortcuts
from tapesmith.update import apply, stage
from tapesmith.update import state as state_mod
from tapesmith.update.errors import UpdateError
from test_update_apply import Env, _current, _root
from test_update_service import AddonFacade, FakeUpdateService, _service
from update_fakes import FakeRun, publish_dir


def _make_source(tmp_path: Path, name: str = "source", content: bytes = b"exe") -> Path:
    src = tmp_path / name
    src.mkdir()
    (src / layout.APP_EXE).write_bytes(content)
    return src


@pytest.fixture
def no_processes(monkeypatch):
    """Keine echten Prozesse auflisten oder beenden."""
    monkeypatch.setattr(uninstaller.processes, "processes_under", lambda root, **kw: [])


# ---------- Deinstallation: Pfadprüfung ----------

def test_deinstallation_verweigert_ordner_ohne_installation(tmp_path, no_processes):
    root = tmp_path / "Dokumente"
    root.mkdir()
    (root / "wichtig.txt").write_text("nicht löschen", encoding="utf-8")
    scheduled: list[Path] = []
    with pytest.raises(ValueError, match="keine Tapesmith-Installation"):
        uninstaller.uninstall(root=root, stopper=lambda r: True, schedule_delete=scheduled.append)
    assert scheduled == []
    assert (root / "wichtig.txt").exists()


def test_deinstallation_verweigert_laufwerkswurzel(tmp_path, no_processes):
    scheduled: list[Path] = []
    with pytest.raises(ValueError):
        uninstaller.uninstall(root=Path(tmp_path.anchor), stopper=lambda r: True,
                              schedule_delete=scheduled.append)
    assert scheduled == []


def test_deinstallation_verweigert_benutzerdaten_ordner(tmp_path, app_home, no_processes):
    app_home.mkdir(parents=True, exist_ok=True)
    layout.write_state(layout.InstallState(current="0.2.0", versions=["0.2.0"]), app_home)
    scheduled: list[Path] = []
    with pytest.raises(ValueError, match="Benutzerdaten"):
        uninstaller.uninstall(root=app_home, stopper=lambda r: True, schedule_delete=scheduled.append)
    assert scheduled == []


def test_deinstallation_verweigert_wurzel_ueber_den_benutzerdaten(tmp_path, monkeypatch, no_processes):
    root = tmp_path / "Programs" / "Tapesmith"
    home = root / "daten"
    home.mkdir(parents=True)
    monkeypatch.setenv("TAPESMITH_HOME", str(home))
    layout.write_state(layout.InstallState(current="0.2.0", versions=["0.2.0"]), root)
    scheduled: list[Path] = []
    with pytest.raises(ValueError, match="Benutzerdaten"):
        uninstaller.uninstall(root=root, stopper=lambda r: True, schedule_delete=scheduled.append)
    assert scheduled == []


def test_deinstallation_verweigert_wurzel_innerhalb_der_benutzerdaten(tmp_path, app_home, no_processes):
    root = app_home / "Programs" / "Tapesmith"
    layout.write_state(layout.InstallState(current="0.2.0", versions=["0.2.0"]), root)
    with pytest.raises(ValueError, match="Benutzerdaten"):
        uninstaller.uninstall(root=root, stopper=lambda r: True, schedule_delete=lambda r: None)


def test_deinstallation_verweigert_benutzerprofil(tmp_path, monkeypatch, no_processes):
    profile = tmp_path / "Profil"
    monkeypatch.setenv("USERPROFILE", str(profile))
    layout.write_state(layout.InstallState(current="0.2.0", versions=["0.2.0"]), profile)
    with pytest.raises(ValueError):
        uninstaller.uninstall(root=profile, stopper=lambda r: True, schedule_delete=lambda r: None)


def test_deinstallation_main_meldet_ungueltige_wurzel(tmp_path, no_processes):
    root = tmp_path / "leer"
    root.mkdir()
    scheduled: list[Path] = []
    code = uninstaller.main(["--root", str(root), "--no-shortcuts", "--no-registry"],
                            schedule_delete=scheduled.append)
    assert code == 1
    assert scheduled == []
    from tapesmith import paths

    assert "fehlgeschlagen" in (paths.log_dir() / "uninstall.log").read_text(encoding="utf-8")


# ---------- Deinstallation: Prozesse, Reihenfolge, Startmenü ----------

def test_deinstallation_bricht_ab_wenn_prozesse_nicht_enden(tmp_path, monkeypatch):
    menu = tmp_path / "startmenue"
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    root = tmp_path / "root"
    shortcuts = FakeShortcuts()
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, shortcuts=shortcuts, start=False)
    fake = processes.ProcessInfo(pid=99999, exe=str(root / "current" / layout.APP_EXE))
    monkeypatch.setattr(uninstaller.processes, "processes_under", lambda r, **kw: [fake])
    scheduled: list[Path] = []
    with pytest.raises(RuntimeError, match="läuft noch"):
        uninstaller.uninstall(root=root, shortcuts=shortcuts, stopper=lambda r: False,
                              schedule_delete=scheduled.append)
    assert scheduled == []
    assert junction.read_junction(layout.current_link(root)) is not None
    assert shortcuts.exists(menu / "Tapesmith.lnk")


def test_deinstallation_loescht_erst_nach_dem_log(tmp_path, monkeypatch, no_processes):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, start=False)
    events: list[str] = []
    monkeypatch.setattr(uninstaller, "_log_result", lambda text, ok: events.append("log"))
    code = uninstaller.main(["--root", str(root), "--no-shortcuts", "--no-registry"],
                            schedule_delete=lambda r: events.append("loeschen"))
    assert code == 0
    assert events == ["log", "loeschen"]


def test_deinstallation_quiet_loescht_ohne_meldung(tmp_path, no_processes):
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, start=False)
    scheduled: list[Path] = []
    code = uninstaller.main(["--root", str(root), "--no-shortcuts", "--no-registry", "--quiet"],
                            schedule_delete=scheduled.append)
    assert code == 0
    assert scheduled == [root]


def test_deinstallation_entfernt_leeren_startmenue_ordner(tmp_path, monkeypatch, no_processes):
    menu = tmp_path / "startmenue" / "Tapesmith"
    menu.mkdir(parents=True)
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    root = tmp_path / "root"
    shortcuts = FakeShortcuts()
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, shortcuts=shortcuts, start=False)
    uninstaller.uninstall(root=root, shortcuts=shortcuts, stopper=lambda r: True, schedule_delete=lambda r: None)
    assert not menu.exists()


def test_deinstallation_laesst_fremde_dateien_im_startmenue(tmp_path, monkeypatch, no_processes):
    menu = tmp_path / "startmenue" / "Tapesmith"
    menu.mkdir(parents=True)
    (menu / "fremd.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    root = tmp_path / "root"
    shortcuts = FakeShortcuts()
    installer.install(_make_source(tmp_path), version="0.2.0", root=root, shortcuts=shortcuts, start=False)
    uninstaller.uninstall(root=root, shortcuts=shortcuts, stopper=lambda r: True, schedule_delete=lambda r: None)
    assert (menu / "fremd.txt").exists()


# ---------- Installer: vorige Version bleibt bei Neuinstallation derselben Version ----------

def test_neuinstallation_gleicher_version_behaelt_vorige(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.processes, "processes_under", lambda root, **kw: [])
    root = tmp_path / "root"
    installer.install(_make_source(tmp_path, "v1"), version="0.1.0", root=root, start=False)
    installer.install(_make_source(tmp_path, "v2"), version="0.2.0", root=root, start=False)
    assert layout.read_state(root).previous == "0.1.0"
    installer.install(_make_source(tmp_path, "v2b"), version="0.2.0", root=root, start=False)
    st = layout.read_state(root)
    assert (st.current, st.previous) == ("0.2.0", "0.1.0")


# ---------- Update: kein Downgrade, kein fremder Kanal ----------

def test_prepare_verweigert_aeltere_signierte_version(tmp_path):
    svc, private, feed, root, spawn = _service(tmp_path, versions=("0.2.0",))
    publish_dir(feed, "0.1.5", private)  # gültig signiert, aber älter (Replay)
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.1.5")
    assert info.value.code == "update.apply_failed"
    assert not layout.version_dir("0.1.5", root).exists()
    assert "0.1.5" not in layout.read_state(root).versions
    assert svc.status().state == "failed"


def test_install_verweigert_downgrade_auf_bereits_vorhandene_version(tmp_path):
    svc, private, feed, root, spawn = _service(tmp_path, versions=("0.1.0", "0.2.0"))
    assert layout.read_state(root).current == "0.2.0"
    publish_dir(feed, "0.1.0", private)
    with pytest.raises(UpdateError):
        svc.prepare("0.1.0")
    with pytest.raises(UpdateError):
        svc.start_install("0.1.0")
    assert spawn.calls == []
    assert (layout.version_dir("0.1.0", root) / layout.APP_EXE).read_bytes() == b"exe 0.1.0"


def test_prepare_verweigert_beta_im_stabilen_kanal(tmp_path):
    svc, private, feed, root, spawn = _service(tmp_path)
    publish_dir(feed, "0.3.0", private, channel="beta")
    with pytest.raises(UpdateError):
        svc.prepare("0.3.0")
    assert not layout.version_dir("0.3.0", root).exists()


# ---------- Update: Fehlerpfade ohne halbes Layout ----------

def test_prepare_dateifehler_hinterlaesst_kein_halbes_layout(tmp_path, monkeypatch):
    svc, private, feed, root, spawn = _service(tmp_path)
    publish_dir(feed, "0.2.1", private)
    svc.check()

    def boom(staging, version, root_):
        raise PermissionError("Zugriff verweigert (Virenscanner)")

    monkeypatch.setattr(stage, "finalize", boom)
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.2.1")
    assert info.value.code == "update.apply_failed"
    assert not stage.staging_dir("0.2.1", root).exists()
    assert not layout.version_dir("0.2.1", root).exists()
    assert list((root / "downloads").iterdir()) == []
    status = svc.status()
    assert status.state == "failed" and status.error["code"] == "update.apply_failed"


def test_prepare_parallel_nur_einmal(tmp_path):
    """API-Knopf und Addon haben je einen eigenen `UpdateService`: zwei gleichzeitige
    Bereitstellungen derselben Version dürfen sich den Staging-Ordner nicht gegenseitig löschen."""
    in_smoke = threading.Event()
    release = threading.Event()

    class BlockingRun(FakeRun):
        def __call__(self, argv, env=None, timeout=None):
            in_smoke.set()
            release.wait(10)
            return super().__call__(argv, env=env, timeout=timeout)

    run_a = BlockingRun()
    svc_a, private, feed, root, _spawn = _service(tmp_path, run=run_a)
    publish_dir(feed, "0.2.1", private)
    run_b = FakeRun()
    svc_b = type(svc_a)(svc_a.cfg_loader, keys_loader=svc_a.keys_loader, root=root, spawn=svc_a.spawn,
                        run=run_b, now=svc_a.now, executable=svc_a.executable, clock=svc_a.clock,
                        heartbeat=svc_a.heartbeat, app_version=svc_a.app_version)
    errors: list[BaseException] = []

    def work(svc):
        try:
            svc.prepare("0.2.1")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t_a = threading.Thread(target=work, args=(svc_a,))
    t_a.start()
    assert in_smoke.wait(10)
    t_b = threading.Thread(target=work, args=(svc_b,))
    t_b.start()
    t_b.join(0.5)
    b_ran_meanwhile = bool(run_b.calls)
    release.set()
    t_a.join(10)
    t_b.join(10)
    assert not b_ran_meanwhile
    assert errors == []
    assert run_b.calls == []  # B fand die fertige Version vor
    assert (layout.version_dir("0.2.1", root) / layout.APP_EXE).read_bytes() == b"neue-exe"
    assert not stage.staging_dir("0.2.1", root).exists()


def test_apply_unerwarteter_fehler_startet_alte_version_wieder(tmp_path):
    root = _root(tmp_path)
    env = Env(root, health_version="0.2.0")

    def lister():
        raise OSError("EnumProcesses fehlgeschlagen")

    deps = env.deps()
    deps["lister"] = lister
    result = apply.apply_update("0.2.0", root=root, **deps)
    assert result == apply.RESULT_ROLLED_BACK
    assert _current(root) == "0.1.0"
    exe = str(layout.current_exe(root))
    assert [exe, "--daemon"] in env.spawned and [exe, "--tray"] in env.spawned
    status = state_mod.load_status()
    assert status.state == "failed" and status.error["code"] == "update.apply_failed"


def test_apply_main_unerwarteter_fehler_zustand_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "MUTEX_NAME", f"Local\\Tapesmith.Update.Review.{id(tmp_path)}")
    root = _root(tmp_path)
    (root / "install.json").write_text("{kaputt", encoding="utf-8")
    env = Env(root, health_version="0.2.0")
    assert apply.main(["--version", "0.2.0", "--root", str(root)], **env.deps()) == 1
    status = state_mod.load_status()
    assert status.state == "failed" and status.error["code"] == "update.apply_failed"


# ---------- Update: keine automatische Neuinstallation nach Rückstellung ----------

class RolledBackService(FakeUpdateService):
    def check(self):
        self.calls.append(("check",))
        return state_mod.UpdateStatus(available=self.available, previous="0.2.0", current="0.1.0")


def test_addon_installiert_zurueckgestellte_version_nicht_automatisch():
    from tapesmith.automation.update import UpdateAddon

    clock = {"t": 0.0}
    svc = RolledBackService(available={"version": "0.2.0"}, idle=True)
    addon = UpdateAddon(AddonFacade(), {"update": {"auto_install": True}}, svc, clock=lambda: clock["t"])
    addon.tick()
    clock["t"] = 300.0
    addon.tick()
    clock["t"] = 400.0
    addon.tick()
    assert ("check",) in svc.calls
    assert not any(call[0] in ("prepare", "start_install") for call in svc.calls)
    assert "0.2.0" in addon.status()["detail"]


def test_addon_neuere_version_nach_rueckstellung_weiter_automatisch():
    from tapesmith.automation.update import UpdateAddon

    clock = {"t": 0.0}
    svc = RolledBackService(available={"version": "0.3.0"}, idle=True)
    addon = UpdateAddon(AddonFacade(), {"update": {"auto_install": True}}, svc, clock=lambda: clock["t"])
    addon.tick()
    clock["t"] = 300.0
    addon.tick()
    assert ("prepare", "0.3.0") in svc.calls



# ---------- Update: unerwartete Fehler der Quelle lassen den Zustand nicht hängen ----------

def _loop_transport():
    import httpx

    def handler(request):
        return httpx.Response(302, headers={"Location": str(request.url)})

    return httpx.MockTransport(handler)


def test_url_quelle_endlose_weiterleitung_ist_update_error(tmp_path, monkeypatch):
    import httpx

    from tapesmith.update.sources import UrlSource

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda self, request: pytest.fail(f"echtes Netz: {request.url}"))
    src = UrlSource("https://updates.invalid/", transport=_loop_transport())
    with pytest.raises(UpdateError) as info:
        src.fetch_manifest()
    assert info.value.code == "update.source_unreachable"
    with pytest.raises(UpdateError) as info:
        src.download("x.zip", tmp_path / "x.zip")
    assert info.value.code == "update.download_failed"
    assert not (tmp_path / "x.zip.part").exists()


def test_check_github_ohne_token_mit_altem_eintrag(tmp_path, monkeypatch):
    """Ein alter `update.token_ref` in config.json wird ignoriert: GitHub wird ohne Token abgefragt."""
    import httpx

    from tapesmith.update.service import UpdateService

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda self, request: pytest.fail(f"echtes Netz: {request.url}"))
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404, json={"message": "Not Found"})

    cfg = {"update": {"source": "github:essendyx/tapesmith", "token_ref": "keyring:tapesmith/github"}}
    svc = UpdateService(lambda: cfg, keys_loader=lambda: [], root=tmp_path / "root",
                        transport=httpx.MockTransport(handler),
                        executable=str(tmp_path / "python.exe"), app_version=lambda: "0.1.0")
    with pytest.raises(UpdateError) as info:
        svc.check()
    assert info.value.code == "update.source_unreachable"
    assert seen and all("Authorization" not in r.headers for r in seen)
    assert svc.status().state == "failed"


def test_check_unerwarteter_fehler_zustand_failed(tmp_path):
    from tapesmith.update.service import UpdateService

    class KaputteQuelle:
        description = "kaputt"

        def fetch_manifest(self):
            raise RuntimeError("unerwartet")

    svc = UpdateService(lambda: {}, source_factory=lambda *a, **kw: KaputteQuelle(), root=tmp_path / "root",
                        executable=str(tmp_path / "python.exe"), app_version=lambda: "0.1.0")
    with pytest.raises(UpdateError) as info:
        svc.check()
    assert info.value.code == "update.source_unreachable"
    status = svc.status()
    assert status.state == "failed" and status.error["code"] == "update.source_unreachable"
