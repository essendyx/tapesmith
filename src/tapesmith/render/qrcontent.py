"""QR-Inhaltsassistent: URL, Text, WLAN und vCard bauen und die Lesbarkeit auf dem Band prüfen.

Die Lesbarkeitsregel steckt einheitlich in `render.qr.render_qr` (Modul < 2 Punkte oder
fehlgeschlagener Selbsttest -> Ablehnung, Modul < 3 Punkte -> Warnung). `capacity_report`
ruft nur noch `render_qr` und reicht dessen Ergebnis/Ausnahme weiter, ohne eigene
Modul-Prüfung: eine `ValueError` aus `render_qr` wird in dieselbe deutschsprachige
Fehlermeldung übersetzt (Version per segno ermittelt, sonst "?").
"""

from collections.abc import Sequence
from dataclasses import dataclass

import segno

from tapesmith.device.profile import DeviceProfile
from tapesmith.render.compose import LabelSpec
from tapesmith.render.qr import WARN_MODULE_DOTS, render_qr, unreadable_error
from tapesmith.render.zxing import NOT_READ_WARNING
from tapesmith.templates.fill import REDACTED
from tapesmith.i18n import _t


@dataclass(frozen=True)
class QrContent:
    kind: str  # "url" | "text" | "wifi" | "vcard"
    data: str  # exakter QR-Inhalt
    display: str  # für Verlauf/Anzeige, Secrets maskiert (REDACTED)
    secret: bool
    # Nicht geheime Bauparameter für den Nachdruck ohne Klartext (WLAN: ssid/security/hidden)
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class QrCapacity:
    version: int
    error: str  # tatsächlich verwendetes Level ("L"/"M"/…), wie segno es meldet
    module_dots: int
    decodes: bool
    warnings: tuple[str, ...]

    def text(self) -> str:
        if self.decodes:
            status = _t("Selbsttest ok")
        elif _t(NOT_READ_WARNING) in self.warnings:
            status = _t("nicht rückgelesen (Decoder nicht verfügbar)")
        else:
            status = _t("Selbsttest fehlgeschlagen")
        return _t("QR Version {version}-{error}, Modul {module_dots} Punkte, {status}", version=self.version, error=self.error, module_dots=self.module_dots, status=status)


def url_content(url: str, uppercase: bool = False) -> QrContent:
    """Baut einen URL-QR-Inhalt. `uppercase=True` schreibt den ganzen Link in Großbuchstaben,
    nur für Kurz-Links sinnvoll, deren Ziel Groß-/Kleinschreibung ignoriert."""
    link = url.strip()
    if not link:
        raise ValueError(_t("Leerer Link"))
    if " " in link:
        raise ValueError(_t("Leerzeichen im Link nicht erlaubt"))
    if "://" in link:
        scheme = link.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            raise ValueError(_t("Nur http- und https-Links sind erlaubt"))
    else:
        link = "https://" + link
    if uppercase:
        link = link.upper()
    return QrContent(kind="url", data=link, display=link, secret=False)


def text_content(text: str) -> QrContent:
    if not text:
        raise ValueError(_t("Leerer Text"))
    for ch in text:
        if ch == "\n":
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValueError(_t("Steuerzeichen im Text nicht erlaubt"))
    return QrContent(kind="text", data=text, display=text, secret=False)


def escape_wifi(value: str) -> str:
    """Maskiert `\\`, `;`, `,`, `:`, `"` mit Backslash (Backslash zuerst)."""
    for ch in ("\\", ";", ",", ":", '"'):
        value = value.replace(ch, "\\" + ch)
    return value


_WIFI_SECURITY = {"WPA": "WPA", "WPA2": "WPA", "WPA3": "WPA", "WEP": "WEP", "NOPASS": "NOPASS"}


