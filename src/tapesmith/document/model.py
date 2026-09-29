"""Objektmodell eines Labels: Objekte mit Box in Druckpunkten, Validierung, JSON-Format (versioniert).

Koordinaten wie `render_label` im Querformat: x entlang des Bands (0 = Labelanfang), y quer dazu
(0 = obere Kante des druckbaren Bereichs). Kein Rendern, kein Qt.
"""

import base64
import binascii
import dataclasses
import io
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from PIL import Image

from tapesmith.render.fonts import FONT_FILES
from tapesmith.render.text import ALIGNS
from tapesmith.i18n import N_, _t

DOC_VERSION = 1
OBJECT_KINDS = ("text", "qr", "code128", "datamatrix", "icon", "line", "rect", "image")
KIND_NAMES = {"text": N_("Text"), "qr": "QR", "code128": "Barcode", "datamatrix": "DataMatrix",
              "icon": "Icon", "line": N_("Linie"), "rect": N_("Rahmen"), "image": N_("Bild")}
ROTATIONS = (0, 90, 180, 270)
LENGTH_MODES = ("auto", "fixed", "max")
VALIGNS = ("top", "middle", "bottom")
LINE_DIRECTIONS = ("h", "v", "down", "up")  # down: oben links -> unten rechts; up: unten links -> oben rechts
RECT_FILLS = ("none", "solid", "stripes")
DITHERS = ("none", "floyd", "bayer")
QR_ERRORS = ("l", "m", "q", "h")
MAX_IMAGE_SIDE = 1024
EXPANDABLE = {"text": ("text",), "qr": ("data",), "code128": ("data",),
              "datamatrix": ("data",), "icon": ("icon",)}

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_ICON = re.compile(r"^(tabler|simple|user):[a-z0-9][a-z0-9_.-]*$")
_OPT_INT = int | None


class DocumentError(ValueError):
    pass


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _choice(label: str, value, allowed: tuple, what: str) -> None:
    if value not in allowed:
        raise DocumentError(_t("{label}: {what} '{value}' unbekannt (erlaubt: {items})", label=label, what=what, value=value, items=', '.join(map(str, allowed))))


def _range(label: str, value, low: int, high: int, what: str) -> None:
    if value is not None and not low <= value <= high:
        raise DocumentError(_t("{label}: {what} {value} außerhalb {low}..{high}", label=label, what=what, value=value, low=low, high=high))


@dataclass(frozen=True, kw_only=True)
class LabelObject:
    kind: ClassVar[str] = ""
    id: str
    x: int
    y: int
    w: int
    h: int
    rotation: int = 0
    mirror: bool = False
    locked: bool = False
    visible: bool = True
    name: str = ""

    @property
    def _label(self) -> str:
        return _t("Objekt '{id}'", id=self.id)

    def __post_init__(self):
        if not isinstance(self.id, str) or not _ID.match(self.id):
            raise DocumentError(
                _t("Objekt-ID '{id}' ungültig (a-z, 0-9, _ und -, Beginn mit Buchstabe)", id=self.id))
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if f.type is int and not _is_int(value):
                raise DocumentError(_t("{label}: {name} muss eine ganze Zahl sein", label=self._label, name=f.name))
            if f.type == _OPT_INT and value is not None and not _is_int(value):
                raise DocumentError(_t("{label}: {name} muss eine ganze Zahl oder leer sein", label=self._label, name=f.name))
            if f.type is bool and not isinstance(value, bool):
                raise DocumentError(_t("{label}: {name} muss wahr/falsch sein", label=self._label, name=f.name))
            if f.type is str and not isinstance(value, str):
                raise DocumentError(_t("{label}: {name} muss Text sein", label=self._label, name=f.name))
        if self.w < 1 or self.h < 1:
            raise DocumentError(_t("{label}: Breite und Höhe müssen mindestens 1 Punkt sein", label=self._label))
        if self.rotation not in ROTATIONS:
            raise DocumentError(_t("{label}: Drehung {rotation} ungültig (erlaubt: 0, 90, 180, 270)", label=self._label, rotation=self.rotation))


