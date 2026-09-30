"""Tests für die GUI-Dienste (ohne Qt): Aufbau der langlebigen Kernobjekte aus der Config."""

import contextlib
import dataclasses
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tapesmith.connection import PrinterOffline
from tapesmith.device.profile import load_profile
from tapesmith.gui.services import AppServices, Relay, build_services, default_transport_factory
from tapesmith.history import HistoryStore
from tapesmith.transport.base import FileTransport, MemoryTransport

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)
STATUS_OK = {bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
             bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
             bytes.fromhex("1f1112"): bytes.fromhex("1a0598")}
CFG = {"mac": "001122334455", "transport": "file:unbenutzt.bin", "idle_timeout_s": 300,
       "connect_timeout_s": 0.5, "guard": {}}
REPO_ROOT = Path(__file__).resolve().parent.parent


def services(tmp_path, transport, *, config=None, **kw) -> AppServices:
    return build_services(config=dict(config or CFG), profile=P,
                          history=HistoryStore(tmp_path / "h.db"),
                          transport_factory=lambda: transport, lock_factory=contextlib.nullcontext,
                          sleep=lambda s: None, **kw)


class SlowOpenTransport(MemoryTransport):
    """Öffnet erst nach `delay` Sekunden oder sobald `release` gesetzt ist."""

    def __init__(self, delay: float):
        super().__init__(STATUS_OK)
        self.delay = delay
        self.release = threading.Event()

    def open(self) -> None:
        self.release.wait(self.delay)
        super().open()


@pytest.fixture
def svc(tmp_path):
    s = services(tmp_path, MemoryTransport(STATUS_OK))
    yield s
    s.close()


def test_build_services_verbindet_nicht(svc):
    assert svc.manager.state.value == "getrennt"
    assert svc.pipeline.profile is P
    assert svc.profile is P
    assert svc.policy.confirm_copies == 5
    assert svc.config["mac"] == "001122334455"


def test_manager_verbindet_bei_bedarf(svc):
    assert svc.manager.run(lambda s: 1) == 1
    assert svc.manager.state.value == "verbunden"


def test_connect_timeout_aus_config(tmp_path):
    cfg = dict(CFG, connect_timeout_s=0.2)
    transport = SlowOpenTransport(30.0)
    s = services(tmp_path, transport, config=cfg)
    try:
        start = time.monotonic()
        with pytest.raises(PrinterOffline):
            s.manager.run(lambda sess: 1)
        assert time.monotonic() - start < 5.0      # ohne Zeitlimit hinge das Öffnen 30 s
    finally:
        transport.release.set()
        s.close()


def test_idle_timeout_aus_config_null_trennt_sofort(tmp_path):
    cfg = dict(CFG, idle_timeout_s=0)
    transport = MemoryTransport(STATUS_OK)
    s = services(tmp_path, transport, config=cfg)
    try:
        s.manager.run(lambda sess: 1)
        assert transport.closed
        assert s.manager.state.value == "getrennt"
    finally:
        s.close()


def test_state_relay_erhaelt_zustaende(tmp_path):
    transport = MemoryTransport(STATUS_OK)
    s = services(tmp_path, transport)
    got = []
    s.state_relay.connect(got.append)
    try:
        s.manager.run(lambda sess: 1)
        assert [st.value for st in got][:2] == ["verbindet", "verbunden"]
    finally:
        s.close()


def test_default_transport_factory_file(tmp_path):
    factory = default_transport_factory({"transport": "file:" + str(tmp_path / "x.bin"),
                                         "mac": "001122334455", "connect_timeout_s": 5})
    assert isinstance(factory(), FileTransport)


def test_relay_verteilt_und_verschluckt_fehler():
    relay = Relay()
    a, b = [], []

    def boom(*args):
        raise RuntimeError("kaputt")

    relay.connect(a.append)
    relay.connect(boom)
    relay.connect(b.append)
    relay("x")
    assert a == ["x"] and b == ["x"]
    relay.disconnect(boom)
    relay.disconnect(lambda *x: None)   # unbekannt: still ignorieren
    relay.disconnect(a.append)
    relay("y")
    assert a == ["x"] and b == ["x", "y"]


def test_relay_mehrere_argumente():
    relay = Relay()
    got = []
    relay.connect(lambda *args: got.append(args))
    relay(1, 2)
    assert got == [(1, 2)]


def test_close_idempotent(tmp_path):
    s = services(tmp_path, MemoryTransport(STATUS_OK))
    s.close()
    s.close()


def test_services_importiert_kein_qt():
    code = "import tapesmith.gui.services\nimport sys\nprint('PySide6' in sys.modules)\n"
    env = dict(os.environ)
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else os.pathsep.join([src_path, existing])
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(REPO_ROOT),
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False", result.stdout + result.stderr
