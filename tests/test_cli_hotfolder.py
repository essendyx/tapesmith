"""`p12 hotfolder`: Status, `run-once`, `HttpPrinter`."""

from __future__ import annotations

import json

import httpx
import pytest

from automation_fakes import FakeFacade, default_templates
from tapesmith import cli
from tapesmith.cli_cmds import hotfolder as hotfolder_cmd


def _ok() -> dict:
    return {"status": "ok", "warnings": [], "reasons": [], "history_id": 1, "consumed_mm": 10.0,
            "results": [], "printer_status": None, "error": None, "queue_id": None, "job_key": "k",
            "title": "Test", "balance_text": ""}


# ---------- p12 hotfolder status ----------


def test_status_nennt_ordner_und_aus(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TAPESMITH_HOME", str(tmp_path))
    assert cli.main(["hotfolder", "status"]) == 0
    out = capsys.readouterr().out
    assert "Hotfolder" in out
    assert "aus" in out


# ---------- p12 hotfolder run-once mit gefälschter Fassade ----------


def test_run_once_druckt_abgelegte_datei(tmp_path, monkeypatch, capsys):
    facade = FakeFacade(templates=default_templates())
    monkeypatch.setattr(hotfolder_cmd, "HttpPrinter", lambda *a, **kw: facade)
    (tmp_path / "a.json").write_text(
        json.dumps({"template": "gefriergut", "values": {"inhalt": "Suppe"}}), encoding="utf-8")

    rc = cli.main(["hotfolder", "run-once", "--dir", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "a.json" in out
    assert (tmp_path / "done" / "a.json").exists()
    assert len(facade.printed) == 1
    assert facade.printed[0][2] == "hotfolder"


def test_run_once_kaputte_datei_ergibt_exit_1(tmp_path, monkeypatch, capsys):
    facade = FakeFacade(templates=default_templates())
    monkeypatch.setattr(hotfolder_cmd, "HttpPrinter", lambda *a, **kw: facade)
    (tmp_path / "b.json").write_text("{nicht json", encoding="utf-8")

    rc = cli.main(["hotfolder", "run-once", "--dir", str(tmp_path)])

    assert rc == 1
    out = capsys.readouterr().out
    assert "b.json" in out
    assert (tmp_path / "error" / "b.json").exists()
    assert (tmp_path / "error" / "b.json.log").exists()


# ---------- HttpPrinter selbst gegen httpx.MockTransport ----------


def _mock_client_factory(requests_log, *, templates=None):
    templates = templates if templates is not None else default_templates()

    def handler(request: httpx.Request) -> httpx.Response:
        requests_log.append(request)
        if request.method == "GET" and request.url.path == "/api/v1/templates":
            return httpx.Response(200, json={"templates": templates})
        if request.method == "POST" and request.url.path == "/api/v1/labels/print":
            return httpx.Response(200, json=_ok())
        return httpx.Response(404, json={"error": {"message": "nicht gefunden"}})  # pragma: no cover

    transport = httpx.MockTransport(handler)

    def factory(*, base_url, headers, **kwargs):
        return httpx.Client(transport=transport, base_url=base_url, headers=headers, **kwargs)

    return factory


def _fake_session():
    return {"port": 8712, "token": "sess"}


def test_httpprinter_print_sendet_kopfzeilen_und_pfad():
    requests_log: list[httpx.Request] = []
    printer = hotfolder_cmd.HttpPrinter(session_loader=_fake_session,
                                        client_factory=_mock_client_factory(requests_log))

    outcome = printer.print({"kind": "text", "lines": ["A"]}, {"copies": 1}, origin="hotfolder")

    assert outcome["status"] == "ok"
    assert len(requests_log) == 1
    request = requests_log[0]
    assert request.method == "POST"
    assert str(request.url) == "http://127.0.0.1:8712/api/v1/labels/print"
    assert request.headers["X-P12-Token"] == "sess"
    assert request.headers["X-P12-Source"] == "hotfolder"


def test_httpprinter_template_summaries_filtert_auf_namen():
    requests_log: list[httpx.Request] = []
    printer = hotfolder_cmd.HttpPrinter(session_loader=_fake_session,
                                        client_factory=_mock_client_factory(requests_log))

    result = printer.template_summaries(["gefriergut"])

    assert len(requests_log) == 1
    assert requests_log[0].method == "GET"
    assert requests_log[0].url.path == "/api/v1/templates"
    assert [t["name"] for t in result] == ["gefriergut"]
    assert any(f["id"] == "inhalt" for f in result[0]["input_fields"])


def test_httpprinter_fehlerantwort_wird_zu_runtimeerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"message": "Vorlage nicht gefunden", "hint": ""}})

    transport = httpx.MockTransport(handler)

    def factory(*, base_url, headers, **kwargs):
        return httpx.Client(transport=transport, base_url=base_url, headers=headers, **kwargs)

    printer = hotfolder_cmd.HttpPrinter(session_loader=_fake_session, client_factory=factory)

    with pytest.raises(RuntimeError, match="Vorlage nicht gefunden"):
        printer.print({"kind": "text", "lines": ["A"]}, None, origin="hotfolder")