@dataclass(frozen=True, kw_only=True)
class TextObject(LabelObject):
    kind: ClassVar[str] = "text"
    text: str = ""
    font: str = "sans"
    size: int | None = None
    align: str = "left"
    valign: str = "middle"
    invert: bool = False
    vertical: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.font not in FONT_FILES:
            raise DocumentError(
                _t("{label}: Schrift '{font}' unbekannt (verfügbar: {items})", label=self._label, font=self.font, items=', '.join(FONT_FILES)))
        _choice(self._label, self.align, ALIGNS, _t("Ausrichtung"))
        _choice(self._label, self.valign, VALIGNS, _t("Ausrichtung (senkrecht)"))
        _range(self._label, self.size, 6, 400, _t("Schriftgröße"))
        if self.text.count("\n") > 2:
            raise DocumentError(_t("{label}: höchstens 3 Zeilen Text", label=self._label))


@dataclass(frozen=True, kw_only=True)
class QrObject(LabelObject):
    kind: ClassVar[str] = "qr"
    data: str = ""
    error: str = "m"
    module: int | None = None

    def __post_init__(self):
        super().__post_init__()
        _choice(self._label, self.error, QR_ERRORS, _t("Fehlerkorrektur"))
        _range(self._label, self.module, 1, 20, _t("Modulgröße"))


@dataclass(frozen=True, kw_only=True)
class Code128Object(LabelObject):
    kind: ClassVar[str] = "code128"
    data: str = ""
    module: int = 2
    show_text: bool = True
    text_size: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if not 2 <= self.module <= 8:
            raise DocumentError(
                _t("{label}: Balkenbreite {module} ungültig (mindestens 2 Punkte, höchstens 8)", label=self._label, module=self.module))
        _range(self._label, self.text_size, 6, 40, _t("Textgröße"))


@dataclass(frozen=True, kw_only=True)
class DataMatrixObject(LabelObject):
    kind: ClassVar[str] = "datamatrix"
    data: str = ""
    module: int | None = None

    def __post_init__(self):
        super().__post_init__()
        _range(self._label, self.module, 2, 20, _t("Modulgröße"))


@dataclass(frozen=True, kw_only=True)
class IconObject(LabelObject):
    kind: ClassVar[str] = "icon"
    icon: str = "tabler:star"

    def __post_init__(self):
        super().__post_init__()
        if not self.icon or not (_ICON.match(self.icon) or "{" in self.icon):
            raise DocumentError(
                _t("{label}: Icon '{icon}' ungültig (Form 'tabler:name', 'simple:name', 'user:name' oder mit {{platzhalter}})", label=self._label, icon=self.icon))


@dataclass(frozen=True, kw_only=True)
class LineObject(LabelObject):
    kind: ClassVar[str] = "line"
    direction: str = "h"
    thickness: int = 2
    dash: int = 0
    arrow_start: bool = False
    arrow_end: bool = False

    def __post_init__(self):
        super().__post_init__()
        _choice(self._label, self.direction, LINE_DIRECTIONS, _t("Richtung"))
        _range(self._label, self.thickness, 1, 20, _t("Stärke"))
        _range(self._label, self.dash, 0, 50, _t("Strichlänge"))


@dataclass(frozen=True, kw_only=True)
class RectObject(LabelObject):
    kind: ClassVar[str] = "rect"
    thickness: int = 2
    radius: int = 0
    fill: str = "none"
    stripe: int = 6

    def __post_init__(self):
        super().__post_init__()
        _choice(self._label, self.fill, RECT_FILLS, _t("Füllung"))
        _range(self._label, self.thickness, 0, 20, _t("Stärke"))
        if self.thickness == 0 and self.fill == "none":
            raise DocumentError(_t("{label}: ohne Linie (Stärke 0) ist eine Füllung nötig", label=self._label))
        _range(self._label, self.radius, 0, 40, "Radius")
        _range(self._label, self.stripe, 2, 40, _t("Streifenbreite"))


@dataclass(frozen=True, kw_only=True)
class ImageObject(LabelObject):
    kind: ClassVar[str] = "image"
    png: str = ""
    threshold: int = 128
    dither: str = "none"
    invert: bool = False
    keep_aspect: bool = True

    def __post_init__(self):
        super().__post_init__()
        if not self.png:
            raise DocumentError(_t("{label}: Bilddaten fehlen", label=self._label))
        _range(self._label, self.threshold, 0, 255, _t("Schwelle"))
        _choice(self._label, self.dither, DITHERS, _t("Rasterung"))


