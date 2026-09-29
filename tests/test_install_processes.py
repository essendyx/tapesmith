"""Tests für `tapesmith.install.processes` (laufende Prozesse finden/beenden).

Nur Fakes für `lister`/`connect`/`killer`; `list_processes()` selbst wird nur einmal echt
aufgerufen (prüft nur, dass der eigene Prozess dabei ist, druckt/verbindet nichts)."""

from __future__ import annotations

import sys

from tapesmith.install import layout, processes


# ---------- list_processes (echt, nur Lesevorgang) ----------

def test_list_processes_enthaelt_eigenen_prozess():
    result = processes.list_processes()
    exes = {p.exe.upper() for p in result}
    assert any(sys.executable.upper() in exe or exe in sys.executable.upper() for exe in exes) or \
        any(p.pid == __import__("os").getpid() for p in result)


# ---------- processes_under ----------

def _proc(pid, exe):
    return processes.ProcessInfo(pid=pid, exe=exe)


def test_processes_under_findet_prozesse_unter_wurzel(tmp_path):
    root = tmp_path / "Tapesmith"
    unter_wurzel = _proc(111, str(root / "versions" / "0.2.0" / "Tapesmith.exe"))
    ausserhalb = _proc(222, r"C:\Windows\System32\notepad.exe")

    result = processes.processes_under(root, lister=lambda: [unter_wurzel, ausserhalb])

    assert result == [unter_wurzel]


def test_processes_under_gross_klein_und_praefix_egal(tmp_path):
    root = tmp_path / "Tapesmith"
    exe = "\\\\?\\" + str(root / "VERSIONS" / "0.2.0" / "Tapesmith.exe").upper()
    proc = _proc(1, exe)

    result = processes.processes_under(root, lister=lambda: [proc])

    assert result == [proc]


def test_processes_under_schliesst_eigene_pid_aus(tmp_path):
    root = tmp_path / "Tapesmith"
    eigener = _proc(999, str(root / "versions" / "0.2.0" / "Tapesmith.exe"))

    result = processes.processes_under(root, lister=lambda: [eigener], exclude_pids=(999,))

    assert result == []


def test_processes_under_beruecksichtigt_current_ziel(tmp_path):
    root = tmp_path / "Tapesmith"
    root.mkdir()
    target = tmp_path / "anderswo" / "0.2.0"
    target.mkdir(parents=True)
    from tapesmith.install import junction
    junction.create_junction(layout.current_link(root), target)

    proc = _proc(5, str(target / "Tapesmith.exe"))
    result = processes.processes_under(root, lister=lambda: [proc])

    assert result == [proc]


# ---------- stop_daemon ----------

class _FakeClient:
    def __init__(self, response, *, alive_after=0):
        self.response = response
        self.alive_after = alive_after
        self.closed = False

    def call(self, method, params=None):
        assert method == "shutdown"
        assert params == {"force": False}
        return self.response

    def close(self):
        self.closed = True


def test_stop_daemon_meldet_sich_mit_erlaubter_client_art():
    # Die Client-Art prüft der Handshake (auch der schon laufende, ältere Dienst). "installer"
    # war nie erlaubt: die echte Installation über einen laufenden Dienst brach so ab (29.09.2026).
    from tapesmith.ipc.protocol import CLIENT_KINDS, hello
    from tapesmith.ipc.pipe import DaemonUnavailable
    kinds = []

    def connect(**kw):
        kinds.append(kw["client"])
        hello(kw["client"], "k")
        raise DaemonUnavailable("weg")

    assert processes.stop_daemon({}, connect=connect) is True
    assert kinds and all(k in CLIENT_KINDS for k in kinds)


def test_stop_daemon_kein_dienst_erreichbar_gibt_true():
    from tapesmith.ipc.pipe import DaemonUnavailable

    def connect(*, client, timeout_s):
        raise DaemonUnavailable("nicht erreichbar")

    assert processes.stop_daemon({}, connect=connect) is True


def test_stop_daemon_stopping_false_gibt_false():
    client = _FakeClient({"stopping": False})

    assert processes.stop_daemon({}, connect=lambda **kw: client) is False
    assert client.closed is True


def test_stop_daemon_stoppt_und_wird_dann_unerreichbar():
    from tapesmith.ipc.pipe import DaemonUnavailable

    fake_client = _FakeClient({"stopping": True})
    state = {"n": 0}

    def connect(*, client, timeout_s):
        state["n"] += 1
        if state["n"] == 1:
            return fake_client
        raise DaemonUnavailable("jetzt weg")

    assert processes.stop_daemon({}, connect=connect, timeout_s=5.0) is True
    assert fake_client.closed is True


def test_stop_daemon_timeout_gibt_false(monkeypatch):
    from tapesmith.ipc.pipe import DaemonUnavailable

    fake_client = _FakeClient({"stopping": True})
    still_alive_client = _FakeClient({"stopping": True})
    state = {"n": 0}

    def connect(*, client, timeout_s):
        state["n"] += 1
        if state["n"] == 1:
            return fake_client
        return still_alive_client  # bleibt immer erreichbar -> Timeout

    monkeypatch.setattr(processes.time, "sleep", lambda s: None)
    assert processes.stop_daemon({}, connect=connect, timeout_s=0.05) is False


# ---------- terminate ----------

def test_terminate_erfolgreich_gibt_leere_liste():
    calls = []

    def killer(pid, timeout_s):
        calls.append((pid, timeout_s))
        return True

    remaining = processes.terminate([1, 2, 3], killer=killer, timeout_s=1.0)
    assert remaining == []
    assert calls == [(1, 1.0), (2, 1.0), (3, 1.0)]


def test_terminate_uebrig_gebliebene_pids():
    def killer(pid, timeout_s):
        return pid != 2

    remaining = processes.terminate([1, 2, 3], killer=killer)
    assert remaining == [2]


def test_terminate_killer_wirft_zaehlt_als_uebrig():
    def killer(pid, timeout_s):
        raise OSError("kaputt")

    remaining = processes.terminate([1], killer=killer)
    assert remaining == [1]
