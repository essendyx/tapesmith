"""Plan-/Status-Prüfungen, Verbrauchsmeldung, Laufzeit-Umschalten, Schneidpause."""

import dataclasses
import threading
import time

import pytest

from tapesmith.guard import GuardPolicy
from tapesmith.jobs import CancelToken
from tapesmith.pipeline import CUT_PAUSE_KEY, CUT_PAUSE_OFF, CheckResult, PrintPlan
from tapesmith.render.compose import rows_to_mm
from tapesmith.transport.base import MemoryTransport

from test_pipeline import (
    STATUS_OK,
    FailingBlockTransport,
    P,
    label,
    pipeline,
    raster_heads,
    request,
)


# 1
def test_plan_check_warnings_reach_plan_and_on_warning():
    seen = []
    pipe = pipeline(MemoryTransport(STATUS_OK), [], on_warning=seen.append,
                    checks=[lambda plan: CheckResult(warnings=("W",))])
    plan = pipe.plan(request(label()))
    assert isinstance(plan, PrintPlan)
    assert plan.check_warnings == ("W",)
    outcome = pipe.execute(request(label()))
    assert outcome.status == "ok"
    assert "W" in seen
    assert "W" in outcome.warnings


# 2
def test_plan_check_confirm_needs_confirmation():
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [])
    pipe.add_check(lambda plan: CheckResult(confirm=("Band ungeeignet",)))
    outcome = pipe.execute(request(label()))
    assert outcome.status == "bestätigung_nötig"
    assert "Band ungeeignet" in outcome.reasons
    assert transport.written == []
    outcome = pipe.execute(request(label(), confirmed=True))
    assert outcome.status == "ok"
    assert len(raster_heads(transport)) == 1


def test_plan_check_confirm_keeps_existing_reasons_and_rejections():
    pipe = pipeline(MemoryTransport(STATUS_OK), [],
                    checks=[lambda plan: CheckResult(confirm=("Band ungeeignet",))])
    plan = pipe.plan(request(label(), copies=6))
    assert plan.decision.allowed and plan.decision.needs_confirmation
    assert plan.decision.reasons == ("6 Kopien", "Band ungeeignet")
    plan = pipe.plan(request(label(), copies=60))
    assert not plan.decision.allowed
    assert "Band ungeeignet" not in plan.decision.reasons


# 3
def test_failing_plan_check_only_warns():
    def boom(plan):
        raise RuntimeError("kaputt")

    transport = MemoryTransport(STATUS_OK)
    seen = []
    pipe = pipeline(transport, [], on_warning=seen.append, checks=[boom])
    outcome = pipe.execute(request(label()))
    assert outcome.status == "ok"
    assert "Prüfung fehlgeschlagen: kaputt" in seen
    assert len(raster_heads(transport)) == 1


# 4
def test_status_check_gets_printer_status_or_none():
    calls = []

    def check(plan, status):
        calls.append(status)
        return ["Akku prüfen"]

    outcome = pipeline(MemoryTransport(STATUS_OK), [], status_checks=[check]).execute(request(label()))
    assert outcome.status == "ok"
    assert calls[0].get("battery").value == 75
    assert "Akku prüfen" in outcome.warnings

    calls.clear()
    pipe = pipeline(MemoryTransport(STATUS_OK), [], preflight=False)
    pipe.add_status_check(check)
    outcome = pipe.execute(request(label()))
    assert calls == [None]
    assert "Akku prüfen" in outcome.warnings


def test_failing_status_check_only_warns():
    def boom(plan, status):
        raise RuntimeError("weg")

    transport = MemoryTransport(STATUS_OK)
    outcome = pipeline(transport, [], status_checks=[boom]).execute(request(label()))
    assert outcome.status == "ok"
    assert "Prüfung fehlgeschlagen: weg" in outcome.warnings
    assert len(raster_heads(transport)) == 1


# 5
def test_on_consumed_for_copies():
    consumed = []
    outcome = pipeline(MemoryTransport(STATUS_OK), [], on_consumed=consumed.append).execute(
        request(label(), copies=2))
    expected = 2 * (rows_to_mm(240, P) + 8 + 16)
    assert outcome.consumed_mm == pytest.approx(expected)
    assert consumed == [pytest.approx(expected)]


def test_on_consumed_for_incomplete_print():
    consumed = []
    transport = FailingBlockTransport(STATUS_OK, block_len=256 * P.bytes_per_line)
    outcome = pipeline(transport, [], chunk_rows=256, on_consumed=consumed.append).execute(
        request(label(600)))
    assert outcome.status == "unvollständig"
    expected = rows_to_mm(256, P) + 8 + 16
    assert outcome.consumed_mm == pytest.approx(expected)
    assert consumed == [pytest.approx(expected)]


def test_on_consumed_not_called_without_print_and_errors_only_warn():
    consumed = []
    token = CancelToken()
    token.cancel()
    outcome = pipeline(MemoryTransport(STATUS_OK), [], on_consumed=consumed.append).execute(
        request(label()), cancel=token)
    assert outcome.status == "abgebrochen"
    assert outcome.consumed_mm == 0.0
    assert consumed == []

    def boom(mm):
        raise RuntimeError("voll")

    outcome = pipeline(MemoryTransport(STATUS_OK), [], on_consumed=boom).execute(request(label()))
    assert outcome.status == "ok"
    assert any("voll" in w for w in outcome.warnings)


