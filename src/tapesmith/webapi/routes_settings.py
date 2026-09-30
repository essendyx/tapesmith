"""Routen /api/v1 (Bereich settings).

Einstellungsseite: Schema mit Feldprüfung (`settings_schema.py`), Verbindung/Einrichtung,
Band und Restmeter-Rolle, Vorschub-Kalibrierung und Dienstinfo. Kein Qt-Import;
Verbindungsassistent-Fabriken sind hier neu angelegt.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictBool

import tapesmith
from tapesmith import config, paths
from tapesmith.device.profile import DeviceProfile, remove_calibration, save_calibration
from tapesmith.printer import PrinterSession
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.setup import run_setup
from tapesmith.tape.profiles import list_tapes
from tapesmith.tape.rolls import ROLL_LENGTH_MM
from tapesmith.transport.btports import list_bt_ports
from tapesmith.transport.resolve import open_transport
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.convert import tape_json
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.settings_schema import apply_changes, settings_json
from tapesmith.i18n import _t

router = APIRouter()

_IMPORTED_AT = time.monotonic()


class PatchSettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    changes: dict[str, Any]


class SetupBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    port: str | None = None
    test_label: StrictBool = False


class TapeCurrentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class RollsNewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tape_id: str | None = None
    length_mm: float | None = None


class RollsEmptyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    at_mm: float | None = None


class CalibrationLengthBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    measured_mm: float
    leader_mm: float | None = None
    trailer_mm: float | None = None


# ---------- Verbindungsassistent: Probe/Testdruck (Muster der früheren Qt-Einstellungsseite,
# hier Qt-frei). Über Modulvariablen in Tests ersetzbar. ----------

ProbeFactory = Callable[[str | None, float, DeviceProfile], Callable[[str], list[tuple[bytes, bytes]]]]
TestPrintFactory = Callable[[str | None, float, DeviceProfile], Callable[[str], None]]


def _default_probe(mac: str | None, connect_timeout_s: float,
                   profile: DeviceProfile) -> Callable[[str], list[tuple[bytes, bytes]]]:
    def probe(port: str) -> list[tuple[bytes, bytes]]:
        transport = open_transport(port, mac, None, open_timeout=connect_timeout_s)
        with PrinterSession(transport, profile) as session:
            return session.handshake()
    return probe


def _default_test_print(mac: str | None, connect_timeout_s: float,
                        profile: DeviceProfile) -> Callable[[str], None]:
    def test_print(port: str) -> None:
        spec = LabelSpec(lines=("Tapesmith", _t("Testdruck")), max_length_mm=40)
        head = render_label(spec, profile).head
        transport = open_transport(port, mac, None, open_timeout=connect_timeout_s)
        with PrinterSession(transport, profile) as session:
            session.print_image(head)
    return test_print


PROBE_FACTORY: ProbeFactory = _default_probe
TEST_PRINT_FACTORY: TestPrintFactory = _default_test_print


# ---------- Einstellungen ----------

@router.get("/settings")
def get_settings(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return settings_json(ctx.config())


@router.patch("/settings")
def patch_settings(body: PatchSettingsBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    changed = apply_changes(body.changes)
    ctx.service.request_reload()
    ctx.publish("config", {"keys": changed})
    return settings_json(ctx.config())


@router.get("/settings/ports")
def get_settings_ports(ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    profile = ctx.profile()
    transports: list[dict] = [
        {"value": "auto", "label": _t("Automatisch (Bluetooth-COM-Port über MAC)"), "experimental": False},
        {"value": "ble", "label": _t("Bluetooth LE ohne Kopplung"), "experimental": True},
    ]
    if "usb" in profile.experimental:
        transports.append({"value": "usb", "label": _t("USB (experimentell)"), "experimental": True})
    for port in list_bt_ports():
        if port.outgoing:
            transports.append({
                "value": port.port, "label": f"{port.port} (Bluetooth {port.mac})", "experimental": False,
            })
    current = config.setting(cfg, "transport")
    if not any(choice["value"] == current for choice in transports):
        transports.append({"value": current, "label": str(current), "experimental": False})
    return {"transports": transports}


@router.post("/settings/setup")
def post_settings_setup(body: SetupBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    owner = object()
    lease_id = ctx.service.lease(owner, 120.0)
    try:
        cfg = ctx.config()
        mac = cfg.get("mac")
        connect_timeout_s = float(config.setting(cfg, "connect_timeout_s"))
        profile = ctx.profile()
        probe = PROBE_FACTORY(mac, connect_timeout_s, profile)
        test_print = TEST_PRINT_FACTORY(mac, connect_timeout_s, profile) if body.test_label else None
        result = run_setup(mac=mac, port=body.port, probe=probe, save=config.save_config,
                           test_print=test_print)
    finally:
        ctx.service.release(lease_id)
    ctx.service.request_reload()
    ctx.publish("config", {"keys": ["transport", "mac"]})
    return {
        "ok": result.ok,
        "port": result.port,
        "mac": result.mac,
        "steps": [{"name": s.name, "ok": s.ok, "detail": s.detail, "hint": s.hint} for s in result.steps],
    }


# ---------- Band ----------

@router.get("/tapes")
def get_tapes(ctx: ApiContext = Depends(get_ctx)) -> dict:
    current = config.tape_setting(ctx.config())
    return {"tapes": [tape_json(t, current) for t in list_tapes()], "current": current}


@router.put("/tapes/current")
def put_tapes_current(body: TapeCurrentBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ids = {t.id for t in list_tapes()}
    if body.id not in ids:
        raise NotFound(_t("Band '{id}' unbekannt", id=body.id))
    config.set_setting("tape.current", body.id)
    ctx.service.request_reload()
    ctx.publish("config", {"keys": ["tape.current"]})
    return get_tapes(ctx)


# ---------- Restmeter-Rolle ----------

def _tape_name(tape_id: str) -> str:
    for tape in list_tapes():
        if tape.id == tape_id:
            return tape.name
    return tape_id


def _state_remaining_mm(state) -> float:
    """Rest der konkreten Rolle `state`, unabhaengig davon, ob sie noch die aktuelle ist."""
    return max(0.0, state.length_mm * state.factor - state.used_mm)


def _state_spread_mm(state) -> float:
    """Streuung der konkreten Rolle `state` (gleiche Formel wie `RollStore.spread_mm`)."""
    return 0.05 * state.used_mm + 1.0 * state.jobs + 0.02 * state.length_mm


def _state_summary(state) -> str:
    remaining_m = _state_remaining_mm(state) / 1000
    spread_m = _state_spread_mm(state) / 1000
    remaining_text = f"{remaining_m:.1f}".replace(".", ",")
    spread_text = f"{spread_m:.1f}".replace(".", ",")
    return _t("beendet: waren noch ca. {remaining_text} m (± {spread_text} m) uebrig", remaining_text=remaining_text, spread_text=spread_text)


def _build_roll_json(state, *, rolls, tape_name: str, finished: bool) -> dict:
    if finished:
        # Beendete Rolle: Werte aus dem uebergebenen Zustand selbst berechnen. Die
        # RollStore-Methoden remaining_mm/spread_mm/summary liefern sonst die Werte der
        # aktuell aktiven Rolle desselben Bandes (RollStore.current), nicht die dieser
        # historischen Instanz.
        remaining_mm = _state_remaining_mm(state)
        spread_mm = _state_spread_mm(state)
        summary = _state_summary(state)
    else:
        remaining_mm = rolls.remaining_mm(state.tape_id)
        spread_mm = rolls.spread_mm(state.tape_id)
        summary = rolls.summary(tape_id=state.tape_id)
    return {
        "tape_id": state.tape_id,
        "tape_name": tape_name,
        "started": state.started,
        "length_mm": state.length_mm,
        "used_mm": state.used_mm,
        "remaining_mm": remaining_mm,
        "spread_mm": spread_mm,
        "jobs": state.jobs,
        "factor": state.factor,
        "summary": summary,
    }


def _rolls_json(ctx: ApiContext) -> dict:
    rolls = ctx.rolls()
    current_tape_id = ctx.tape().id
    current_state = rolls.current(current_tape_id)
    current = (_build_roll_json(current_state, rolls=rolls, tape_name=_tape_name(current_tape_id),
                                finished=False)
              if current_state is not None else None)
    all_rolls = [_build_roll_json(state, rolls=rolls, tape_name=_tape_name(state.tape_id), finished=finished)
                for state, finished in rolls.all_rolls()]
    return {"current": current, "all": all_rolls}


@router.get("/rolls")
def get_rolls(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _rolls_json(ctx)


@router.post("/rolls/new")
def post_rolls_new(body: RollsNewBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    tape_id = body.tape_id or ctx.tape().id
    length_mm = body.length_mm if body.length_mm is not None else ROLL_LENGTH_MM
    ctx.rolls().new_roll(tape_id, length_mm, now=ctx.now())
    return _rolls_json(ctx)


@router.post("/rolls/empty")
def post_rolls_empty(body: RollsEmptyBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.rolls().mark_empty(body.at_mm, tape_id=ctx.tape().id)
    return _rolls_json(ctx)


# ---------- Vorschub-Kalibrierung ----------

def _calibration_json(ctx: ApiContext) -> dict:
    profile = ctx.profile()
    return {
        "length_factor": profile.length_factor,
        "leader_mm": profile.leader_mm,
        "trailer_mm": profile.trailer_mm,
        "content_offset": profile.content_offset,
        "content_dots": profile.content_dots,
        "verified": list(profile.verified),
        "path": str(paths.calibration_path()),
    }


@router.get("/calibration")
def get_calibration(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _calibration_json(ctx)


@router.post("/calibration/length")
def post_calibration_length(body: CalibrationLengthBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if body.measured_mm <= 0:
        raise ValueError(_t("Gemessener Wert muss größer als 0 mm sein"))
    # Das Lineal wurde mit dem aktuellen Faktor gedruckt: mit ihm verrechnen, nicht ersetzen.
    factor = round(ctx.profile().length_factor * 100.0 / body.measured_mm, 4)
    values: dict[str, float] = {"length_factor": factor}
    if body.leader_mm is not None:
        values["leader_mm"] = float(body.leader_mm)
    if body.trailer_mm is not None:
        values["trailer_mm"] = float(body.trailer_mm)
    save_calibration(paths.calibration_path(), **values)
    ctx.service.request_reload()
    ctx.publish("config", {"keys": ["calibration"]})
    return _calibration_json(ctx)


@router.delete("/calibration/length")
def delete_calibration_length(ctx: ApiContext = Depends(get_ctx)) -> dict:
    """Längenfaktor zurücksetzen (Wert aus dem Geräteprofil, meist 1,0)."""
    remove_calibration(paths.calibration_path(), "length_factor")
    ctx.service.request_reload()
    ctx.publish("config", {"keys": ["calibration"]})
    return _calibration_json(ctx)


# ---------- Dienstinfo ----------

@router.get("/daemon")
def get_daemon(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {
        "pid": os.getpid(),
        "version": tapesmith.__version__,
        "uptime_s": time.monotonic() - _IMPORTED_AT,
        "web_port": ctx.port,
        "home_key": ctx.home_key,
        "log_path": str(paths.log_dir() / "daemon.log"),
        "app_dir": str(paths.app_dir()),
    }
