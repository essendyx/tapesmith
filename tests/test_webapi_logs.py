"""Protokolle in der Web-API (/api/v1/logs) und `tapesmith.logfiles`."""

from __future__ import annotations

import pytest

from tapesmith import logfiles, paths
from webapi_fakes import close_ctx, make_client, make_token

LOGS = "/api/v1/logs"

SAMPLE = (
    "2026-09-30 10:00:00,001 INFO tapesmith.daemon: Dienst gestartet\n"
    "2026-09-30 10:00:01,002 WARNING tapesmith.web: langsam\n"
    "2026-09-30 10:00:02,003 ERROR tapesmith.print: Druck fehlgeschlagen\n"
    "Traceback (most recent call last):\n"
    "  File \"x.py\", line 1\n"
    "2026-09-30 10:00:03,004 INFO tapesmith.web: X-P12-Token: abc123geheim\n"
)


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    (paths.log_dir() / "daemon.log").write_text(SAMPLE, encoding="utf-8")
    (paths.log_dir() / "install.log").write_text("ok\n", encoding="utf-8")
    yield client, ctx
    close_ctx(ctx)


def test_list(api):
    client, _ctx = api
    body = client.get(LOGS).json()
    names = {f["name"] for f in body["files"]}
    assert names == {"daemon.log", "install.log"}
    assert body["daemon_log"] == "daemon.log"
    assert all(f["size"] > 0 and f["mtime"] > 0 for f in body["files"])


def test_read_tail_levels_and_mask(api):
    client, _ctx = api
    body = client.get(f"{LOGS}/daemon.log").json()
    texts = [line["text"] for line in body["lines"]]
    assert texts[0].endswith("Dienst gestartet")
    assert [line["level"] for line in body["lines"]] == ["INFO", "WARNING", "ERROR", "ERROR", "ERROR", "INFO"]
    assert "abc123geheim" not in client.get(f"{LOGS}/daemon.log").text
    assert body["truncated"] is False

    two = client.get(f"{LOGS}/daemon.log", params={"lines": 2}).json()
    assert len(two["lines"]) == 2 and two["truncated"] is True


def test_filter_level_and_search(api):
    client, _ctx = api
    body = client.get(f"{LOGS}/daemon.log", params={"level": "ERROR"}).json()
    assert len(body["lines"]) == 3 and body["lines"][1]["text"].startswith("Traceback")
    body = client.get(f"{LOGS}/daemon.log", params={"search": "LANGSAM"}).json()
    assert [line["level"] for line in body["lines"]] == ["WARNING"]
    assert client.get(f"{LOGS}/daemon.log", params={"level": "LAUT"}).status_code == 422


def test_download_masked(api):
    client, _ctx = api
    r = client.get(f"{LOGS}/daemon.log/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"]
    assert "Dienst gestartet" in r.text and "abc123geheim" not in r.text


@pytest.mark.parametrize("name", ["..%2Fconfig.json", "config.json", "..", "daemon.log.x", "fehlt.log",
                                  "%2E%2E%5Cconfig.json", "C:%5Cwindows%5Cwin.ini"])
def test_path_traversal_and_unknown_rejected(api, name):
    client, _ctx = api
    (paths.app_dir() / "config.json").write_text("{}", encoding="utf-8")
    assert client.get(f"{LOGS}/{name}").status_code == 404
    assert client.get(f"{LOGS}/{name}/download").status_code == 404


def test_logfiles_rejects_outside_names(tmp_path):
    (tmp_path / "a.log").write_text("x\n", encoding="utf-8")
    for name in ("../a.log", "sub/a.log", "a.txt", "", "a.log.123"):
        with pytest.raises(logfiles.LogNotFound):
            logfiles.read_log(name, log_dir=tmp_path)
    assert logfiles.read_log("a.log", log_dir=tmp_path)["lines"] == [{"text": "x", "level": None}]


def test_large_file_tail_reads_only_the_end(tmp_path):
    line = "2026-09-30 10:00:00,000 INFO tapesmith: " + "x" * 100 + "\n"
    (tmp_path / "big.log").write_text(line * 100_000 + "2026-09-30 10:00:01,000 ERROR tapesmith: ENDE\n",
                                      encoding="utf-8")
    body = logfiles.read_log("big.log", lines=3, log_dir=tmp_path)
    assert body["lines"][-1]["text"].endswith("ENDE") and len(body["lines"]) == 3
    assert body["truncated"] is True
    errors = logfiles.read_log("big.log", level="ERROR", log_dir=tmp_path)
    assert [r["text"][-4:] for r in errors["lines"]] == ["ENDE"]


def test_other_roles_forbidden(api):
    client, ctx = api
    token = make_token(ctx, "drucken")
    assert client.get(LOGS, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    client.headers.pop("X-P12-Token", None)
    assert client.get(f"{LOGS}/daemon.log").status_code == 401


def test_migrate_legacy_daemon_log(tmp_path):
    (tmp_path / "p12d.log").write_text("neu\n", encoding="utf-8")
    (tmp_path / "p12d.log.1").write_text("alt\n", encoding="utf-8")
    assert logfiles.migrate_legacy_daemon_log(tmp_path) is True
    assert (tmp_path / "daemon.log").read_text(encoding="utf-8") == "neu\n"
    assert (tmp_path / "daemon.log.1").read_text(encoding="utf-8") == "alt\n"
    assert not (tmp_path / "p12d.log").exists()
    (tmp_path / "p12d.log").write_text("später\n", encoding="utf-8")
    assert logfiles.migrate_legacy_daemon_log(tmp_path) is False
    assert (tmp_path / "daemon.log").read_text(encoding="utf-8") == "neu\n"