def wifi_content(ssid: str, password: str = "", security: str = "WPA", hidden: bool = False) -> QrContent:
    sec = _WIFI_SECURITY.get(security.upper())
    if sec is None:
        raise ValueError(_t("Unbekannte Sicherheitsart '{security}' (erlaubt: WPA, WEP, nopass)", security=security))
    hidden_part = "H:true;" if hidden else ""
    if sec == "NOPASS":
        if password:
            raise ValueError(_t("Offenes WLAN (nopass) erwartet kein Passwort"))
        data = f"WIFI:T:nopass;S:{escape_wifi(ssid)};{hidden_part};"
        display = _t("WLAN {ssid}", ssid=ssid)
    else:
        if not password:
            raise ValueError(_t("{sec} braucht ein Passwort", sec=sec))
        data = f"WIFI:T:{sec};S:{escape_wifi(ssid)};P:{escape_wifi(password)};{hidden_part};"
        display = _t("WLAN {ssid} (Passwort {redacted})", ssid=ssid, redacted=REDACTED)
    params = (("ssid", ssid), ("security", sec), ("hidden", "ja" if hidden else "nein"))
    return QrContent(kind="wifi", data=data, display=display, secret=bool(password), params=params)


def _esc_vcard(value: str) -> str:
    return value.replace(";", "\\;").replace(",", "\\,")


def vcard_content(name: str, phone: str = "", email: str = "", org: str = "", url: str = "") -> QrContent:
    if not name:
        raise ValueError(_t("Name ist Pflicht"))
    for label, value in ((_t("Name"), name), (_t("Telefon"), phone), (_t("E-Mail"), email), (_t("Firma"), org), ("URL", url)):
        if "\n" in value:
            raise ValueError(_t("Zeilenumbruch in vCard-Feld '{label}' nicht erlaubt", label=label))
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{_esc_vcard(name)}", f"FN:{_esc_vcard(name)}"]
    if phone:
        lines.append(f"TEL:{_esc_vcard(phone)}")
    if email:
        lines.append(f"EMAIL:{_esc_vcard(email)}")
    if org:
        lines.append(f"ORG:{_esc_vcard(org)}")
    if url:
        lines.append(f"URL:{_esc_vcard(url)}")
    lines.append("END:VCARD")
    return QrContent(kind="vcard", data="\n".join(lines), display=_t("vCard {name}", name=name), secret=False)


def capacity_report(content: QrContent, profile: DeviceProfile, error: str = "m") -> QrCapacity:
    try:
        r = render_qr(content.data, profile.content_dots, error)
    except ValueError as exc:
        try:
            version = segno.make_qr(content.data, error=error, boost_error=False).version
        except Exception:
            version = "?"
        raise unreadable_error(version, 0) from exc
    return QrCapacity(version=r.version, error=r.error, module_dots=r.module_dots,
                      decodes=r.decodes, warnings=r.warnings)


def best_error_level(content: QrContent, profile: DeviceProfile) -> str:
    """Wählt das Fehlerkorrektur-Level für „Automatisch“ in drei Stufen:

    1. das erste Level aus ('m', 'l') mit Version <= 2 (ohne Modulwarnung),
    2. sonst das erste Level mit Modul >= `WARN_MODULE_DOTS` (sauber scanbar),
    3. sonst das erste Level, das `render_qr` überhaupt zulässt (dann mit Modulwarnung).

    Scheitern beide, wird der Fehler aus dem letzten Versuch ('l') weitergereicht (dieselbe
    Meldung wie bei `capacity_report`)."""
    caps: dict[str, QrCapacity] = {}
    last_exc: ValueError | None = None
    for level in ("m", "l"):
        try:
            caps[level] = capacity_report(content, profile, level)
        except ValueError as exc:
            last_exc = exc
    for level, cap in caps.items():
        if cap.version <= 2 and cap.module_dots >= WARN_MODULE_DOTS:
            return level
    for level, cap in caps.items():
        if cap.module_dots >= WARN_MODULE_DOTS:
            return level
    if caps:
        return next(iter(caps))
    raise last_exc


def build_qr_spec(content: QrContent, lines: Sequence[str] = (), error: str = "m",
                  max_length_mm: float | None = None) -> LabelSpec:
    return LabelSpec(lines=tuple(lines), qr=content.data, qr_error=error, max_length_mm=max_length_mm)
