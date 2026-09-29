import contextlib
import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from tapesmith.connection import ConnectionManager
from tapesmith.device.profile import load_profile
from tapesmith.guard import Debouncer
from tapesmith.history import HistoryStore
from tapesmith.jobs import CancelToken, IncompletePrint, JobMeta
from tapesmith.pipeline import (
    OUTCOME_STATUSES,
    PrintLabel,
    PrintPipeline,
    PrintRequest,
    direct_runner,
    labels_from_result,
    manager_runner,
)
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import ESC_AT_GS_V0, build_job, job_bytes
from tapesmith.protocol.raster import place_on_head
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label
from tapesmith.transport.base import ConnectTimeout, FileTransport, MemoryTransport, TransportError

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 9, 27, 12, 0, 0)

STATUS_OK = {
    bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
    bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
    bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
}
STATUS_LID_OPEN = {**STATUS_OK, bytes.fromhex("1f1112"): bytes.fromhex("1a0599")}


def label(rows=240, mark=0):
    img = Image.new("1", (P.head_dots, rows), 255)
    if mark:
        img.putpixel((P.content_offset + mark, 0), 0)
    return PrintLabel(img)


def memory_runner(transport, slept, chunk_rows=256):
    def open_session():
        return PrinterSession(transport, P, lock=contextlib.nullcontext(), sleep=slept.append,
                              chunk_rows=chunk_rows)
    return direct_runner(open_session)


def raster_heads(transport):
    return [w for w in transport.written if w.startswith(ESC_AT_GS_V0)]


def header_rows(header: bytes) -> int:
    return int.from_bytes(header[8:10], "little")


def request(*labels, meta=None, **kw):
    return PrintRequest(labels=tuple(labels), meta=meta or JobMeta(source="cli", kind="text", title="T"), **kw)


@pytest.fixture
def history(tmp_path):
    store = HistoryStore(tmp_path / "verlauf.db", clock=lambda: NOW)
    yield store
    store.close()


def pipeline(transport, slept, history=None, **kw):
    kw.setdefault("now", lambda: NOW)
    return PrintPipeline(P, memory_runner(transport, slept, kw.pop("chunk_rows", 256)),
                         history=history, **kw)


# 1
def test_simple_print_with_preflight(history):
    transport = MemoryTransport(STATUS_OK)
    slept = []
    outcome = pipeline(transport, slept, history).execute(request(label()))
    assert outcome.status == "ok"
    assert outcome.status in OUTCOME_STATUSES
    assert len(outcome.results) == 1
    init_index = transport.written.index(bytes.fromhex("1f1138"))
    assert transport.written[:3] == [bytes.fromhex(q) for q in ("1f1108", "1f1111", "1f1112")]
    assert init_index == 3
    assert len(raster_heads(transport)) == 1
    assert outcome.printer_status.get("lid").value == "zu"
    assert outcome.warnings == []
    assert history.get(outcome.history_id).status == "ok"


# 2
def test_file_transport_stream_unchanged(tmp_path):
    head = place_on_head(Image.open(GOLDEN / "ref_label.pbm"), P)
    out = tmp_path / "job.bin"
    slept = []

    def open_session():
        return PrinterSession(FileTransport(out), P, lock=contextlib.nullcontext(), sleep=slept.append)

    outcome = PrintPipeline(P, direct_runner(open_session)).execute(request(PrintLabel(head)))
    assert outcome.status == "ok"
    assert outcome.printer_status is None
    data = out.read_bytes()
    assert data == job_bytes(build_job(head, P))
    assert data == (GOLDEN / "ref_stream.bin").read_bytes()


# 3
def test_copies_without_chain_are_separate_jobs():
    transport = MemoryTransport(STATUS_OK)
    slept = []
    outcome = pipeline(transport, slept).execute(request(label(), copies=3))
    assert outcome.status == "ok"
    assert len(outcome.plan.chain.jobs) == 3
    assert len(raster_heads(transport)) == 3
    assert len(slept) == 3


