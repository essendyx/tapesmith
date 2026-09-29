"""Tests für `tapesmith.mcpserver.tools` (reine Logik, Fake-Backend, nie ein echter Druck)."""

from __future__ import annotations

import base64
import copy

import pytest

from automation_fakes import DEFAULT_OUTCOME, default_render, default_templates, field_json, queue_json, \
    queued_job, status_json, template_summary
from tapesmith.mcpserver.tools import P12Tools, PreviewCache

RASTER_A = base64.b64encode(b"raster-a").decode("ascii")
RASTER_B = base64.b64encode(b"raster-b").decode("ascii")
DESIGN = b"design-png"


def _render(raster: str = RASTER_A, **changes) -> dict:
    data = default_render("Gefriergut")
    data["preview"]["raster_png"] = raster
    data["preview"]["design_png"] = base64.b64encode(DESIGN).decode("ascii")
    data["values"] = {"inhalt": "Gulasch"}
    for key, value in changes.items():
        data[key] = value
    return data


class FakeBackend:
    def __init__(self, *, render: dict | None = None, outcome: dict | None = None, limit: int = 5,
                 templates: list[dict] | None = None, queue: dict | None = None, history: list[dict] | None = None):
        self.renders = [render if render is not None else _render()]
        self.outcome = outcome if outcome is not None else dict(DEFAULT_OUTCOME)
        self.limit = limit
        self.template_list = templates if templates is not None else default_templates()
        self.queue_value = queue if queue is not None else queue_json()
        self.history_value = history if history is not None else []
        self.render_calls: list[tuple[dict, dict | None]] = []
        self.print_calls: list[tuple[dict, dict | None]] = []

    def templates(self):
        return copy.deepcopy(self.template_list)

    def render(self, source, options):
        self.render_calls.append((source, options))
        index = min(len(self.render_calls) - 1, len(self.renders) - 1)
        return copy.deepcopy(self.renders[index])

    def print(self, source, options):
        self.print_calls.append((source, options))
        return copy.deepcopy(self.outcome)

    def status(self):
        return status_json()

    def history(self, limit, query):
        return copy.deepcopy(self.history_value[:limit])

    def queue(self):
        return copy.deepcopy(self.queue_value)

    def copy_limit(self):
        return self.limit

    def limits_text(self):
        return f"höchstens {self.limit} Kopien je Auftrag, Labels bis 150 mm"


def _tools(**kw) -> tuple[P12Tools, FakeBackend]:
    backend = FakeBackend(**kw)
    return P12Tools(backend), backend


# ---------------------------------------------------------------- Vorlagen


def test_list_templates_filtert_und_formt():
    tools, _ = _tools()
    everything = tools.list_templates()
    assert [t["name"] for t in everything] == ["gefriergut", "eigentum"]
    found = tools.list_templates("GEFRIER")
    assert [t["name"] for t in found] == ["gefriergut"]
    entry = found[0]
    assert set(entry) == {"name", "description", "category", "fields"}
    assert entry["fields"][0] == {"id": "inhalt", "label": "Inhalt", "type": "input", "required": True,
                                  "choices": [], "default": ""}
    assert tools.list_templates("werkzeug")[0]["name"] == "eigentum"
    assert tools.list_templates("haushalt") == everything
    assert tools.list_templates("gibtsnicht") == []


def test_list_templates_ohne_geheime_werte():
    secret = field_json("pin", "PIN", default="1234", secret=True)
    tools, _ = _tools(templates=[template_summary("wlan", [secret], description="WLAN")])
    field = tools.list_templates()[0]["fields"][0]
    assert field["default"] is None
    assert "1234" not in repr(tools.list_templates())


# ---------------------------------------------------------------- Vorschau


def test_label_preview_vorlage_ok():
    tools, backend = _tools()
    result, png = tools.label_preview(template="gefriergut", values={"inhalt": "Gulasch"})
    assert result["ok"] is True
    assert isinstance(result["preview_id"], str) and len(result["preview_id"]) == 16
    assert png == DESIGN
    assert result["title"] == "Gefriergut"
    assert result["needs_confirmation"] is False
    assert result["reasons"] == []
    assert result["values"] == {"inhalt": "Gulasch"}
    source, options = backend.render_calls[0]
    assert source == {"kind": "template", "template": "gefriergut", "values": {"inhalt": "Gulasch"}}
    assert options == {"copies": 1}


