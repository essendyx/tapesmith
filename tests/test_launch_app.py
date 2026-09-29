"""Tests für die neue Prozessart 'app' und `cwd` = App-Verzeichnis bei losgelösten
Prozessen (Dienst, Tray, Browserstart)."""

from tapesmith import launch, paths
from tapesmith.ipc.launcher import ensure_daemon
from tapesmith.ipc.pipe import DaemonUnavailable


def test_app_argv_frozen():
    argv = launch.app_argv("app", frozen=True, executable="C:/P/Tapesmith.exe")
    assert argv == ["C:/P/Tapesmith.exe", "--app"]


def test_app_argv_dev_endet_mit_modul_und_extra(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    argv = launch.app_argv("app", "--route", "/verlauf", frozen=False, executable=str(py))
    assert argv[-4:] == ["-m", "tapesmith.webui.browser", "--route", "/verlauf"]


def test_gui_frozen_ist_exe_ohne_argument():
    """`Tapesmith.exe` ohne Argument öffnet die Web-Oberfläche im Browser (Kontextmenü/URI-Befehle)."""
    assert launch.FROZEN_FLAGS["gui"] == []
    assert launch.app_argv("gui", frozen=True, executable="C:/P/Tapesmith.exe") == ["C:/P/Tapesmith.exe"]


def test_gui_entwicklung_oeffnet_browser(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    argv = launch.app_argv("gui", "--uri", "tapesmith://text?l=x", frozen=False, executable=str(py))
    assert argv == [str(py), "-m", "tapesmith.webui.browser", "--uri", "tapesmith://text?l=x"]
    assert launch.MODULES["gui"] == launch.MODULES["app"] == "tapesmith.webui.browser"


def test_registry_befehl_kontextmenue_dev(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    cmd = launch.registry_command("gui", "--open", "batch", "--path", frozen=False, executable=str(py))
    assert "-m tapesmith.webui.browser --open batch --path" in cmd
    assert cmd.endswith('"%1"')


def test_spawn_detached_cwd_default_ist_app_dir():
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["cwd"] = kwargs.get("cwd")

        class P:
            pid = 1

        return P()

    launch.spawn_detached(["x"], popen=fake_popen)
    assert captured["cwd"] == str(paths.app_dir())
    assert paths.app_dir().is_dir()


def test_spawn_detached_cwd_explizit_bleibt_unveraendert(tmp_path):
    captured = {}
    anders = str(tmp_path / "anders")

    def fake_popen(argv, **kwargs):
        captured["cwd"] = kwargs.get("cwd")

        class P:
            pid = 1

        return P()

    launch.spawn_detached(["x"], popen=fake_popen, cwd=anders)
    assert captured["cwd"] == anders


class FakeClient:
    def __init__(self):
        self.closed = False

    def call(self, method, params=None, *, timeout=30.0):
        return {"pid": 1}

    def close(self):
        self.closed = True


def test_ensure_daemon_spawnt_ueber_spawn_detached_mit_app_dir_als_cwd(monkeypatch):
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["cwd"] = kwargs.get("cwd")

        class P:
            pid = 999

        return P()

    monkeypatch.setattr(launch.subprocess, "Popen", fake_popen)

    client = FakeClient()
    results = [DaemonUnavailable("nein"), client]

    def connector(**kw):
        item = results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    result = ensure_daemon({}, spawn=launch.spawn_detached, connector=connector,
                           sleep=lambda s: None, clock=lambda: 0.0)
    assert result is client
    assert captured["cwd"] == str(paths.app_dir())
