"""Dekodiert Druckerantworten (1A <typ> <daten>). Bedeutungen kommen aus dem Geräteprofil
(Beispiel P12: Deckelcode invertiert), ohne Profil gelten die generischen DEFAULT_CODES."""

from dataclasses import dataclass
from tapesmith.i18n import _t

StatusCodes = dict[str, dict[int, str]]

DEFAULT_CODES: StatusCodes = {                   # generisch laut phomymo (bisheriges Verhalten)
    "lid": {0x98: "offen", 0x99: "zu"},
    "paper": {0x88: "leer"},
    "media": {0x0B: "endlos", 0x26: "Marken"},
}


@dataclass(frozen=True)
class StatusMessage:
    kind: str
    raw: bytes
    value: str | int | None
    text: str


def _single(typ: int, b: int, codes: StatusCodes) -> tuple[str, str | int | None, str]:
    if typ == 0x04:
        return "battery", b, _t("Akku {b} %", b=b) if b <= 100 else _t("Akku Sondercode {b:02x}", b=b)
    if typ == 0x05:
        state = codes.get("lid", {}).get(b, f"{b:02x}")
        return "lid", state, _t("Deckel {state}", state=state)
    if typ == 0x06:
        state = codes.get("paper", {}).get(b, "ok")
        return "paper", state, _t("Band {state}", state=state)
    if typ == 0x09:
        return "auto_off", b, _t("Auto-Aus {b}", b=b)
    if typ == 0x0C:
        state = codes.get("media", {}).get(b, "Lücken")
        return "media", state, _t("Medium {state}", state=state)
    if typ == 0x03:
        return "overheat", b, _t("Überhitzung {b:02x}", b=b)
    return "unknown", None, _t("unbekannt 1a{typ:02x}{b:02x}", typ=typ, b=b)


def decode(buf: bytes, codes: StatusCodes | None = None) -> list[StatusMessage]:
    codes = DEFAULT_CODES if codes is None else codes
    out: list[StatusMessage] = []
    i = 0
    while i < len(buf):
        if buf[i] != 0x1A:
            j = buf.find(b"\x1a", i)
            j = len(buf) if j < 0 else j
            out.append(StatusMessage("unknown", buf[i:j], None, _t("Rohdaten {hex}", hex=buf[i:j].hex())))
            i = j
            continue
        if i + 2 >= len(buf) and not (i + 1 < len(buf) and buf[i + 1] == 0x08):
            out.append(StatusMessage("unknown", buf[i:], None, f"abgeschnitten {buf[i:].hex()}"))
            break
        typ = buf[i + 1]
        if typ == 0x07 and i + 5 > len(buf):
            out.append(StatusMessage("unknown", buf[i:], None, f"abgeschnitten {buf[i:].hex()}"))
            break
        if typ == 0x07 and i + 5 <= len(buf):
            raw = buf[i:i + 5]
            version = ".".join(str(x) for x in raw[2:5])
            out.append(StatusMessage("firmware", raw, version, f"Firmware {version}"))
            i += 5
        elif typ == 0x08:
            j = buf.find(b"\x1a", i + 2)
            j = len(buf) if j < 0 else j
            raw = buf[i:j]
            serial = raw[2:].decode("ascii", "backslashreplace")
            out.append(StatusMessage("serial", raw, serial, _t("Seriennummer {serial}", serial=serial)))
            i = j
        else:
            kind, value, text = _single(typ, buf[i + 2], codes)
            out.append(StatusMessage(kind, buf[i:i + 3], value, text))
            i += 3
    return out
