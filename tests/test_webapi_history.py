"""Verlauf über die Web-API."""

import pytest

from daemon_fakes import label
from tapesmith.labelmeta import qr_meta
from tapesmith.render.compose import LabelSpec
from tapesmith.render.qrcontent import wifi_content
from tapesmith.webapi.printing import PrintOptionsModel, submit_labels
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


_MARK = [0]


def _next_mark() -> int:
    _MARK[0] += 1
    return _MARK[0] % 80 + 1


def _print_text(ctx, title: str) -> int:
    from tapesmith.jobs import JobMeta

    meta = JobMeta(source="gui", kind="text", title=title)
    out = submit_labels(ctx, [label(mark=_next_mark(), rows=40)], meta, PrintOptionsModel())
    assert out["status"] == "ok", out
    return out["history_id"]


def _print_wifi(ctx) -> int:
    content = wifi_content("MeinWLAN", "geheim123", security="WPA")
    spec = LabelSpec(lines=(), qr=content.data)
    meta = qr_meta(content, source="gui", spec=spec)
    out = submit_labels(ctx, [label(mark=_next_mark(), rows=40)], meta, PrintOptionsModel())
    assert out["status"] == "ok", out
    return out["history_id"]


def test_history_list_newest_first_and_search(api):
    client, ctx = api
    id1 = _print_text(ctx, "Erstes Label")
    id2 = _print_text(ctx, "Seriennummer 112233274913")

    r = client.get("/api/v1/history")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert [e["id"] for e in entries] == [id2, id1]
    assert entries[0]["reprintable"] is True
    assert entries[0]["missing_secrets"] == []

    r = client.get("/api/v1/history", params={"query": "274913"})
    assert r.status_code == 200
    hits = r.json()["entries"]
    assert [e["id"] for e in hits] == [id2]


def test_history_get_unknown_is_404(api):
    client, _ctx = api
    r = client.get("/api/v1/history/9999")
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "NotFound"


def test_history_get_single(api):
    client, ctx = api
    entry_id = _print_text(ctx, "Einzelnes Label")
    r = client.get(f"/api/v1/history/{entry_id}")
    assert r.status_code == 200
    assert r.json()["id"] == entry_id
    assert r.json()["title"] == "Einzelnes Label"


def test_history_thumb(api):
    client, ctx = api
    entry_id = _print_text(ctx, "Miniatur-Test")
    r = client.get(f"/api/v1/history/{entry_id}/thumb.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    r = client.get("/api/v1/history/9999/thumb.png")
    assert r.status_code == 404


@pytest.mark.parametrize("fmt, magic", [
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("pdf", b"%PDF"),
    ("pbm", b"P4"),
])
def test_history_export_formats(api, fmt, magic):
    client, ctx = api
    entry_id = _print_text(ctx, "Export-Test")
    r = client.get(f"/api/v1/history/{entry_id}/export", params={"format": fmt})
    assert r.status_code == 200
    assert r.content[: len(magic)] == magic
    assert f"verlauf-{entry_id}.{fmt}" in r.headers.get("content-disposition", "")


def test_history_export_sensitive_is_404(api):
    client, ctx = api
    entry_id = _print_wifi(ctx)

    r = client.get(f"/api/v1/history/{entry_id}/export", params={"format": "png"})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Für sensible Aufträge wird kein Bild gespeichert"

    r = client.get("/api/v1/history")
    entry = next(e for e in r.json()["entries"] if e["id"] == entry_id)
    assert entry["missing_secrets"] == ["password"]
    assert entry["sensitive"] is True


def test_history_archive_requires_dir(api):
    client, ctx = api
    entry_id = _print_text(ctx, "Archiv ohne Konfiguration")
    r = client.post(f"/api/v1/history/{entry_id}/archive", json={})
    assert r.status_code == 422
    assert "archive.dir" in r.json()["error"]["message"]


def test_history_archive_with_dir(tmp_path):
    archive_dir = tmp_path / "archiv"
    client, ctx = make_client(tmp_path, config={"archive": {"dir": archive_dir.as_posix()}})
    try:
        entry_id = _print_text(ctx, "Archiv-Test")
        r = client.post(f"/api/v1/history/{entry_id}/archive", json={})
        assert r.status_code == 200
        notes = r.json()["notes"]
        assert notes and all(n.startswith("Archiviert:") for n in notes)
        year_dir = archive_dir / f"{ctx.now().year}"
        assert any(year_dir.glob("*.json"))
    finally:
        close_ctx(ctx)
