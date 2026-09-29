"""Schutzliste für Rohbefehle: klassifiziert Bytes in erlaubt / rückfrage / gesperrt.

Gesperrt ist bewusst **nur** ESC 7 (Heizparameter, `1B 37`). Konkrete Firmware-/OTA-Präfixe des
Jieli-Chips sind für den P12 nicht belegt, daher werden keine Sperrpräfixe erfunden. Alles Unbekannte
(auch mögliche OTA-/Update-Befehle) ist „rückfrage" und wird nur mit `--unsafe` **und** ausdrücklicher
Bestätigung gesendet.
"""

from dataclasses import dataclass
from tapesmith.i18n import N_, _t

LEVELS = ("erlaubt", "rückfrage", "gesperrt")

KNOWN_QUERIES = {
    0x07: "Firmware", 0x08: N_("Akku"), 0x09: N_("Seriennummer"), 0x0E: N_("Auto-Aus"), 0x11: N_("Band"),
    0x12: N_("Deckel"), 0x13: N_("unbekannt (1F1113)"), 0x19: N_("Medium"), 0x20: "MAC", 0x33: N_("Version"),
    0x38: N_("unbekannt (1F1138)"),
}

ESC_7 = bytes.fromhex("1b37")
_ESC_AT = bytes.fromhex("1b40")
_GS_V0 = bytes.fromhex("1d7630")
_STRIP_CHARS = (" ", ":", "-")


@dataclass(frozen=True)
class RawVerdict:
    level: str
    reason: str


def parse_hex(text: str) -> bytes:
    cleaned = text.strip()
    for ch in _STRIP_CHARS:
        cleaned = cleaned.replace(ch, "")
    if cleaned[:2].lower() == "0x":
        cleaned = cleaned[2:]
    if not cleaned or len(cleaned) % 2:
        raise ValueError(_t("Ungültige Hex-Eingabe: '{text}'", text=text))
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(_t("Ungültige Hex-Eingabe: '{text}'", text=text)) from exc


def classify_raw(data: bytes) -> RawVerdict:
    if ESC_7 in data:
        return RawVerdict("gesperrt", _t("ESC 7 (Heizparameter) ist gesperrt, kann den Druckkopf überhitzen"))

    if len(data) >= 3 and len(data) % 3 == 0 and all(
        data[i] == 0x1F and data[i + 1] == 0x11 for i in range(0, len(data), 3)
    ):
        codes = [data[i + 2] for i in range(0, len(data), 3)]
        if all(c in KNOWN_QUERIES for c in codes):
            names = ", ".join(_t(KNOWN_QUERIES[c]) for c in codes)
            return RawVerdict("erlaubt", _t("Abfrage {names}", names=names))

    if data == _ESC_AT:
        return RawVerdict("erlaubt", _t("ESC @ (Initialisieren)"))
    if len(data) == 3 and data[0] == 0x1B and data[1] == 0x64 and data[2] <= 20:
        return RawVerdict("erlaubt", _t("Vorschub {value}", value=data[2]))

    if len(data) == 4 and data[0] == 0x1B and data[1] == 0x4E and data[2] == 0x04:
        n = data[3]
        if 1 <= n <= 15:
            return RawVerdict("erlaubt", _t("Dichte-Kandidat M110 {n} (experimentell)", n=n))
        return RawVerdict("rückfrage", _t("Dichte-Kandidat M110 {n} außerhalb 1..15, Rückfrage nötig", n=n))
    if len(data) == 4 and data[0] == 0x1F and data[1] == 0x11 and data[2] == 0x02:
        n = data[3]
        if 1 <= n <= 15:
            return RawVerdict("erlaubt", _t("Dichte-Kandidat M02 {n} (experimentell)", n=n))
        return RawVerdict("rückfrage", _t("Dichte-Kandidat M02 {n} außerhalb 1..15, Rückfrage nötig", n=n))

    if len(data) == 3 and data[0] == 0x1F and data[1] == 0x11:
        return RawVerdict("rückfrage", _t("unbekannte Abfrage, könnte eine Einstellung ändern"))
    if len(data) > 3 and data[0] == 0x1F and data[1] == 0x11:
        return RawVerdict("rückfrage", _t("setzt evtl. eine dauerhafte Einstellung (z. B. Auto-Aus)"))

    if data[:3] == _GS_V0:
        return RawVerdict("rückfrage", _t("Rasterdaten: druckt und verbraucht Band"))

    return RawVerdict(
        "rückfrage",
        _t("unbekannter Befehl, kann persistente Einstellungen oder Firmware-Modi (Jieli) auslösen"),
    )