@pytest.mark.parametrize("kwargs", [
    {},
    {"template": "gefriergut", "text": ["A"]},
    {"text": ["1", "2", "3", "4"]},
    {"text": []},
    {"text": ["A", 5]},
])
def test_label_preview_ungueltige_quelle(kwargs):
    tools, backend = _tools()
    with pytest.raises(ValueError):
        tools.label_preview(**kwargs)
    assert backend.render_calls == []


def test_label_preview_nicht_druckbar():
    render = _render(ok=False, preview=None, errors=["Pflichtfeld inhalt fehlt"])
    tools, _ = _tools(render=render)
    result, png = tools.label_preview(template="gefriergut")
    assert result["ok"] is False
    assert result["errors"] == ["Pflichtfeld inhalt fehlt"]
    assert "preview_id" not in result
    assert png is None


def test_kopiengrenze():
    tools, backend = _tools()
    result, _ = tools.label_preview(text=["A"], copies=5)
    assert result["ok"] is True and result["preview_id"]
    calls = len(backend.render_calls)
    for bad in (6, 0, True, "2"):
        with pytest.raises(ValueError, match="1 bis 5"):
            tools.label_preview(text=["A"], copies=bad)
    assert len(backend.render_calls) == calls


def test_kopiengrenze_aus_backend():
    tools, backend = _tools(limit=3)
    with pytest.raises(ValueError, match="1 bis 3"):
        tools.label_preview(text=["A"], copies=4)
    assert backend.render_calls == []
    assert tools.label_preview(text=["A"], copies=3)[0]["ok"] is True


def test_guard_lehnt_ab_keine_preview_id():
    render = _render()
    render["preview"]["decision"] = {"allowed": False, "needs_confirmation": False,
                                     "reasons": ["Quelle mcp kann nicht bestätigen"]}
    cache = PreviewCache()
    backend = FakeBackend(render=render)
    tools = P12Tools(backend, cache)
    result, png = tools.label_preview(text=["A"])
    assert result["ok"] is False
    assert "Quelle mcp kann nicht bestätigen" in result["errors"]
    assert "preview_id" not in result
    assert "150 mm" in result["limits"]
    assert png == DESIGN
    assert len(cache) == 0


def test_band_rueckfrage_wird_mit_confirm_bestaetigt():
    tools, backend = _tools(render=_render(tape_reason="Vorlage erwartet Kunststoffband"))
    result, _ = tools.label_preview(template="gefriergut", values={"inhalt": "X"})
    assert result["ok"] is True
    assert result["needs_confirmation"] is True
    assert "Vorlage erwartet Kunststoffband" in result["reasons"]
    out = tools.label_print(result["preview_id"], confirm=True)
    assert out["printed"] is True
    assert backend.print_calls[0][1]["confirmed"] is True


# ---------------------------------------------------------------- Druck


def test_label_print_ohne_confirm_druckt_nie():
    tools, backend = _tools()
    pid = tools.label_preview(text=["A"])[0]["preview_id"]
    for confirm in (False, "true", 1, None):
        out = tools.label_print(pid, confirm=confirm)
        assert out["printed"] is False
        assert "ausdrücklichen Zustimmung" in out["message"]
    out = tools.label_print(pid)
    assert out["printed"] is False
    assert backend.print_calls == []


def test_label_print_mit_confirm_genau_einmal():
    tools, backend = _tools()
    pid = tools.label_preview(text=["A", "B"], copies=3)[0]["preview_id"]
    out = tools.label_print(pid, confirm=True)
    assert out["printed"] is True
    assert out["status"] == "ok"
    assert set(out) >= {"printed", "status", "message", "queue_id", "warnings"}
    assert len(backend.print_calls) == 1
    source, options = backend.print_calls[0]
    assert source == {"kind": "text", "lines": ["A", "B"]}
    assert options["confirmed"] is True
    assert options["copies"] == 3
    again = tools.label_print(pid, confirm=True)
    assert again["printed"] is False
    assert "unbekannt" in again["message"]
    assert len(backend.print_calls) == 1