# ---------- run-once mit echtem HttpPrinter gegen den MockTransport ----------


def _patch_real_http_printer(monkeypatch, requests_log):
    real_http_printer = hotfolder_cmd.HttpPrinter
    factory = _mock_client_factory(requests_log)

    def make_printer(*a, **kw):
        return real_http_printer(session_loader=_fake_session, client_factory=factory)

    monkeypatch.setattr(hotfolder_cmd, "HttpPrinter", make_printer)


def test_run_once_csv_mit_echtem_httpprinter(tmp_path, monkeypatch, capsys):
    requests_log: list[httpx.Request] = []
    _patch_real_http_printer(monkeypatch, requests_log)
    (tmp_path / "k.csv").write_text("#template=gefriergut\ninhalt\nSuppe\nBrot\n", encoding="utf-8")

    rc = cli.main(["hotfolder", "run-once", "--dir", str(tmp_path)])

    assert rc == 0
    print_requests = [r for r in requests_log if r.url.path == "/api/v1/labels/print"]
    assert len(print_requests) == 2
    values = [json.loads(r.content)["source"]["values"]["inhalt"] for r in print_requests]
    assert values == ["Suppe", "Brot"]
    assert (tmp_path / "done" / "k.csv").exists()


def test_run_once_txt_mit_template_ueber_echten_httpprinter(tmp_path, monkeypatch):
    requests_log: list[httpx.Request] = []
    _patch_real_http_printer(monkeypatch, requests_log)
    (tmp_path / "t.txt").write_text("#template=gefriergut\nSuppe\n", encoding="utf-8")

    rc = cli.main(["hotfolder", "run-once", "--dir", str(tmp_path)])

    assert rc == 0
    print_requests = [r for r in requests_log if r.url.path == "/api/v1/labels/print"]
    assert len(print_requests) == 1
    assert json.loads(print_requests[0].content)["source"]["values"]["inhalt"] == "Suppe"
    assert (tmp_path / "done" / "t.txt").exists()


# ---------- Zeitüberschreitung: Der Druck kann länger dauern als httpx' Standard (5 s) ----------


def test_httpprinter_nutzt_langes_lesetimeout():
    seen: dict = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_ok())),
                            **kwargs)

    printer = hotfolder_cmd.HttpPrinter(session_loader=_fake_session, client_factory=factory)
    printer.print({"kind": "text", "lines": ["A"]}, None, origin="hotfolder")

    timeout = seen["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    # Allein das Öffnen des COM-Ports dauert am echten P12 10 bis 20 s.
    assert timeout.read is None or timeout.read >= 60
    assert timeout.connect is not None and timeout.connect <= 10


def _slow_client_factory(requests_log):
    """Fake-Client, dessen Druckroute wie ein langsamer Druckdienst in die Zeitüberschreitung läuft."""
    templates = default_templates()

    def handler(request: httpx.Request) -> httpx.Response:
        requests_log.append(request)
        if request.method == "GET" and request.url.path == "/api/v1/templates":
            return httpx.Response(200, json={"templates": templates})
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)

    def factory(*, base_url, headers, **kwargs):
        return httpx.Client(transport=transport, base_url=base_url, headers=headers, **kwargs)

    return factory


def test_httpprinter_zeitueberschreitung_meldet_status_unbekannt():
    printer = hotfolder_cmd.HttpPrinter(session_loader=_fake_session, client_factory=_slow_client_factory([]))

    outcome = printer.print({"kind": "text", "lines": ["A"]}, {"copies": 3}, origin="hotfolder")

    assert outcome["status"] == "unbekannt"
    assert "Status unbekannt, bitte Verlauf prüfen" in outcome["error"]["message"]


def test_run_once_zeitueberschreitung_ist_kein_druckfehler(tmp_path, monkeypatch, capsys):
    requests_log: list[httpx.Request] = []
    real_http_printer = hotfolder_cmd.HttpPrinter
    factory = _slow_client_factory(requests_log)
    monkeypatch.setattr(hotfolder_cmd, "HttpPrinter",
                        lambda *a, **kw: real_http_printer(session_loader=_fake_session, client_factory=factory))
    (tmp_path / "b.txt").write_text("Zeile\nZeile\nZeile\n", encoding="utf-8")

    rc = cli.main(["hotfolder", "run-once", "--dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "b.txt: unklar" in out
    assert "Status unbekannt, bitte Verlauf prüfen" in out
    assert "Druck fehlgeschlagen" not in out
    # Genau ein Druckversuch: kein automatischer Neuversuch, der doppelt drucken könnte.
    assert len([r for r in requests_log if r.url.path == "/api/v1/labels/print"]) == 1
    log_text = (tmp_path / "error" / "b.txt.log").read_text(encoding="utf-8")
    assert "Status unbekannt, bitte Verlauf prüfen" in log_text
    assert "Druck fehlgeschlagen" not in log_text