# 4
def test_chain_is_one_job_with_cut_zones():
    transport = MemoryTransport(STATUS_OK)
    slept = []
    pipe = pipeline(transport, slept)
    req = request(label(), label(mark=1), label(mark=2), chain=True)
    outcome = pipe.execute(req)
    assert outcome.status == "ok"
    heads = raster_heads(transport)
    assert len(heads) == 1
    assert mm_to_rows(1.0, P) == 8
    assert header_rows(heads[0]) == 3 * 240 + 2 * 18
    assert "statt" in outcome.plan.balance_text


# 5
def test_long_chain_is_split_and_warned():
    transport = MemoryTransport(STATUS_OK)
    slept = []
    seen = []
    pipe = pipeline(transport, slept, on_warning=seen.append)
    outcome = pipe.execute(request(*[label(mark=i) for i in range(10)], chain=True))
    assert outcome.status == "ok"
    assert len(raster_heads(transport)) == 2
    assert any("aufgeteilt" in w for w in outcome.warnings)
    assert any("aufgeteilt" in w for w in seen)


def test_plan_warnings_reported_before_sending():
    transport = MemoryTransport(STATUS_OK)
    written_at_warning = []
    pipe = pipeline(transport, [], on_warning=lambda w: written_at_warning.append(len(transport.written)))
    pipe.execute(request(*[label(mark=i) for i in range(10)], chain=True))
    assert written_at_warning and written_at_warning[0] == 0


# 6
def test_preflight_lid_open_warns_but_prints():
    transport = MemoryTransport(STATUS_LID_OPEN)
    seen = []
    outcome = pipeline(transport, [], on_warning=seen.append).execute(request(label()))
    assert outcome.status == "ok"
    assert any("Deckel offen" in w for w in outcome.warnings)
    assert any("Deckel offen" in w for w in seen)
    assert len(raster_heads(transport)) == 1


def test_preflight_can_be_disabled():
    transport = MemoryTransport(STATUS_OK)
    outcome = pipeline(transport, [], preflight=False).execute(request(label()))
    assert outcome.status == "ok"
    assert transport.written[0] == bytes.fromhex("1f1138")
    assert outcome.printer_status is None


# 7
def test_guard_needs_confirmation(history):
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], history)
    outcome = pipe.execute(request(label(), copies=6))
    assert outcome.status == "bestätigung_nötig"
    assert outcome.reasons
    assert transport.written == []
    assert outcome.history_id is None
    assert history.search() == []
    outcome = pipe.execute(request(label(), copies=6, confirmed=True))
    assert outcome.status == "ok"
    assert len(raster_heads(transport)) == 6


# 8
def test_guard_rejects_unconfirmable_source():
    transport = MemoryTransport(STATUS_OK)
    meta = JobMeta(source="api", kind="text", title="lang")
    outcome = pipeline(transport, []).execute(request(label(1300), meta=meta))
    assert outcome.status == "abgelehnt"
    assert any("kann nicht bestätigen" in r for r in outcome.reasons)
    assert transport.written == []


# 9
def test_quota_from_history(tmp_path):
    clock = [NOW - timedelta(hours=2)]
    store = HistoryStore(tmp_path / "q.db", clock=lambda: clock[0])
    try:
        meta = JobMeta(source="mqtt", kind="text", title="alt")
        for _ in range(10):
            store.record(meta, landscape=None, head=None, length_mm=30, tape_mm=10, status="ok")
        transport = MemoryTransport(STATUS_OK)
        pipe = PrintPipeline(P, memory_runner(transport, []), history=store, now=lambda: NOW)
        clock[0] = NOW - timedelta(minutes=30)
        assert pipe.execute(request(label(), meta=meta)).status == "ok"  # alte zählen nicht
        for _ in range(9):
            store.record(meta, landscape=None, head=None, length_mm=30, tape_mm=10, status="ok")
        outcome = pipe.execute(request(label(), meta=meta))
        assert outcome.status == "abgelehnt"
        assert any("Kontingent" in r for r in outcome.reasons)
    finally:
        store.close()


