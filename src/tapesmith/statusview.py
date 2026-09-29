"""Statusansicht: Texte für Status-Chip, Titelleiste, Detailpanel und Tray-Tooltip.

Nur verifizierte Werte erscheinen ohne Zusatz; der Chip zeigt ausschließlich verifizierte Werte
(Akku, Deckel offen), das Band nie. Ob ein Wert verifiziert ist, steht im Report (`verified` kommt
vom Profil des Dienstes); diese Funktion verlässt sich nur darauf. Ohne Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.status import StatusValue
from tapesmith.i18n import N_, _t

PREFIX = "P12 · "
TITLE_PREFIX = "Tapesmith: "
TOOLTIP_MAX = 127
RAW_MAX_BYTES = 48
LOW_BATTERY = 20
UNCONFIRMED = N_(" (unbestätigt)")
MISSING = N_("nicht verfügbar")

_STATES = {
    "verbunden": (N_("verbunden"), "success"),
    "getrennt": (N_("getrennt"), "secondary"),
    "verbindet": (N_("verbindet …"), "secondary"),
    "offline": (N_("nicht erreichbar"), "error"),
    "belegt": (N_("belegt"), "warning"),
    "fehler": (N_("Fehler"), "error"),
    "leased": (N_("reserviert (Einrichtung)"), "warning"),
}
# Anzeige der Rohwerte aus `protocol.status` (die Werte selbst bleiben deutsche Kennungen).
_VALUE_TEXTS = {"offen": N_("offen"), "zu": N_("zu"), "leer": N_("leer"), "endlos": N_("endlos"),
                "Marken": N_("Marken")}
_ROLE_RANK = {"success": 0, "secondary": 0, "warning": 1, "error": 2}


@dataclass(frozen=True)
class StatusView:
    chip: str            # "P12 · verbunden (COM4) · Akku 75 %"
    role: str            # "success" | "secondary" | "warning" | "error"
    title: str           # "Tapesmith: verbunden (COM4) · Akku 75 %"
    detail: str          # mehrzeilig für das Detailpanel
    tooltip: str         # Tray-Tooltip (≤ 127 Zeichen)


def age_text(then: datetime | None, now: datetime) -> str:
    if then is None:
        return _t("noch nie")
    seconds = (now - then).total_seconds()
    if seconds < 60:
        return _t("gerade eben")
    if seconds < 3600:
        return _t("vor {value} min", value=int(seconds // 60))
    return _t("vor {value} h", value=int(seconds // 3600))


def _base(state: StateInfo) -> tuple[str, str]:
    if state.leased or state.state == "leased":
        text, role = _STATES["leased"]
        return _t(text), role
    text, role = _STATES.get(state.state, (state.state, "secondary"))
    text = _t(text)
    if state.state == "verbunden" and state.transport:
        text = f"{text} ({state.transport})"
    return text, role


def _worse(role: str, other: str) -> str:
    return other if _ROLE_RANK[other] > _ROLE_RANK[role] else role


def _battery_text(value: StatusValue) -> str:
    v = value.value
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v} %" if v <= 100 else _t("Sondercode {v:02x}", v=v)
    return str(v)


def _mark(text: str, value: StatusValue) -> str:
    return text if value.verified else text + _t(UNCONFIRMED)


def _value_line(label: str, value: StatusValue | None, text=None) -> str:
    if value is None:
        return f"{label}: {_t(MISSING)}"
    if text is not None:
        shown = text(value)
    else:
        raw = str(value.value)
        shown = _t(_VALUE_TEXTS[raw]) if raw in _VALUE_TEXTS else raw
    return f"{label}: {_mark(shown, value)}"


def _raw_text(raw: bytes) -> str:
    if not raw:
        return _t("keine")
    text = raw[:RAW_MAX_BYTES].hex(" ")
    if len(raw) > RAW_MAX_BYTES:
        text += _t(" … (+{value} Bytes)", value=len(raw) - RAW_MAX_BYTES)
    return text


def _mac_line(status_mac: StatusValue | None, mac: str | None) -> str:
    if status_mac is not None and status_mac.value:
        return f"MAC: {_mark(str(status_mac.value), status_mac)}"
    if mac:
        return _t("MAC: {format_mac} (aus Konfiguration, unbestätigt)", format_mac=_format_mac(mac))
    return f"MAC: {_t(MISSING)}"


def _format_mac(mac: str) -> str:
    compact = "".join(ch for ch in mac if ch.isalnum()).upper()
    if len(compact) == 12:
        return ":".join(compact[i:i + 2] for i in range(0, 12, 2))
    return mac


def _paper_line(value: StatusValue | None) -> str:
    if value is None:
        return _t("Band: {missing}", missing=_t(MISSING))
    if value.value == "leer":
        return _t("Band: leer gemeldet (unbestätigt)")
    return _t("Band: eingelegt gemeldet (leere Rolle nicht erkennbar)")


def status_view(state: StateInfo, report: StatusReport | None, *, now: datetime,
                mac: str | None = None) -> StatusView:
    base, role = _base(state)
    chip = PREFIX + base
    status = report.status if report is not None else None
    checked_at = report.checked_at if report is not None else None
    values = status.values if status is not None else {}

    battery = values.get("battery")
    if battery is not None and battery.verified and isinstance(battery.value, int) \
            and not isinstance(battery.value, bool) and battery.value <= 100:
        chip += _t(" · Akku {value} %", value=battery.value)
        if battery.value <= LOW_BATTERY:
            role = _worse(role, "warning")
    lid = values.get("lid")
    if lid is not None and lid.verified and lid.value == "offen":
        chip += _t(" · Deckel offen")
        role = _worse(role, "warning")

    lines = [
        _t("Verbindung: {base}", base=base),
        _value_line(_t("Akku"), battery, _battery_text),
        _value_line(_t("Deckel"), lid),
        _paper_line(values.get("paper")),
        _value_line("Firmware", values.get("firmware")),
        _value_line(_t("Seriennummer"), values.get("serial")),
        _value_line(_t("Medium"), values.get("media")),
        _mac_line(values.get("mac"), mac),
        f"Transport: {state.transport or _t(MISSING)}",
        _t("Letzte Antwort: {raw_text}", raw_text=_raw_text(status.raw if status is not None else b'')),
        _t("Zuletzt abgefragt: {age_text}", age_text=age_text(checked_at, now)),
    ]
    if state.last_error:
        lines.append(_t("Letzter Fehler: {last_error}", last_error=state.last_error))

    short = chip[len(PREFIX):]
    tooltip = f"{short} · Status {age_text(checked_at, now)}"
    if len(tooltip) > TOOLTIP_MAX:
        tooltip = tooltip[:TOOLTIP_MAX - 1] + "…"
    return StatusView(chip=chip, role=role, title=TITLE_PREFIX + short, detail="\n".join(lines),
                      tooltip=tooltip)