# 6
def test_set_policy_and_profile():
    pipe = pipeline(MemoryTransport(STATUS_OK), [])
    assert not pipe.plan(request(label(), copies=2)).decision.needs_confirmation
    pipe.set_policy(GuardPolicy(confirm_copies=1))
    assert pipe.plan(request(label(), copies=2)).decision.needs_confirmation
    pipe.set_policy(None)
    assert not pipe.plan(request(label(), copies=2)).decision.needs_confirmation
    p2 = dataclasses.replace(P, leader_mm=5.0)
    pipe.set_profile(p2)
    assert pipe.profile is p2


def test_connection_manager_set_profile_applies_to_next_session():
    import contextlib

    from tapesmith.connection import ConnectionManager

    manager = ConnectionManager(lambda: MemoryTransport(STATUS_OK), P, idle_timeout_s=0,
                                lock_factory=contextlib.nullcontext, sleep=lambda s: None)
    try:
        assert manager.run(lambda session: session.profile) is P
        p2 = dataclasses.replace(P, leader_mm=5.0)
        manager.set_profile(p2)
        assert manager.run(lambda session: session.profile) is p2
    finally:
        manager.close()


# ---------- Schneidpause ----------

def _wait_until(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("Bedingung nicht erreicht")
        time.sleep(0.005)


def _start(pipe, req, cancel=None):
    box = {}

    def work():
        box["outcome"] = pipe.execute(req, cancel=cancel)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, box


# 7
def test_cut_pause_waits_for_continue():
    transport = MemoryTransport(STATUS_OK)
    events = []
    pipe = pipeline(transport, [], on_cut_pause=lambda *a: events.append(a), pause_poll_s=0.005)
    assert pipe.continue_after_cut() is False
    thread, box = _start(pipe, request(label(), copies=3, cut_pause_s=CUT_PAUSE_KEY))
    _wait_until(lambda: pipe.cut_pause_active and events)
    assert events == [("start", 1, 3, 0.0)]
    assert len(raster_heads(transport)) == 1
    assert pipe.continue_after_cut() is True
    _wait_until(lambda: pipe.cut_pause_active and len(events) == 3)
    assert events[1] == ("end", 1, 3, 0.0)
    assert events[2] == ("start", 2, 3, 0.0)
    assert len(raster_heads(transport)) == 2
    assert pipe.continue_after_cut() is True
    thread.join(5)
    assert box["outcome"].status == "ok"
    assert len(raster_heads(transport)) == 3
    assert events[-1] == ("end", 2, 3, 0.0)
    assert not pipe.cut_pause_active


# 8
def test_cut_pause_seconds_run_out():
    t = [0.0]

    def clock():
        t[0] += 1.0
        return t[0]

    transport = MemoryTransport(STATUS_OK)
    events = []
    pipe = pipeline(transport, [], on_cut_pause=lambda *a: events.append(a), clock=clock,
                    pause_poll_s=0.001)
    outcome = pipe.execute(request(label(), copies=2, cut_pause_s=5))
    assert outcome.status == "ok"
    assert len(raster_heads(transport)) == 2
    assert events == [("start", 1, 2, 5.0), ("end", 1, 2, 5.0)]


# 9
def test_cancel_during_cut_pause():
    transport = MemoryTransport(STATUS_OK)
    token = CancelToken()
    pipe = pipeline(transport, [], pause_poll_s=0.005)
    thread, box = _start(pipe, request(label(), copies=3, cut_pause_s=CUT_PAUSE_KEY), cancel=token)
    _wait_until(lambda: pipe.cut_pause_active)
    token.cancel()
    thread.join(5)
    assert box["outcome"].status == "abgebrochen"
    assert len(raster_heads(transport)) == 1
    assert not pipe.cut_pause_active


# 10
def test_cut_pause_default_and_off():
    events = []
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], on_cut_pause=lambda *a: events.append(a),
                    cut_pause_s=CUT_PAUSE_KEY, pause_poll_s=0.005)
    outcome = pipe.execute(request(label(), copies=2, cut_pause_s=CUT_PAUSE_OFF))
    assert outcome.status == "ok"
    assert len(raster_heads(transport)) == 2
    outcome = pipe.execute(request(label(mark=1), copies=3, chain=True))
    assert outcome.status == "ok"
    assert len(outcome.plan.chain.jobs) == 1
    assert events == []
    pipe.set_cut_pause(None)
    assert pipe.execute(request(label(mark=2), copies=2)).status == "ok"
    assert events == []


def test_cut_pause_uses_pipeline_default():
    events = []
    pipe = pipeline(MemoryTransport(STATUS_OK), [], on_cut_pause=lambda *a: events.append(a),
                    pause_poll_s=0.005)
    pipe.set_cut_pause(CUT_PAUSE_KEY)
    thread, box = _start(pipe, request(label(), copies=2))
    _wait_until(lambda: pipe.cut_pause_active)
    pipe.continue_after_cut()
    thread.join(5)
    assert box["outcome"].status == "ok"
    assert [e[0] for e in events] == ["start", "end"]