KIND_CLASSES: dict[str, type[LabelObject]] = {
    cls.kind: cls for cls in (TextObject, QrObject, Code128Object, DataMatrixObject,
                              IconObject, LineObject, RectObject, ImageObject)}


@dataclass(frozen=True, kw_only=True)
class LabelDocument:
    objects: tuple[LabelObject, ...] = ()
    length_mode: str = "auto"
    length_mm: float | None = None
    margin_mm: float = 1.0
    mirror: bool = False
    rotate180: bool = False

    def __post_init__(self):
        if not isinstance(self.objects, tuple):
            raise DocumentError(_t("Dokument: objects muss ein Tupel von Objekten sein"))
        seen = set()
        for obj in self.objects:
            if not isinstance(obj, LabelObject) or not obj.kind:
                raise DocumentError(_t("Dokument: '{obj}' ist kein Label-Objekt", obj=obj))
            if obj.id in seen:
                raise DocumentError(_t("Objekt-ID '{id}' doppelt", id=obj.id))
            seen.add(obj.id)
        _choice(_t("Dokument"), self.length_mode, LENGTH_MODES, _t("Längenmodus"))
        if self.length_mode == "auto":
            if self.length_mm is not None:
                raise DocumentError(_t("Dokument: bei automatischer Länge darf keine Länge (mm) gesetzt sein"))
        elif not _is_number(self.length_mm) or self.length_mm <= 0:
            raise DocumentError(_t("Dokument: Längenmodus '{length_mode}' braucht eine Länge (mm) > 0", length_mode=self.length_mode))
        else:
            object.__setattr__(self, "length_mm", float(self.length_mm))
        if not _is_number(self.margin_mm) or not 0 <= self.margin_mm <= 20:
            raise DocumentError(_t("Dokument: Rand {margin_mm} mm ungültig (0..20)", margin_mm=self.margin_mm))
        object.__setattr__(self, "margin_mm", float(self.margin_mm))
        for name in ("mirror", "rotate180"):
            if not isinstance(getattr(self, name), bool):
                raise DocumentError(_t("Dokument: {name} muss wahr/falsch sein", name=name))


_DOC_KEYS = ("version",) + tuple(f.name for f in dataclasses.fields(LabelDocument))


# --- JSON --------------------------------------------------------------------

def _non_default(obj) -> dict:
    out = {}
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        if f.default is dataclasses.MISSING or value != f.default or type(value) is not type(f.default):
            out[f.name] = value
    return out


def object_to_dict(obj: LabelObject) -> dict:
    data = {"kind": obj.kind}
    for key in ("id", "x", "y", "w", "h"):
        data[key] = getattr(obj, key)
    data.update({k: v for k, v in _non_default(obj).items() if k not in data})
    return data


def object_from_dict(data: dict) -> LabelObject:
    if not isinstance(data, dict):
        raise DocumentError(_t("Objekt muss ein JSON-Objekt sein, nicht {name}", name=type(data).__name__))
    kind = data.get("kind")
    if kind not in KIND_CLASSES:
        raise DocumentError(_t("Unbekannte Objektart '{kind}' (erlaubt: {items})", kind=kind, items=', '.join(OBJECT_KINDS)))
    cls = KIND_CLASSES[kind]
    names = [f.name for f in dataclasses.fields(cls)]
    label = _t("Objekt '{get}'", get=data.get('id', '?'))
    unknown = sorted(k for k in data if k != "kind" and k not in names)
    if unknown:
        raise DocumentError(_t("{label}: unbekannte Eigenschaften {unknown}", label=label, unknown=unknown))
    missing = [k for k in ("id", "x", "y", "w", "h") if k not in data]
    if missing:
        raise DocumentError(_t("{label}: Pflichtangabe fehlt: {items}", label=label, items=', '.join(missing)))
    return cls(**{k: v for k, v in data.items() if k != "kind"})


