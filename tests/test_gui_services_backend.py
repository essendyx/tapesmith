"""GUI-Dienste über das Druck-Backend: lokal, übergeben, über den Dienst."""

import contextlib
import dataclasses

from tapesmith.device.profile import load_profile
from tapesmith.gui import services as services_mod
from tapesmith.gui.services import build_services
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import LocalBackend
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel, PrintRequest
from tapesmith.transport.base import MemoryTransport

from gui_backend_fakes import FakeBackend, FakeQueueOps

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)
STATUS_OK = {bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
             bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
             bytes.fromhex("1f1112"): bytes.fromhex("1a0598")}
CFG = {"mac": "001122334455", "transport": "file:unbenutzt.bin", "idle_timeout_s": 300,
       "connect_timeout_s": 0.5, "guard": {}}


def build(tmp_path, **kw):
    kw.setdefault("transport_factory", lambda: MemoryTransport(STATUS_OK))
    return build_services(config=dict(CFG), profile=P, history=HistoryStore(tmp_path / "h.db"),
                          lock_factory=contextlib.nullcontext, sleep=lambda s: None, **kw)


def request():
    from PIL import Image

    return PrintRequest(labels=(PrintLabel(Image.new("1", (P.head_dots, 120), 255)),),
                        meta=JobMeta(source="gui", kind="text", title="T"))


# 1
def test_lokales_backend_druckt_in_den_verlauf(tmp_path):
    svc = build(tmp_path)
    try:
        assert isinstance(svc.backend, LocalBackend)
        assert svc.backend.kind == "local"
        assert svc.uses_daemon() is False
        assert svc.queue_ops() is None
        outcome = svc.backend.execute(request())
        assert outcome.status == "ok"
        assert svc.history.last().id == outcome.history_id
        assert svc.backend.state_info().state == "verbunden"
    finally:
        svc.close()


def test_ohne_transport_fabrik_aber_no_daemon_lokal(tmp_path):
    # conftest setzt TAPESMITH_NO_DAEMON=1 -> nie ein Dienst
    svc = build_services(config=dict(CFG), profile=P, history=HistoryStore(tmp_path / "h.db"))
    try:
        assert svc.backend.kind == "local"
        assert svc.backend.fallback_reason == ""
    finally:
        svc.close()


# 2
def test_uebergebenes_backend_und_reload(tmp_path):
    fake = FakeBackend()
    saved = []
    svc = build(tmp_path, backend=fake)
    try:
        assert svc.backend is fake
        svc.reload_policy()
        assert fake.reloads == 1
        svc.set_tape(svc.tape().id, save=lambda upd: saved.append(upd) or dict(CFG, **upd))
        assert fake.reloads == 2
        svc.set_cut_pause(5)
        assert fake.reloads == 3
        svc.reload_profile()
        assert fake.reloads == 4
        svc.reload_policy(reload_backend=False)
        assert fake.reloads == 4
    finally:
        svc.close()
    assert fake.closed


def test_reload_fehler_des_dienstes_bricht_nichts(tmp_path):
    fake = FakeBackend(reload_error=RuntimeError("Dienst weg"))
    svc = build(tmp_path, backend=fake)
    try:
        policy = svc.reload_policy()
        assert svc.policy is policy
    finally:
        svc.close()


# 3
def test_dienst_backend_ueber_make_backend(tmp_path, monkeypatch):
    fake = FakeBackend(kind="daemon", queue=FakeQueueOps())
    seen = {}

    def fake_make_backend(cfg, profile, *, client, local_factory, planner=None, **kw):
        seen.update(client=client, planner=planner, local=local_factory("grund"))
        return fake

    monkeypatch.setattr(services_mod, "make_backend", fake_make_backend)
    svc = build(tmp_path, use_daemon=True)
    try:
        assert svc.backend is fake
        assert svc.uses_daemon() is True
        assert svc.queue_ops() is fake.queue
        assert seen["client"] == "gui"
        assert seen["planner"] == svc.pipeline.plan
        assert isinstance(seen["local"], LocalBackend)
        assert seen["local"].fallback_reason == "grund"
    finally:
        svc.close()
    assert fake.closed


def test_use_daemon_automatisch_nur_ohne_transport_fabrik(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(services_mod, "make_backend",
                        lambda *a, **kw: calls.append(1) or FakeBackend(kind="daemon"))
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    svc = build(tmp_path)        # Transport-Fabrik gesetzt -> direkt (Tests/Fakes)
    svc.close()
    assert calls == []
    svc = build_services(config=dict(CFG), profile=P, history=HistoryStore(tmp_path / "h2.db"))
    try:
        assert calls == [1]
        assert svc.uses_daemon()
    finally:
        svc.close()


def test_archiv_hook_wird_angehaengt(tmp_path, monkeypatch):
    notes = []

    def hook(outcome):
        notes.append(outcome.status)
        return ["archiviert"]

    monkeypatch.setattr(services_mod, "archive_hook", lambda cfg: hook)
    svc = build(tmp_path)
    try:
        outcome = svc.backend.execute(request())
        assert notes == ["ok"]
        assert "archiviert" in outcome.warnings
    finally:
        svc.close()