# 10
def test_debouncer_rejects_double_press():
    t = [100.0]
    deb = Debouncer(min_interval_s=1.5, clock=lambda: t[0])
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], debouncer=deb)
    assert pipe.execute(request(label())).status == "ok"
    second = pipe.execute(request(label()))
    assert second.status == "abgelehnt"
    assert any("doppelt" in r for r in second.reasons)
    assert pipe.execute(request(label(mark=5))).status == "ok"


def test_job_running_is_rejected_without_history(history):
    deb = Debouncer(clock=lambda: 0.0)
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], history, debouncer=deb)
    with deb.running():
        outcome = pipe.execute(request(label()))
    assert outcome.status == "abgelehnt"
    assert outcome.reasons == ("Druckauftrag lief bereits",)
    assert outcome.history_id is None
    assert history.last() is None
    assert raster_heads(transport) == []


# 11
def test_cancel_before_start(history):
    transport = MemoryTransport(STATUS_OK)
    token = CancelToken()
    token.cancel()
    outcome = pipeline(transport, [], history).execute(request(label()), cancel=token)
    assert outcome.status == "abgebrochen"
    assert raster_heads(transport) == []
    assert history.get(outcome.history_id).status == "abgebrochen"


# 12
def test_cancel_between_copies(history):
    transport = MemoryTransport(STATUS_OK)
    token = CancelToken()
    progress = []

    def on_progress(done, total):
        progress.append((done, total))
        token.cancel()

    outcome = pipeline(transport, [], history).execute(
        request(label(), copies=2), cancel=token, on_progress=on_progress)
    assert outcome.status == "abgebrochen"
    assert len(outcome.results) == 1
    assert progress == [(240, 480)]
    assert history.get(outcome.history_id).status == "abgebrochen"


def test_progress_is_summed_over_jobs():
    transport = MemoryTransport(STATUS_OK)
    progress = []
    pipeline(transport, []).execute(request(label(), copies=2),
                                    on_progress=lambda d, t: progress.append((d, t)))
    assert progress == [(240, 480), (480, 480)]


# 13
class FailingBlockTransport(MemoryTransport):
    def __init__(self, responses, block_len, fail_at=2):
        super().__init__(responses)
        self.block_len = block_len
        self.fail_at = fail_at
        self.blocks = 0

    def write(self, data):
        if len(data) == self.block_len:
            self.blocks += 1
            if self.blocks == self.fail_at:
                raise TransportError("COM4: Semaphore timeout")
        super().write(data)


def test_incomplete_print_is_reported_not_raised(history):
    transport = FailingBlockTransport(STATUS_OK, block_len=256 * P.bytes_per_line)
    outcome = pipeline(transport, [], history, chunk_rows=256).execute(request(label(600)))
    assert outcome.status == "unvollständig"
    assert isinstance(outcome.error, IncompletePrint)
    entry = history.get(outcome.history_id)
    assert entry.status == "unvollständig"
    assert "unvollständig" in entry.error


# 14
def test_connection_error_is_raised_without_history(history):
    def run(fn):
        raise ConnectTimeout("Drucker nicht erreichbar")

    pipe = PrintPipeline(P, run, history=history, now=lambda: NOW)
    with pytest.raises(ConnectTimeout):
        pipe.execute(request(label()))
    assert history.last() is None


# 15
def test_history_content_and_sensitive(history):
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], history)
    meta = JobMeta(source="cli", kind="text", title="SN 274913", values={"sn": "112233274913"})
    outcome = pipe.execute(request(label(), meta=meta, copies=2))
    found = history.search("274913")
    assert [e.id for e in found] == [outcome.history_id]
    entry = found[0]
    assert entry.copies == 2
    assert entry.chained is False
    assert entry.length_mm == pytest.approx(60.0)
    assert history.head_image(entry.id) is not None

    secret = JobMeta(source="cli", kind="text", title="geheim", sensitive=True)
    outcome = pipe.execute(request(label(mark=3), meta=secret))
    assert history.head_image(outcome.history_id) is None


