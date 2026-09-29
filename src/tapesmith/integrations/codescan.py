"""Seriennummer vom Aufkleber scannen: Barcode-/DataMatrix-/QR-Suche über zxing-cpp und
eine Heuristik, die die wahrscheinliche Seriennummer vorschlägt.

`scan(data)` ist der einzige Einstiegspunkt für Routen/CLI: Bild laden (EXIF-Drehung, Größe
prüfen), mehrere Bildvarianten nach Codes durchsuchen, Kandidaten bewerten. zxing-cpp wird erst
hier geladen (render.zxing); fehlt es, meldet `scan` `DecoderUnavailable` (decoder.unavailable).
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from io import BytesIO
from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageChops, ImageOps

from tapesmith.render import zxing
from tapesmith.templates.serial import SerialNotDerivable, clean_serial, parse_by_id
from tapesmith.i18n import _t

MAX_PIXELS = 40_000_000
MAX_BYTES = 15 * 1024 * 1024

_MAX_LONG_EDGE = 2000
_SMALL_EDGE = 800
_GS = "\x1d"

_PREFIX_RE = re.compile(r"^\s*(?:S/N|S\.N\.|Serial\s*No\.?|Serial|SN)\s*:?\s*", re.IGNORECASE)
_BY_ID_RE = re.compile(r"^(?:ata-|nvme-|scsi-|wwn-)")
_AI_PAREN_RE = re.compile(r"\((\d{2,4})\)([^()]*)")
_AI_PREFIXES = ("]d2", "]C1", "]e0", "]Q3")
_AI_FIXED_LEN = {"01": 14, "11": 6, "17": 6}
_AI_VARIABLE = {"10", "21"}

_ARTICLE_FORMATS = {"EAN8": "EAN", "EAN13": "EAN", "UPCA": "UPC", "UPCE": "UPC"}
_GOOD_FORMATS = {"Code128": 20, "Code39": 20, "DataMatrix": 20, "QRCode": 5}

_SERIAL_CHARS_RE = re.compile(r"^[A-Z0-9-]+$")


@dataclass(frozen=True)
class CodeHit:
    text: str
    format: str  # zxingcpp-Formatname, z. B. "Code128", "DataMatrix", "QRCode", "EAN13"
    position: tuple[int, int, int, int] | None  # umschließendes Rechteck x, y, w, h im Originalbild


@dataclass(frozen=True)
class SerialCandidate:
    serial: str  # bereinigt (templates.serial.clean_serial)
    score: int  # höher = wahrscheinlicher
    reason: str  # deutsch, z. B. "GS1 (21) Seriennummer", "Präfix S/N", "Code128", "EAN: eher Artikelnummer"
    hit: CodeHit


@dataclass(frozen=True)
class ScanResult:
    hits: tuple[CodeHit, ...]
    candidates: tuple[SerialCandidate, ...]  # absteigend nach score, je Seriennummer einmal
    best: SerialCandidate | None
    width: int
    height: int


def load_image(data: bytes) -> Image.Image:
    """Öffnet ein Bild aus Bytes, wendet die EXIF-Drehung an und prüft die Größe."""
    if len(data) > MAX_BYTES:
        raise ValueError(_t("Bild zu groß (max. {value} MB)", value=MAX_BYTES // (1024 * 1024)))
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(_t("Datei ist kein lesbares Bild")) from exc
    img = ImageOps.exif_transpose(img)
    if img.width * img.height > MAX_PIXELS:
        raise ValueError(_t("Bild zu groß ({width}×{height} Punkte, max. {max_pixels} Pixel)", width=img.width, height=img.height, max_pixels=MAX_PIXELS))
    return img


@lru_cache(maxsize=1)
def _read_params(read_barcodes) -> frozenset[str]:
    return frozenset(inspect.signature(read_barcodes).parameters)


def _read(image: Image.Image) -> list:
    read_barcodes = zxing.require().read_barcodes
    params = _read_params(read_barcodes)
    kwargs: dict = {}
    if "try_rotate" in params:
        kwargs["try_rotate"] = True
    if "try_downscale" in params:
        kwargs["try_downscale"] = True
    return read_barcodes(image, **kwargs)


def _bbox_from_position(position) -> tuple[int, int, int, int]:
    xs = (position.top_left.x, position.top_right.x, position.bottom_right.x, position.bottom_left.x)
    ys = (position.top_left.y, position.top_right.y, position.bottom_right.y, position.bottom_left.y)
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return (x0, y0, x1 - x0, y1 - y0)


def _identity(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return box


def _scale_transform(orig_w: int, orig_h: int, new_w: int, new_h: int):
    fx = orig_w / new_w if new_w else 1.0
    fy = orig_h / new_h if new_h else 1.0

    def transform(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, y, w, h = box
        return (round(x * fx), round(y * fy), round(w * fx), round(h * fy))

    return transform


def _rotate90_transform(orig_w: int, orig_h: int):
    rh = orig_w  # Höhe des um 90 Grad gedrehten Bilds = Breite des Originals

    def transform(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        rx, ry, bw, bh = box
        x1, y1 = rh - 1 - ry, rx
        x2, y2 = rh - 1 - (ry + bh), rx + bw
        x0, x1b = (x1, x2) if x1 <= x2 else (x2, x1)
        y0, y1b = (y1, y2) if y1 <= y2 else (y2, y1)
        return (x0, y0, x1b - x0, y1b - y0)

    return transform


def _variants(img: Image.Image):
    base = img.convert("L")
    w, h = base.size
    out = [(base, _identity), (ImageOps.autocontrast(base), _identity)]

    long_edge = max(w, h)
    if long_edge > _MAX_LONG_EDGE:
        scale = _MAX_LONG_EDGE / long_edge
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        resized = base.resize(new_size, Image.LANCZOS)
        out.append((resized, _scale_transform(w, h, *new_size)))

    if min(w, h) < _SMALL_EDGE:
        big_size = (w * 2, h * 2)
        big = base.resize(big_size, Image.LANCZOS)
        out.append((big, _scale_transform(w, h, *big_size)))

    out.append((ImageChops.invert(base), _identity))
    out.append((base.rotate(90, expand=True), _rotate90_transform(w, h)))
    return out


def decode(img: Image.Image) -> list[CodeHit]:
    """Sucht in mehreren Bildvarianten nach Codes; Treffer über (text, format) entdoppelt.
    Ohne Decoder `zxing.DecoderUnavailable`."""
    zxing.require()
    seen: dict[tuple[str, str], CodeHit] = {}
    for variant_img, transform in _variants(img):
        for result in _read(variant_img):
            text = result.text
            if not text:
                continue
            fmt = result.format.name
            key = (text, fmt)
            if key in seen:
                continue
            try:
                box = transform(_bbox_from_position(result.position))
            except Exception:
                box = None
            seen[key] = CodeHit(text=text, format=fmt, position=box)
    return list(seen.values())


def _parse_gs1_elements(raw: str) -> dict[str, str]:
    elements: dict[str, str] = {}
    i, n = 0, len(raw)
    while i < n:
        if raw[i] == _GS:
            i += 1
            continue
        ai = raw[i : i + 2]
        if not ai.isdigit():
            break
        if ai in _AI_FIXED_LEN:
            length = _AI_FIXED_LEN[ai]
            elements[ai] = raw[i + 2 : i + 2 + length]
            i += 2 + length
        else:
            j = raw.find(_GS, i + 2)
            if j == -1:
                elements[ai] = raw[i + 2 :]
                i = n
            else:
                elements[ai] = raw[i + 2 : j]
                i = j + 1
    return elements


def gs1_serial(text: str) -> str | None:
    """GS1-Element (21) aus '(01)…(21)SERIAL' oder aus Rohdaten mit FNC1/GS bzw. ']d2'/']C1'-Präfix."""
    if not text:
        return None
    body = text
    has_prefix = False
    for prefix in _AI_PREFIXES:
        if body.startswith(prefix):
            body = body[len(prefix) :]
            has_prefix = True
            break
    if "(" in body and ")" in body:
        for ai, value in _AI_PAREN_RE.findall(body):
            if ai == "21":
                value = value.strip()
                return value or None
        return None
    if not has_prefix and _GS not in text:
        return None
    elements = _parse_gs1_elements(body.lstrip(_GS))
    value = elements.get("21")
    return value or None


def _base_serial_and_bonus(text: str) -> tuple[str, int, str, bool]:
    """Roh-Seriennummer (noch ungereinigt), Bonuspunkte, Grund und Leerzeichen-Flag aus GS1/Präfix/by-id.

    Das Leerzeichen-Flag wird auf dem Text VOR `clean_serial` ermittelt, weil `clean_serial`
    jedes Leerzeichen entfernt (auch eingebettete, nicht nur am Rand) und die Prüfung danach
    daher nie anschlagen könnte.
    """
    gs1 = gs1_serial(text)
    if gs1:
        return gs1, 100, _t("GS1 (21) Seriennummer"), bool(re.search(r"\s", gs1))
    prefix_match = _PREFIX_RE.match(text)
    if prefix_match:
        stripped = text[prefix_match.end() :]
        return stripped, 60, _t("Präfix S/N"), bool(re.search(r"\s", stripped))
    if _BY_ID_RE.match(text.strip()):
        try:
            disk_id = parse_by_id(text.strip())
        except SerialNotDerivable:
            pass
        else:
            return disk_id.serial, 40, _t("by-id-Name"), bool(re.search(r"\s", disk_id.serial))
    return text, 0, "", bool(re.search(r"\s", text))


def candidates(hits: Sequence[CodeHit]) -> list[SerialCandidate]:
    """Bewertet jeden Treffer und liefert je Seriennummer den besten Kandidaten, absteigend."""
    best_by_serial: dict[str, SerialCandidate] = {}
    for hit in hits:
        raw_serial, score, reason_text, had_space = _base_serial_and_bonus(hit.text)
        serial = clean_serial(raw_serial)
        reasons = [reason_text] if reason_text else []

        if hit.format in _GOOD_FORMATS:
            score += _GOOD_FORMATS[hit.format]
            reasons.append(hit.format if hit.format != "QRCode" else "QR")
        elif hit.format in _ARTICLE_FORMATS:
            score -= 60
            reasons.append(_t("{value}: eher Artikelnummer", value=_ARTICLE_FORMATS[hit.format]))

        if serial.lower().startswith(("http://", "https://")) or had_space:
            score -= 80
            reasons.append(_t("URL oder Text mit Leerzeichen: eher kein Etikett-Code"))

        if 6 <= len(serial) <= 24 and _SERIAL_CHARS_RE.match(serial):
            score += 10
        else:
            score -= 40

        candidate = SerialCandidate(serial=serial, score=score, reason=", ".join(reasons) or "-", hit=hit)
        current = best_by_serial.get(serial)
        if current is None or candidate.score > current.score:
            best_by_serial[serial] = candidate

    return sorted(best_by_serial.values(), key=lambda c: -c.score)


def scan(data: bytes) -> ScanResult:
    img = load_image(data)
    hits = decode(img)
    cands = candidates(hits)
    best = cands[0] if cands and cands[0].score > 0 else None
    return ScanResult(hits=tuple(hits), candidates=tuple(cands), best=best, width=img.width, height=img.height)
