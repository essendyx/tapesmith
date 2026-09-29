"""`"wartet"`-Status, `PrintOutcome.queue_id`, `execute(..., debounce=False)`."""

import contextlib
from datetime import datetime

from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.guard import Debouncer
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import (
    OUTCOME_STATUSES,
    PrintLabel,
    PrintOutcome,
    PrintPipeline,
    PrintRequest,
    direct_runner,
)
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import ESC_AT_GS_V0
from tapesmith.transport.base import MemoryTransport

P = load_profile()

STATUS_OK = {
    bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
    bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
    bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
}


def label(rows=240):
    img = Image.new("1", (P.head_dots, rows), 255)
    return PrintLabel(img)


def memory_runner(transport, slept):
    def open_session():
        return PrinterSession(transport, P, lock=contextlib.nullcontext(), sleep=slept.append)
    return direct_runner(open_session)


def request(meta=None):
    return PrintRequest(labels=(label(),), meta=meta or JobMeta(source="cli", kind="text", title="T"))


def make_plan():
    transport = MemoryTransport(STATUS_OK)
    pipe = PrintPipeline(P, memory_runner(transport, []), preflight=False)
    return pipe.plan(request())


# 13
def test_wartet_status_and_queue_id():
    assert "wartet" in OUTCOME_STATUSES
    plan = make_plan()
    outcome = PrintOutcome("wartet", plan)
    assert outcome.queue_id is None
    outcome2 = PrintOutcome("wartet", plan, queue_id=3)
    assert outcome2.queue_id == 3


def test_existing_pipeline_tests_still_pass_with_default_debounce():
    t = [100.0]
    deb = Debouncer(min_interval_s=1.5, clock=lambda: t[0])
    transport = MemoryTransport(STATUS_OK)
    pipe = PrintPipeline(P, memory_runner(transport, []), debouncer=deb, preflight=False,
                         now=lambda: datetime(2026, 9, 27))
    assert pipe.execute(request()).status == "ok"
    second = pipe.execute(request())
    assert second.status == "abgelehnt"


# 14
def test_debounce_false_bypasses_double_press_guard():
    t = [100.0]
    deb = Debouncer(min_interval_s=1.5, clock=lambda: t[0])
    transport = MemoryTransport(STATUS_OK)
    pipe = PrintPipeline(P, memory_runner(transport, []), debouncer=deb, preflight=False)
    req = request()

    outcome1 = pipe.execute(req, debounce=False)
    outcome2 = pipe.execute(req, debounce=False)
    assert outcome1.status == "ok"
    assert outcome2.status == "ok"
    # Zwei vollständige Jobs im Transport (je ein Raster-Kopfbild ESC @ GS v 0)
    raster_jobs = [w for w in transport.written if w.startswith(ESC_AT_GS_V0)]
    assert len(raster_jobs) == 2

    # debounce=False hat den Debouncer nicht "gefüttert" -> normaler Aufruf danach ist noch ok
    outcome3 = pipe.execute(req)
    assert outcome3.status == "ok"


def test_debounce_true_default_still_rejects_after_debounce_false_runs():
    t = [100.0]
    deb = Debouncer(min_interval_s=1.5, clock=lambda: t[0])
    transport = MemoryTransport(STATUS_OK)
    pipe = PrintPipeline(P, memory_runner(transport, []), debouncer=deb, preflight=False)
    req = request()

    pipe.execute(req, debounce=False)
    pipe.execute(req, debounce=False)
    assert pipe.execute(req).status == "ok"
    # jetzt hat der normale Aufruf den Debouncer belegt -> ein direkt folgender zweiter wird abgelehnt
    second = pipe.execute(req)
    assert second.status == "abgelehnt"