def document_to_dict(doc: LabelDocument) -> dict:
    data = {"version": DOC_VERSION}
    extra = _non_default(doc)
    extra.pop("objects", None)
    data.update(extra)
    data["objects"] = [object_to_dict(o) for o in doc.objects]
    return data


def document_from_dict(data: dict) -> LabelDocument:
    if not isinstance(data, dict):
        raise DocumentError(_t("Dokument muss ein JSON-Objekt sein"))
    version = data.get("version", 1)
    if not _is_int(version) or version < 1:
        raise DocumentError(_t("Dokument-Version '{version}' ungültig", version=version))
    if version > DOC_VERSION:
        raise DocumentError(
            _t("Dokument-Version {version} ist neuer als diese App ({doc_version}), bitte App aktualisieren", version=version, doc_version=DOC_VERSION))
    unknown = sorted(k for k in data if k not in _DOC_KEYS)
    if unknown:
        raise DocumentError(_t("Dokument: unbekannte Eigenschaften {unknown}", unknown=unknown))
    objects = data.get("objects", [])
    if not isinstance(objects, (list, tuple)):
        raise DocumentError(_t("Dokument: objects muss eine Liste sein"))
    kwargs = {k: v for k, v in data.items() if k not in ("version", "objects")}
    return LabelDocument(objects=tuple(object_from_dict(o) for o in objects), **kwargs)


def document_to_json(doc: LabelDocument) -> str:
    return json.dumps(document_to_dict(doc), indent=2, ensure_ascii=False)


def document_from_json(text: str) -> LabelDocument:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DocumentError(_t("Dokument ist kein gültiges JSON: {exc}", exc=exc)) from exc
    return document_from_dict(data)


# --- Hilfsfunktionen ---------------------------------------------------------

def texts(doc: LabelDocument) -> list[str]:
    return [getattr(o, attr) for o in doc.objects for attr in EXPANDABLE.get(o.kind, ())]


def map_texts(doc: LabelDocument, fn: Callable[[str], str]) -> LabelDocument:
    def convert(obj):
        attrs = EXPANDABLE.get(obj.kind, ())
        if not attrs:
            return obj
        return dataclasses.replace(obj, **{a: fn(getattr(obj, a)) for a in attrs})

    return with_objects(doc, [convert(o) for o in doc.objects])


def bbox(obj: LabelObject) -> tuple[int, int, int, int]:
    return (obj.x, obj.y, obj.x + obj.w, obj.y + obj.h)


def extent(doc: LabelDocument) -> int:
    return max((o.x + o.w for o in doc.objects if o.visible), default=0)


def find_object(doc: LabelDocument, object_id: str) -> LabelObject:
    for obj in doc.objects:
        if obj.id == object_id:
            return obj
    raise DocumentError(_t("Objekt '{object_id}' nicht gefunden", object_id=object_id))


def replace_object(doc: LabelDocument, obj: LabelObject) -> LabelDocument:
    find_object(doc, obj.id)
    return with_objects(doc, [obj if o.id == obj.id else o for o in doc.objects])


def with_objects(doc: LabelDocument, objects: Sequence[LabelObject]) -> LabelDocument:
    return dataclasses.replace(doc, objects=tuple(objects))


def new_id(doc: LabelDocument, kind: str) -> str:
    if kind not in KIND_CLASSES:
        raise DocumentError(_t("Unbekannte Objektart '{kind}' (erlaubt: {items})", kind=kind, items=', '.join(OBJECT_KINDS)))
    used = {o.id for o in doc.objects}
    n = 1
    while f"{kind}{n}" in used:
        n += 1
    return f"{kind}{n}"


def encode_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_png(data: str) -> Image.Image:
    try:
        raw = base64.b64decode(data, validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            return img.convert("L")
    except (binascii.Error, ValueError, TypeError, OSError, Image.DecompressionBombError) as exc:
        raise DocumentError(_t("Bilddaten nicht lesbar")) from exc


def prepare_embedded_image(image: Image.Image) -> str:
    img = image
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if "A" in img.getbands():
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, rgba)
    img = img.convert("L")
    longest = max(img.size)
    if longest > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / longest
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.Resampling.LANCZOS)
    return encode_png(img)