def test_label_print_unbekannte_id():
    tools, backend = _tools()
    out = tools.label_print("deadbeefdeadbeef", confirm=True)
    assert out == {"printed": False,
                   "message": "Vorschau unbekannt oder abgelaufen: bitte label_preview neu aufrufen."}
    assert backend.print_calls == []


def test_label_print_wartet_gilt_als_gedruckt():
    outcome = dict(DEFAULT_OUTCOME, status="wartet", queue_id=7)
    tools, _ = _tools(outcome=outcome)
    pid = tools.label_preview(text=["A"])[0]["preview_id"]
    out = tools.label_print(pid, confirm=True)
    assert out["printed"] is True
    assert out["status"] == "wartet"
    assert out["queue_id"] == 7


def test_label_print_abgelehnt():
    outcome = dict(DEFAULT_OUTCOME, status="abgelehnt", reasons=["Kontingent erschöpft"])
    tools, _ = _tools(outcome=outcome)
    pid = tools.label_preview(text=["A"])[0]["preview_id"]
    out = tools.label_print(pid, confirm=True)
    assert out["printed"] is False
    assert out["status"] == "abgelehnt"
    assert out["message"].startswith("Abgelehnt:")
    assert "Kontingent erschöpft" in out["message"]


def test_label_print_digest_geaendert():
    backend = FakeBackend()
    backend.renders = [_render(RASTER_A), _render(RASTER_B)]
    tools = P12Tools(backend)
    pid = tools.label_preview(text=["A"])[0]["preview_id"]
    out = tools.label_print(pid, confirm=True)
    assert out["printed"] is False
    assert "veraltet" in out["message"]
    assert backend.print_calls == []


# ---------------------------------------------------------------- Cache


def test_preview_cache_ablauf_und_verdraengung():
    now = [100.0]
    cache = PreviewCache(ttl_s=10.0, max_entries=2, clock=lambda: now[0])
    a = cache.put({"kind": "text", "lines": ["a"]}, {"copies": 1}, "da")
    assert cache.get(a) == ({"kind": "text", "lines": ["a"]}, {"copies": 1}, "da")
    now[0] += 10.5
    assert cache.get(a) is None
    b = cache.put({"b": 1}, {}, "db")
    c = cache.put({"c": 1}, {}, "dc")
    d = cache.put({"d": 1}, {}, "dd")
    assert cache.get(b) is None
    assert cache.get(c) is not None and cache.get(d) is not None
    assert cache.get("gibtsnicht") is None
    assert len({b, c, d}) == 3


# ---------------------------------------------------------------- Zustand


def test_printer_status():
    tools, _ = _tools()
    assert tools.printer_status() == {"text": "P12 · verbunden (COM4) · Akku 75 %", "state": "verbunden",
                                      "detail": ""}


def test_print_history():
    entry = {"id": 3, "created": "2026-09-28T10:00:00", "source": "mcp", "kind": "template", "title": "Gulasch",
             "template": "gefriergut", "values": {"inhalt": "Gulasch"}, "copies": 2, "status": "ok",
             "sensitive": False}
    tools, _ = _tools(history=[entry])
    assert tools.print_history() == [{"id": 3, "created": "2026-09-28T10:00:00", "title": "Gulasch",
                                      "template": "gefriergut", "source": "mcp", "status": "ok", "copies": 2}]
    with pytest.raises(ValueError):
        tools.print_history(limit=0)


def test_queue_list_fehlerfeld():
    queue = queue_json([queued_job(1, last_error="Drucker aus"), queued_job(2, last_error="")])
    tools, _ = _tools(queue=queue)
    out = tools.queue_list()
    assert out["paused"] is False
    assert out["waiting_reason"] == ""
    assert out["jobs"][0] == {"id": 1, "state": "wartet", "title": "Test", "source": "api",
                              "created": "2026-09-28T10:00:00", "error": "Drucker aus"}
    assert out["jobs"][1]["error"] is None
