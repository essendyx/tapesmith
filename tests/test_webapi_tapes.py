"""Band, Restmeter-Rolle und Vorschub-Kalibrierung."""

from __future__ import annotations

import json

import pytest

from tapesmith.device.profile import save_calibration

from daemon_fakes import label
from tapesmith import config as config_mod
from tapesmith import paths
from tapesmith.jobs import JobMeta
from tapesmith.tape.rolls import ROLL_LENGTH_MM
from tapesmith.webapi.printing import PrintOptionsModel, submit_labels
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


# ---------- Band ----------

def test_get_tapes_has_current_and_hex_colors(api):
    client, _ctx = api
    r = client.get("/api/v1/tapes")
    assert r.status_code == 200
    body = r.json()
    assert body["current"] == "schwarz-weiss"
    by_id = {t["id"]: t for t in body["tapes"]}
    assert by_id["schwarz-weiss"]["current"] is True
    for tape in body["tapes"]:
        assert tape["background"].startswith("#") and len(tape["background"]) == 7
        assert tape["ink"].startswith("#") and len(tape["ink"]) == 7


def test_put_tapes_current_updates_config_service_and_app(api):
    client, ctx = api
    r = client.put("/api/v1/tapes/current", json={"id": "weiss-schwarz"})
    assert r.status_code == 200
    assert r.json()["current"] == "weiss-schwarz"

    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["tape"]["current"] == "weiss-schwarz"
    assert config_mod.tape_setting(ctx.service.config) == "weiss-schwarz"

    app_body = client.get("/api/v1/app").json()
    assert app_body["tape"]["id"] == "weiss-schwarz"


def test_put_tapes_current_unknown_is_404(api):
    client, _ctx = api
    r = client.put("/api/v1/tapes/current", json={"id": "nichts-vorhanden"})
    assert r.status_code == 404


# ---------- Restmeter-Rolle ----------

def test_rolls_new_consume_and_empty(api):
    client, ctx = api
    r = client.post("/api/v1/rolls/new", json={})
    assert r.status_code == 200
    current = r.json()["current"]
    assert current["tape_id"] == "schwarz-weiss"
    assert current["remaining_mm"] == pytest.approx(ROLL_LENGTH_MM, rel=0.05)

    meta = JobMeta(source="gui", kind="text", title="Rolle")
    out = submit_labels(ctx, [label(rows=40)], meta, PrintOptionsModel(job_key="roll_1"))
    assert out["status"] == "ok"

    r = client.get("/api/v1/rolls")
    after_print = r.json()["current"]
    assert after_print["used_mm"] > current["used_mm"]
    assert after_print["remaining_mm"] < current["remaining_mm"]

    r = client.post("/api/v1/rolls/empty", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["current"] is None
    assert any(item["tape_id"] == "schwarz-weiss" for item in body["all"])


def test_rolls_finished_entry_keeps_own_remaining_and_spread(api):
    """Regressionstest: eine beendete Rolle in `all` darf nicht
    die remaining_mm/spread_mm der inzwischen aktuellen Rolle desselben Bandes zeigen."""
    client, ctx = api
    store = ctx.rolls()
    tape_id = ctx.tape().id

    store.new_roll(tape_id, length_mm=1000.0)
    store.consume(49.0, tape_id=tape_id)
    store.mark_empty(tape_id=tape_id)
    store.new_roll(tape_id, length_mm=1000.0)
    store.consume(100.0, tape_id=tape_id)

    r = client.get("/api/v1/rolls")
    assert r.status_code == 200
    body = r.json()

    finished = next(item for item in body["all"] if item["used_mm"] == pytest.approx(49.0))
    assert finished["length_mm"] == pytest.approx(1000.0)
    assert finished["factor"] == pytest.approx(1.0)
    assert finished["remaining_mm"] == pytest.approx(951.0)
    assert finished["spread_mm"] == pytest.approx(0.05 * 49.0 + 1.0 * 1 + 0.02 * 1000.0)

    current = body["current"]
    assert current["used_mm"] == pytest.approx(100.0)
    assert current["remaining_mm"] != finished["remaining_mm"]
    assert current["spread_mm"] != finished["spread_mm"]


# ---------- Vorschub-Kalibrierung ----------

def test_calibration_length_saves_factor(api):
    client, _ctx = api
    r = client.post("/api/v1/calibration/length", json={"measured_mm": 98.5})
    assert r.status_code == 200
    body = r.json()
    assert body["length_factor"] == pytest.approx(1.0152, abs=1e-4)

    cal_path = paths.calibration_path()
    saved = json.loads(cal_path.read_text(encoding="utf-8"))
    assert saved["length_factor"] == pytest.approx(1.0152, abs=1e-4)

    r = client.get("/api/v1/calibration")
    assert r.status_code == 200
    assert r.json()["length_factor"] == pytest.approx(1.0152, abs=1e-4)


def test_calibration_length_verrechnet_mit_bisherigem_faktor(api):
    # Das Lineal wird mit dem aktuellen Faktor gedruckt: der neue Faktor ist alt * 100 / gemessen.
    client, _ctx = api
    save_calibration(paths.calibration_path(), length_factor=1.0204)
    r = client.post("/api/v1/calibration/length", json={"measured_mm": 99.0})
    assert r.status_code == 200
    assert r.json()["length_factor"] == pytest.approx(1.0204 * 100 / 99.0, abs=1e-4)


def test_calibration_length_reset_entfernt_faktor(api):
    client, _ctx = api
    save_calibration(paths.calibration_path(), length_factor=1.0204, leader_mm=8.0)
    r = client.delete("/api/v1/calibration/length")
    assert r.status_code == 200
    assert r.json()["length_factor"] == 1.0              # Wert aus dem Geräteprofil
    saved = json.loads(paths.calibration_path().read_text(encoding="utf-8"))
    assert "length_factor" not in saved
    assert saved["leader_mm"] == 8.0                     # übrige Kalibrierung bleibt


def test_calibration_length_rejects_zero(api):
    client, _ctx = api
    r = client.post("/api/v1/calibration/length", json={"measured_mm": 0})
    assert r.status_code == 422
