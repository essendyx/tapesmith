"""`python -m tapesmith.update.apply` gegen ein Installationslayout in tmp_path (Junction nur dort), alle Prozesse,
Starts und Gesundheitsprüfungen über Fakes. Nie echte Prozesse dieses PCs."""

from __future__ import annotations

import pytest

from tapesmith.daemon.instance import SingleInstance
from tapesmith.install import junction, layout
from tapesmith.install.processes import ProcessInfo
from tapesmith.update import apply
from tapesmith.update import state as state_mod
from tapesmith.update.errors import UpdateError
from update_fakes import install_layout, make_version


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class Env:
    def __init__(self, root, *, health_version=None, stopper_results=None, procs=None, kill_ok=True):
        self.root = root
        self.clock = Clock()
        self.spawned: list[list[str]] = []
        self.killed: list[int] = []
        self.pruned: list[int] = []
        self.health_version = health_version
        self.stopper_results = list(stopper_results or [True])
        self.procs = procs if procs is not None else []
        self.kill_ok = kill_ok
        self.stopper_calls = 0

    def stopper(self):
        self.stopper_calls += 1
        return self.stopper_results.pop(0) if len(self.stopper_results) > 1 else self.stopper_results[0]

    def lister(self):
        return list(self.procs)

    def killer(self, pid, timeout_s):
        self.killed.append(pid)
        return self.kill_ok

    def spawn(self, argv):
        self.spawned.append(list(argv))
        return 4242

    def health(self):
        if self.health_version is None:
            return None
        return {"ok": True, "app": "tapesmith", "version": self.health_version}

    def pruner(self, keep, *, root):
        self.pruned.append(keep)
        return []

    def deps(self):
        return dict(stopper=self.stopper, lister=self.lister, killer=self.killer, spawn=self.spawn,
                    health=self.health, clock=self.clock, sleep=self.clock.sleep, keep=2, pruner=self.pruner)


def _root(tmp_path):
    """0.1.0 aktiv (ohne vorige), 0.2.0 bereitgestellt wie nach `venv.provision` und `register_version`."""
    root = install_layout(tmp_path / "root", versions=("0.1.0",))
    make_version(root, "0.2.0")
    st = layout.read_state(root)
    st.versions.append("0.2.0")
    layout.write_state(st, root)
    return root


def _current(root):
    return junction.read_junction(layout.current_link(root)).name


def _exe(root):
    return str(layout.current_pythonw(root))


DAEMON = ["-m", "tapesmith.daemon"]
TRAY = ["-m", "tapesmith.gui.tray"]


def test_erfolg_schaltet_um_prunt_und_oeffnet_fenster(tmp_path):
    root = _root(tmp_path)
    env = Env(root, health_version="0.2.0",
              procs=[ProcessInfo(pid=77, exe=str(root / "versions" / "0.1.0" / "Scripts" / "pythonw.exe"))])
    result = apply.apply_update("0.2.0", root=root, reopen_route="/einstellungen?abschnitt=updates", **env.deps())
    assert result == "ok"
    assert _current(root) == "0.2.0"
    st = layout.read_state(root)
    assert (st.current, st.previous, st.failed) == ("0.2.0", "0.1.0", [])
    assert env.pruned == [2]
    assert env.killed == [77]
    assert env.spawned == [[_exe(root), *DAEMON], [_exe(root), *TRAY],
                           [_exe(root), "-m", "tapesmith.webui.browser", "--route", "/einstellungen?abschnitt=updates"]]
    status = state_mod.load_status()
    assert status.state == "idle" and status.error is None


@pytest.mark.parametrize("health_version", [None, "0.1.0"])
def test_ungesund_rueckfall_auf_alt(tmp_path, health_version):
    root = _root(tmp_path)
    env = Env(root, health_version=health_version)
    result = apply.apply_update("0.2.0", root=root, **env.deps())
    assert result == "rolled_back"
    assert _current(root) == "0.1.0"
    st = layout.read_state(root)
    assert st.current == "0.1.0"
    assert "0.2.0" in st.failed
    assert st.previous is None  # vorige Angabe bleibt wie vor dem Versuch
    # neu gestartet (Dienst, Tray), dann nach dem Rückfall die alten wieder
    assert env.spawned.count([_exe(root), *DAEMON]) == 2
    assert env.spawned[-1] == [_exe(root), *TRAY]
    assert env.pruned == []
    status = state_mod.load_status()
    assert status.state == "failed"
    assert status.error["code"] == "update.apply_failed"
    # Gesundheitsprüfung hat 60 s gewartet
    assert env.clock.t >= 1000.0 + apply.HEALTH_TIMEOUT_S