# 15a
def test_history_stores_single_head_without_copies_or_chain(history):
    transport = MemoryTransport(STATUS_OK)
    pipe = pipeline(transport, [], history)

    out = pipe.execute(request(label(), copies=3, chain=True))
    entry = history.get(out.history_id)
    assert entry.copies == 3
    assert entry.chained is True
    assert history.head_image(out.history_id).height == 240

    out = pipe.execute(request(label(mark=1), copies=3, chain=False))
    assert history.get(out.history_id).chained is False
    assert history.head_image(out.history_id).height == 240

    out = pipe.execute(request(label(240, mark=2), label(160, mark=3)))
    assert history.head_image(out.history_id).height == 240


# 16
def test_manager_runner():
    transport = MemoryTransport(STATUS_OK)
    slept = []
    manager = ConnectionManager(lambda: transport, P, idle_timeout_s=0,
                                lock_factory=contextlib.nullcontext, sleep=slept.append)
    try:
        pipe = PrintPipeline(P, manager_runner(manager), now=lambda: NOW)
        outcome = pipe.execute(request(label()))
        assert outcome.status == "ok"
        assert len(raster_heads(transport)) == 1
        assert outcome.printer_status.get("lid").value == "zu"
        assert slept
    finally:
        manager.close()


# 17
def test_export_chain(tmp_path):
    pipe = pipeline(MemoryTransport(), [])
    plan = pipe.plan(request(label(), label(mark=1), chain=True))
    job_rows = plan.chain.jobs[0].head.height
    assert job_rows == 2 * 240 + 18
    png = pipe.export(plan, tmp_path / "kette.png")
    with Image.open(png) as img:
        assert img.height == P.content_dots * 4
        assert img.width == job_rows * 4
    pbm = pipe.export(plan, tmp_path / "k.pbm")
    with Image.open(pbm) as img:
        assert img.height == sum(j.head.height for j in plan.chain.jobs)


# 18
def test_preview():
    pipe = pipeline(MemoryTransport(), [])
    plan = pipe.plan(request(label(), copies=2))
    img = pipe.preview(plan)
    assert img.height == P.head_dots * 2


# 19
def test_labels_from_result():
    labels = labels_from_result(render_label(LabelSpec(lines=("A",)), P))
    assert len(labels) == 1
    assert labels[0].landscape is not None
    assert labels[0].head.width == P.head_dots


def test_plan_validation():
    pipe = pipeline(MemoryTransport(), [])
    with pytest.raises(ValueError, match="Keine Labels"):
        pipe.plan(PrintRequest(labels=(), meta=JobMeta()))
    with pytest.raises(ValueError):
        pipe.plan(request(label(), copies=0))


def test_other_errors_before_connect_are_raised_without_history(history):
    def run(fn):
        raise ValueError("kaputt")

    pipe = PrintPipeline(P, run, history=history, now=lambda: NOW)
    with pytest.raises(ValueError):
        pipe.execute(request(label()))
    assert history.last() is None


class FailingRasterTransport(MemoryTransport):
    """Wirft beim Schreiben des Rasterkopfs einen Fehler; die Verbindung stand schon."""

    def write(self, data):
        if data.startswith(ESC_AT_GS_V0):
            raise ValueError("kaputt")
        super().write(data)


def test_error_after_connect_is_logged(history):
    transport = FailingRasterTransport(STATUS_OK)
    pipe = pipeline(transport, [], history)
    with pytest.raises(ValueError):
        pipe.execute(request(label()))
    entry = history.last()
    assert entry.status == "fehler"
    assert entry.error == "kaputt"


def test_history_entry_created_inside_session(history):
    transport = MemoryTransport(STATUS_OK)
    slept = []
    seen_before = []

    def run(fn):
        seen_before.append(history.last())
        session = PrinterSession(transport, P, lock=contextlib.nullcontext(), sleep=slept.append)
        with session:
            return fn(session)

    pipe = PrintPipeline(P, run, history=history, now=lambda: NOW)
    outcome = pipe.execute(request(label()))
    assert outcome.status == "ok"
    assert seen_before == [None]
    assert len(history.search()) == 1
    assert history.get(outcome.history_id).status == "ok"
