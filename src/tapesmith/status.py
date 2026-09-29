"""Druckerstatus lesen, dekodieren, anzeigen und loggen; blockiert nie (nur Warnen)."""

from collections.abc import Sequence
from dataclasses import dataclass

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.status import decode
from tapesmith.i18n import N_, _t

FULL_QUERIES = ("1f1108", "1f1111", "1f1112", "1f1107", "1f1109", "1f1119", "1f110e", "1f1120")
PREFLIGHT_QUERIES = ("1f1108", "1f1111", "1f1112")

KIND_LABELS = {
    "battery": N_("Akku"), "lid": N_("Deckel"), "paper": N_("Band"), "firmware": "Firmware",
    "serial": N_("Seriennummer"), "media": N_("Medium"), "auto_off": N_("Auto-Aus"), "overheat": "1A03",
}

_SUMMARY_ORDER = ("battery", "lid", "paper", "media", "firmware", "serial")


@dataclass(frozen=True)
class StatusValue:
    kind: str
    value: str | int | None
    text: str
    verified: bool          # kind in profile.verified
    raw: bytes


@dataclass
class PrinterStatus:
    values: dict[str, StatusValue]
    unknown: list[bytes]
    raw: bytes

    def get(self, kind: str) -> StatusValue | None:
        return self.values.get(kind)

    @property
    def answered(self) -> bool:
        return bool(self.raw)

    def to_dict(self) -> dict:
        return {
            "answered": self.answered,
            "values": {
                kind: {"value": v.value, "text": v.text, "verified": v.verified, "raw": v.raw.hex()}
                for kind, v in self.values.items()
            },
            "unknown": [b.hex() for b in self.unknown],
            "raw": self.raw.hex(),
        }

    def summary(self) -> str:
        if not self.answered:
            return _t("keine Statusantwort")
        parts: list[str] = []
        for kind in _SUMMARY_ORDER:
            value = self.values.get(kind)
            if kind == "paper":
                if value is None:
                    parts.append(_t("{paper}: nicht verfügbar", paper=_t(KIND_LABELS['paper'])))
                elif value.value == "leer":
                    parts.append(_t("Band leer gemeldet (unbestätigt)"))
                else:
                    parts.append(_t("Band: eingelegt gemeldet (leere Rolle nicht erkennbar)"))
                continue
            if value is None:
                parts.append(_t("{value}: nicht verfügbar", value=_t(KIND_LABELS[kind])))
            else:
                text = value.text
                if not value.verified:
                    text += _t(" (unbestätigt)")
                parts.append(text)
        return " · ".join(parts)


def status_from_bytes(buf: bytes, profile: DeviceProfile) -> PrinterStatus:
    values: dict[str, StatusValue] = {}
    unknown: list[bytes] = []
    for m in decode(buf, profile.status_map()):
        if m.kind == "unknown":
            if m.raw:
                unknown.append(m.raw)
            continue
        values[m.kind] = StatusValue(
            kind=m.kind, value=m.value, text=m.text, verified=m.kind in profile.verified, raw=m.raw)
    return PrinterStatus(values=values, unknown=unknown, raw=bytes(buf))


def read_status(session, profile: DeviceProfile, queries: Sequence[str] = FULL_QUERIES,
                 listen_s: float = 0.15) -> PrinterStatus:
    if not getattr(session.transport, "supports_responses", True):
        return PrinterStatus(values={}, unknown=[], raw=b"")
    chunks = [session.exchange(bytes.fromhex(q)) for q in queries]
    chunks.append(session.listen(listen_s))
    return status_from_bytes(b"".join(chunks), profile)


def preflight(status: PrinterStatus, profile: DeviceProfile) -> list[str]:
    if not status.answered:
        return [_t("Keine Statusantwort. Drucker eingeschlafen? Druck wird trotzdem versucht")]
    warnings: list[str] = []
    lid = status.get("lid")
    if lid is not None and lid.value == "offen":
        warning = _t("Deckel offen gemeldet, bitte schließen")
        if not lid.verified:
            warning += _t(" (unbestätigt)")
        warnings.append(warning)
    battery = status.get("battery")
    if battery is not None and isinstance(battery.value, int):
        b = battery.value
        if b > 100:
            warnings.append(_t("Akku kritisch (Sondercode {b:02x})", b=b))
        elif b <= 10:
            warnings.append(_t("Akku kritisch ({b} %)", b=b))
        elif b <= 20:
            warnings.append(_t("Akku niedrig ({b} %)", b=b))
    paper = status.get("paper")
    if paper is not None and paper.value == "leer":
        warnings.append(_t("Band leer gemeldet (unbestätigt, der P12 meldet leere Rollen nicht zuverlässig)"))
    return warnings