def test_dienst_belegt_busy_nichts_umgestellt(tmp_path):
    root = _root(tmp_path)
    env = Env(root, stopper_results=[False], health_version="0.2.0")
    result = apply.apply_update("0.2.0", root=root, **env.deps())
    assert result == "busy"
    assert _current(root) == "0.1.0"
    assert env.spawned == []
    assert env.stopper_calls > 1
    assert env.clock.t >= 1000.0 + apply.BUSY_WAIT_S
    status = state_mod.load_status()
    assert status.state == "ready" and status.error["code"] == "update.busy"


def test_dienst_zuerst_belegt_dann_frei(tmp_path):
    root = _root(tmp_path)
    env = Env(root, stopper_results=[False, False, True], health_version="0.2.0")
    assert apply.apply_update("0.2.0", root=root, **env.deps()) == "ok"
    assert env.stopper_calls == 3


def test_prozesse_lassen_sich_nicht_beenden(tmp_path):
    root = _root(tmp_path)
    env = Env(root, health_version="0.2.0", kill_ok=False,
              procs=[ProcessInfo(pid=55, exe=str(root / "current" / "Scripts" / "pythonw.exe"))])
    assert apply.apply_update("0.2.0", root=root, **env.deps()) == "rolled_back"
    assert _current(root) == "0.1.0"
    assert layout.read_state(root).failed == []
    assert state_mod.load_status().state == "failed"


def test_rollback_stellt_auf_previous(tmp_path):
    root = install_layout(tmp_path / "root", versions=("0.1.0", "0.2.0"), current="0.2.0")
    env = Env(root, health_version="0.1.0")
    assert apply.apply_update(None, root=root, rollback=True, **env.deps()) == "ok"
    assert _current(root) == "0.1.0"
    st = layout.read_state(root)
    assert (st.current, st.previous) == ("0.1.0", "0.2.0")


def test_rollback_ungesund_bleibt_bei_aktueller(tmp_path):
    root = install_layout(tmp_path / "root", versions=("0.1.0", "0.2.0"), current="0.2.0")
    env = Env(root, health_version=None)
    assert apply.apply_update(None, root=root, rollback=True, **env.deps()) == "rolled_back"
    st = layout.read_state(root)
    assert (st.current, st.previous, st.failed) == ("0.2.0", "0.1.0", [])


def test_fehlerfaelle(tmp_path):
    env = Env(tmp_path)
    with pytest.raises(UpdateError) as info:
        apply.apply_update("0.2.0", root=tmp_path / "leer", **env.deps())
    assert info.value.code == "update.not_installed"
    root = install_layout(tmp_path / "root", versions=("0.1.0",))
    with pytest.raises(UpdateError, match="nicht bereitgestellt"):
        apply.apply_update("0.3.0", root=root, **env.deps())
    with pytest.raises(UpdateError, match="Keine vorige"):
        apply.apply_update(None, root=root, rollback=True, **env.deps())
    assert apply.apply_update("0.1.0", root=root, **env.deps()) == "ok"
    assert env.spawned == []


def test_main_mutex_belegt_endet_mit_0(tmp_path, monkeypatch):
    name = f"Local\\Tapesmith.Update.Test.{id(tmp_path)}"
    monkeypatch.setattr(apply, "MUTEX_NAME", name)
    root = _root(tmp_path)
    holder = SingleInstance(name)
    assert holder.acquire()
    try:
        env = Env(root, health_version="0.2.0")
        assert apply.main(["--version", "0.2.0", "--root", str(root)], **env.deps()) == 0
        assert env.spawned == [] and _current(root) == "0.1.0"
    finally:
        holder.release()


def test_main_exitcodes(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "MUTEX_NAME", f"Local\\Tapesmith.Update.Test2.{id(tmp_path)}")
    root = _root(tmp_path)
    env = Env(root, health_version="0.2.0")
    assert apply.main(["--version", "0.2.0", "--root", str(root)], **env.deps()) == 0
    assert _current(root) == "0.2.0"
    env = Env(root, stopper_results=[False])
    assert apply.main(["--rollback", "--root", str(root)], **env.deps()) == 7
    env = Env(root, health_version=None)
    assert apply.main(["--rollback", "--root", str(root)], **env.deps()) == 1
    assert apply.main(["--root", str(root)], **env.deps()) == 1
    assert apply.main(["--version", "9.9.9", "--root", str(root)], **env.deps()) == 1
    assert state_mod.load_status().error["code"] == "update.apply_failed"
