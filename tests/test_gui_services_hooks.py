"""Band/Restmeter und Schwarzanteil als Pipeline-Hooks in `build_services`,
sowie `AppServices.tape()`/`set_tape()`. Fake-Transport wie in `tests/test_gui_services.py`,
kein echter Druck, kein COM-Port."""

import contextlib
import dataclasses

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.gui.services import build_services
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel, PrintRequest
from tapesmith.render.compose import mm_to_rows
from tapesmith.tape.rolls import RollStore
from tapesmith.transport.base import FileTransport, MemoryTransport

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)

CFG = {"mac": "001122334455", "transport": "auto", "idle_timeout_s": 300,
       "connect_timeout_s": 5, "guard": {}}


def status_with_battery(hex_byte: str) -> dict:
    return {bytes.fromhex("1f1108"): bytes.fromhex(f"1a04{hex_byte}"),
            bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
            bytes.fromhex("1f1112"): bytes.fromhex("1a0598")}


STATUS_OK = status_with_battery("4b")   # 75 %


def make_services(tmp_path, transport, *, name="h", rolls=None, config=None):
    return build_services(config=dict(config or CFG), profile=P,
                          history=HistoryStore(tmp_path / f"{name}.db"),
                          transport_factory=lambda: transport,
                          lock_factory=contextlib.nullcontext, sleep=lambda s: None,
                          rolls=rolls)


def text_request(head) -> PrintRequest:
    return PrintRequest(labels=(PrintLabel(head),),
                        meta=JobMeta(source="gui", kind="text", title="T"))


# ---------- 1: Plan-Warnung und Verbrauchsmeldung ----------

def test_b2_plan_warning_and_consumption(tmp_path):
    rolls = RollStore(tmp_path / "rolls.json")
    rolls.new_roll("schwarz-weiss", length_mm=100.0)
    svc = make_services(tmp_path, MemoryTransport(STATUS_OK), rolls=rolls)
    try:
        head = Image.new("1", (P.head_dots, mm_to_rows(80, P)), 255)
        req = text_request(head)

        plan = svc.pipeline.plan(req)
        assert any("reicht wahrscheinlich nicht" in w for w in plan.check_warnings)

        remaining_before = rolls.remaining_mm()
        outcome = svc.pipeline.execute(req)
        assert outcome.status == "ok"
        assert outcome.consumed_mm > 0
        remaining_after = rolls.remaining_mm()
        assert remaining_after == pytest.approx(max(0.0, remaining_before - outcome.consumed_mm))
    finally:
        svc.close()


def test_b2_consumption_reduces_remaining_by_consumed_mm(tmp_path):
    rolls = RollStore(tmp_path / "rolls.json")
    rolls.new_roll("schwarz-weiss", length_mm=4000.0)
    svc = make_services(tmp_path, MemoryTransport(STATUS_OK), rolls=rolls, name="ausreichend")
    try:
        head = Image.new("1", (P.head_dots, mm_to_rows(20, P)), 255)
        remaining_before = rolls.remaining_mm()
        outcome = svc.pipeline.execute(text_request(head))
        assert outcome.status == "ok"
        remaining_after = rolls.remaining_mm()
        assert remaining_after == pytest.approx(remaining_before - outcome.consumed_mm)
    finally:
        svc.close()


def test_b2_no_warning_when_roll_is_sufficient(tmp_path):
    rolls = RollStore(tmp_path / "rolls.json")
    rolls.new_roll("schwarz-weiss", length_mm=4000.0)
    svc = make_services(tmp_path, MemoryTransport(STATUS_OK), rolls=rolls)
    try:
        head = Image.new("1", (P.head_dots, mm_to_rows(20, P)), 255)
        plan = svc.pipeline.plan(text_request(head))
        assert not any("reicht wahrscheinlich nicht" in w for w in plan.check_warnings)
    finally:
        svc.close()


# ---------- 2: Schwarzanteil mit Akkustand ----------

def test_n7_status_check_warns_on_low_battery(tmp_path):
    black = Image.new("1", (P.head_dots, 200), 0)
    svc = make_services(tmp_path, MemoryTransport(status_with_battery("14")), name="low")  # 20 %
    try:
        outcome = svc.pipeline.execute(text_request(black))
        assert outcome.status == "ok"
        assert any("Viel Schwarz" in w for w in outcome.warnings)
    finally:
        svc.close()


def test_n7_status_check_silent_on_high_battery(tmp_path):
    black = Image.new("1", (P.head_dots, 200), 0)
    svc = make_services(tmp_path, MemoryTransport(status_with_battery("50")), name="high")  # 80 %
    try:
        outcome = svc.pipeline.execute(text_request(black))
        assert outcome.status == "ok"
        assert not any("Viel Schwarz" in w for w in outcome.warnings)
    finally:
        svc.close()


def test_n7_status_check_unknown_battery_without_preflight(tmp_path):
    black = Image.new("1", (P.head_dots, 200), 0)
    svc = make_services(tmp_path, FileTransport(tmp_path / "out.bin"), name="filetrans")
    try:
        outcome = svc.pipeline.execute(text_request(black))
        assert outcome.status == "ok"
        assert any("unbekanntem Akkustand" in w for w in outcome.warnings)
    finally:
        svc.close()


# ---------- 3: AppServices.tape()/set_tape() ----------

def test_tape_default_and_set(tmp_path):
    svc = make_services(tmp_path, MemoryTransport(STATUS_OK))
    try:
        assert svc.tape().id == "schwarz-weiss"

        calls = []

        def fake_save(updates):
            calls.append(updates)
            return {**svc.config, **updates}

        result = svc.set_tape("weiss-schwarz", save=fake_save)
        assert result.id == "weiss-schwarz"
        assert calls == [{"tape": {"current": "weiss-schwarz"}}]
        assert svc.tape().id == "weiss-schwarz"

        with pytest.raises(ValueError):
            svc.set_tape("gibtsnicht", save=fake_save)
        assert calls == [{"tape": {"current": "weiss-schwarz"}}]  # nichts weiter gespeichert
    finally:
        svc.close()


# ---------- 4: Rolle je Band ----------

def test_b2_bandwechsel_laesst_alte_rolle_unveraendert(tmp_path):
    rolls = RollStore(tmp_path / "rolls.json")
    rolls.new_roll("schwarz-weiss", length_mm=4000.0)            # Rolle A
    svc = make_services(tmp_path, MemoryTransport(STATUS_OK), rolls=rolls, name="wechsel")
    try:
        svc.set_tape("weiss-schwarz", save=lambda updates: {**CFG, **updates})
        head = Image.new("1", (P.head_dots, mm_to_rows(20, P)), 255)
        assert svc.pipeline.execute(text_request(head)).status == "ok"
        assert rolls.current("schwarz-weiss").used_mm == 0       # A unverändert
        rolls.new_roll("weiss-schwarz", length_mm=100.0)         # Rolle B
        plan = svc.pipeline.plan(text_request(Image.new("1", (P.head_dots, mm_to_rows(80, P)), 255)))
        assert any("reicht wahrscheinlich nicht" in w for w in plan.check_warnings)
        outcome = svc.pipeline.execute(text_request(head))
        assert rolls.current("weiss-schwarz").used_mm == pytest.approx(outcome.consumed_mm)
        assert rolls.current("schwarz-weiss").used_mm == 0
    finally:
        svc.close()
