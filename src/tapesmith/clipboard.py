"""Zwischenablage-Erkennung: aus Text oder Bild einen Druckvorschlag ableiten und
zu druckfertigen Labels rendern.

Kein Qt hier. Genutzt von Selbsttest und Web-Oberfläche; die Tray-App übergibt die Zwischenablage
nur noch als Text an den Schnelldruck im Browser (`webui.browser.quick_route`).
Reine Vorschläge: eingefügter Text löst nie direkt einen Druck aus, sondern immer
nur diesen Vorschlag.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from urllib.parse import urlsplit

from PIL import Image

from tapesmith import paths
from tapesmith.device.profile import DeviceProfile
from tapesmith.document.render import render_spec
from tapesmith.imageinput import image_to_head
from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.pipeline import PrintLabel
from tapesmith.render.chain import plan_chain, plan_single
from tapesmith.render.compose import LabelSpec
from tapesmith.tape.profiles import TapeProfile
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.render import render_meta, render_template
from tapesmith.templates.serial import SerialNotDerivable, clean_serial, parse_by_id
from tapesmith.templates.store import find_template
from tapesmith.i18n import _t

MAX_PER_LINE_LABELS = 50
TWO_LINE_SIZE = 44
LONG_URL = 50

_LINE_BREAKS: tuple[tuple[str, str], ...] = (("\r\n", "\n"), ("\r", "\n"))
_URL_RE = re.compile(r"^(?:https?|ftp)://\S+$", re.IGNORECASE)
_WWW_RE = re.compile(r"^www\.\S+$", re.IGNORECASE)
_MAC_SEP_RE = re.compile(r"^[0-9A-Fa-f]{2}([:\-.][0-9A-Fa-f]{2}){5}$")
_MAC_PLAIN_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
_BYID_PREFIXES = ("ata-", "nvme-", "scsi-", "usb-", "wwn-", "eui.")
_SERIAL_RE = re.compile(r"^[A-Z0-9-]{8,24}$")
_SN_PREFIX_RE = re.compile(r"^\s*(?:S/N|SN)\s*:?\s*", re.IGNORECASE)


class ClipKind(str, Enum):
    EMPTY = "leer"
    IMAGE = "bild"
    URL = "url"
    IPV4 = "ipv4"
    MAC = "mac"
    BYID = "by-id"
    SERIAL = "seriennummer"
    TEXT = "text"
    TWO_LINES = "zwei_zeilen"
    MULTILINE = "mehrzeilig"


@dataclass(frozen=True)
class ClipSuggestion:
    kind: ClipKind
    title: str
    action: str  # "none" | "text" | "qr" | "template" | "image" | "lines"
    lines: tuple[str, ...] = ()
    font: str = "sans"
    font_size: int | None = None
    qr: str | None = None
    template: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    image: Image.Image | None = None
    note: str = ""


@dataclass(frozen=True)
class ClipRender:
    labels: tuple[PrintLabel, ...]
    meta: JobMeta
    preview: Image.Image
    warnings: tuple[str, ...]
    balance_text: str
    tape_reason: str | None
    counter_keys: tuple[str, ...] = ()


def normalize_text(text: str) -> tuple[str, ...]:
    """Zeilenumbrüche vereinheitlichen (CRLF/CR -> LF), Zeilen `strip()`,
    leere Randzeilen entfernen."""
    for src, dst in _LINE_BREAKS:
        text = text.replace(src, dst)
    lines = [line.strip() for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return tuple(lines)


def _hostname_without_www(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _classify_url(text: str) -> ClipSuggestion | None:
    if _WWW_RE.match(text):
        url = f"https://{text}"
    elif _URL_RE.match(text):
        url = text
    else:
        return None
    host = _hostname_without_www(url)
    note = ""
    if len(url) > LONG_URL:
        note = _t("Lange URL, QR evtl. nicht lesbar, Kurz-Link verwenden")
    return ClipSuggestion(ClipKind.URL, _t("URL → QR + Hostname"), "qr", lines=(host,), qr=url, note=note)


def _classify_ipv4(text: str) -> ClipSuggestion | None:
    if text.count(".") != 3:
        return None
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return None
    return ClipSuggestion(ClipKind.IPV4, _t("IP-Adresse erkannt"), "template",
                          template="ip-label", values={"ip": text})


def _classify_mac(text: str) -> ClipSuggestion | None:
    if _MAC_SEP_RE.match(text):
        hexonly = re.sub(r"[:\-.]", "", text)
    elif _MAC_PLAIN_RE.match(text):
        hexonly = text
    else:
        return None
    hexonly = hexonly.upper()
    mac = ":".join(hexonly[i:i + 2] for i in range(0, 12, 2))
    return ClipSuggestion(ClipKind.MAC, _t("MAC-Adresse erkannt"), "text", lines=(mac,), font="mono")


def _classify_byid(text: str) -> ClipSuggestion | None:
    if "/dev/disk/by-id/" not in text and not text.startswith(_BYID_PREFIXES):
        return None
    try:
        parse_by_id(text)
    except SerialNotDerivable as exc:
        return ClipSuggestion(ClipKind.BYID, _t("Datenträger-Name erkannt (Seriennummer nicht ableitbar)"),
                              "text", lines=(text,), note=str(exc))
    return ClipSuggestion(ClipKind.BYID, _t("Datenträger erkannt"), "template",
                          template="datentraeger", values={"sn": text})


def _classify_serial(text: str) -> ClipSuggestion | None:
    cleaned = clean_serial(text)
    if not _SERIAL_RE.match(cleaned):
        return None
    if not any(c.isdigit() for c in cleaned) or not any(c.isupper() for c in cleaned):
        return None
    no_space = " " not in text
    has_prefix = bool(_SN_PREFIX_RE.match(text))
    if not no_space and not has_prefix:
        return None
    return ClipSuggestion(ClipKind.SERIAL, _t("Seriennummer erkannt"), "template",
                          template="datentraeger", values={"sn": cleaned})


def _classify_single_line(text: str) -> ClipSuggestion:
    for classifier in (_classify_url, _classify_ipv4, _classify_mac, _classify_byid, _classify_serial):
        result = classifier(text)
        if result is not None:
            return result
    return ClipSuggestion(ClipKind.TEXT, _t("Text"), "text", lines=(text,))


def classify_clipboard(text: str | None, image: Image.Image | None = None) -> ClipSuggestion:
    """Leitet aus Zwischenablage-Inhalt (Text oder Bild) einen Druckvorschlag ab (nur ein
    Vorschlag, löst nie selbst einen Druck aus)."""
    if image is not None:
        return ClipSuggestion(ClipKind.IMAGE, _t("Bild in der Zwischenablage"), "image", image=image)

    lines = normalize_text(text) if text else ()
    if not lines:
        return ClipSuggestion(ClipKind.EMPTY, _t("Zwischenablage ist leer"), "none")

    if len(lines) == 1:
        return _classify_single_line(lines[0])

    if len(lines) == 2:
        return ClipSuggestion(ClipKind.TWO_LINES, _t("Zwei Zeilen"), "text",
                              lines=lines, font_size=TWO_LINE_SIZE)

    note = ""
    if len(lines) > MAX_PER_LINE_LABELS:
        note = _t("Mehr als {max_per_line_labels} Zeilen, Serien-Dialog (Strg+Umschalt+V) verwenden", max_per_line_labels=MAX_PER_LINE_LABELS)
        lines = lines[:MAX_PER_LINE_LABELS]
    return ClipSuggestion(ClipKind.MULTILINE, _t("{count} Zeilen: ein Label pro Zeile?", count=len(lines)),
                          "lines", lines=lines, note=note)


def _balance_text(heads: tuple[Image.Image, ...], profile: DeviceProfile) -> str:
    if len(heads) <= 1:
        return plan_single(heads, profile).balance.text()
    single_total = plan_single(heads, profile).balance.chain_mm
    chain_total = plan_chain(heads, profile).balance.chain_mm
    return (_t("{count} Labels: ca. {single_total:.0f} mm Band einzeln · als Kette ca. {chain_total:.0f} mm", count=len(heads), single_total=single_total, chain_total=chain_total))


def render_suggestion(s: ClipSuggestion, profile: DeviceProfile, *, tape: TapeProfile | None = None,
                      source: str = "hotkey", per_line: bool = True, now: datetime | None = None,
                      counters: CounterStore | None = None) -> ClipRender:
    """Rendert einen `ClipSuggestion` zu druckfertigen Labels.

    Zählt bei `action="template"` selbst nie weiter (nur `peek` über `resolve_values`). Der
    Default `CounterStore(paths.app_dir()/"counters.json")` ist nur der Rückfall für Tests und
    direkte Bibliotheksnutzung; Produkt-Aufrufer übergeben `counters=numbering.counter_store(cfg)`
    und committen nach erfolgreichem Druck je Schlüssel aus `ClipRender.counter_keys`.
    """
    warnings: list[str] = []
    tape_reason: str | None = None
    counter_keys: tuple[str, ...] = ()

    if s.action == "none":
        raise ValueError(_t("Nichts zu drucken"))

    if s.action == "image":
        heads = (image_to_head(s.image, profile, rotate="auto", fit=True),)
        meta = JobMeta(source=source, kind="image", title=_t("Bild aus Zwischenablage"))

    elif s.action == "text":
        spec = LabelSpec(lines=s.lines, font=s.font, font_size=s.font_size)
        result = render_spec(spec, profile, tape)
        heads = (result.head,)
        warnings.extend(result.warnings)
        meta = JobMeta(source=source, kind="text", title=" ".join(s.lines), spec=spec_to_dict(spec))

    elif s.action == "qr":
        spec = LabelSpec(lines=s.lines, qr=s.qr)
        result = render_spec(spec, profile, tape)
        heads = (result.head,)
        warnings.extend(result.warnings)
        title = s.lines[0] if s.lines else (s.qr or "")
        meta = JobMeta(source=source, kind="qr", title=title, values={"url": s.qr or ""})

    elif s.action == "template":
        if not s.template:
            raise ValueError(_t("Kein Vorlagenname angegeben"))
        template = find_template(s.template)
        store = counters if counters is not None else CounterStore(paths.app_dir() / "counters.json")
        resolved = resolve_values(template, s.values, now or datetime.now(), store)
        tr = render_template(template, resolved.values, profile, tape=tape)
        heads = (tr.result.head,)
        warnings.extend(tr.warnings)
        meta = render_meta(tr, source=source)
        tape_reason = tr.tape_reason
        counter_keys = resolved.counter_keys

    elif s.action == "lines":
        if per_line:
            heads_list = []
            for line in s.lines:
                spec = LabelSpec(lines=(line,), font=s.font)
                result = render_spec(spec, profile, tape)
                heads_list.append(result.head)
                warnings.extend(result.warnings)
            heads = tuple(heads_list)
            extra = f" (+{len(s.lines) - 1})" if len(s.lines) > 1 else ""
            title = (s.lines[0] if s.lines else "") + extra
            meta = JobMeta(source=source, kind="text", title=title)
        else:
            if len(s.lines) > 3:
                raise ValueError(_t("höchstens 3 Zeilen in einem Label, {count} angegeben", count=len(s.lines)))
            spec = LabelSpec(lines=s.lines, font=s.font)
            result = render_spec(spec, profile, tape)
            heads = (result.head,)
            warnings.extend(result.warnings)
            meta = JobMeta(source=source, kind="text", title=" ".join(s.lines), spec=spec_to_dict(spec))

    else:
        raise ValueError(_t("Unbekannte Aktion: {action!r}", action=s.action))

    labels = tuple(PrintLabel(head) for head in heads)
    preview = heads[0].rotate(90, expand=True)
    balance_text = _balance_text(heads, profile)
    return ClipRender(labels=labels, meta=meta, preview=preview, warnings=tuple(warnings),
                      balance_text=balance_text, tape_reason=tape_reason, counter_keys=counter_keys)
