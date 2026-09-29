"""Renderer für das Objektmodell: `LabelDocument` -> 1-Bit-Querformat -> Kopfbild.

Jedes Objekt wird für seine Inhaltsfläche erzeugt, gedreht/gespiegelt und in seine Box gesetzt.
Fehler einzelner Objekte werden nie geworfen, sondern als `ObjectIssue` gemeldet (Editor-Markierung,
Lint); `to_render_result` macht daraus für den Druck eine Ausnahme. Codes auf dunklem Band werden
je nach Bandprofil invertiert mit gedruckter Ruhezone innerhalb der Box. Kein Qt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import segno
from PIL import Image, ImageOps

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.model import (Code128Object, DataMatrixObject, IconObject, ImageObject,
                                     LabelDocument, LabelObject, LineObject, QrObject, RectObject,
                                     TextObject, bbox, decode_png, extent)
from tapesmith.protocol.raster import landscape_to_content, place_on_head
from tapesmith.render.barcode import render_code128
from tapesmith.render.checks import LONG_LABEL_MM, MIN_FONT_SIZE, small_font_warning
from tapesmith.render.codes import invert_with_quiet
from tapesmith.render.compose import LabelSpec, RenderResult, mm_to_rows, render_label, rows_to_mm
from tapesmith.render.datamatrix import render_datamatrix
from tapesmith.render.dither import fit_image, to_1bit
from tapesmith.render.fonts import load_font
from tapesmith.render.icons import IconMissing, render_icon
from tapesmith.render.qr import QUIET_MODULES, render_qr
from tapesmith.render.shapes import draw_line, draw_rect
from tapesmith.render.text import MAX_SIZE, MIN_SIZE, fit_text, render_text_block
from tapesmith.tape.profiles import TapeProfile
from tapesmith.i18n import N_, _t

EMPTY_TEXT = N_("Text ist leer, nicht gedruckt")
THIN_LINE = N_("1-Punkt-Linie kann bei hellem Druck verschwinden")
DARK_WARN = N_("Code auf dunklem Band: viele Scanner lesen helle Codes auf dunklem Grund nicht")
QUIET_INCOMPLETE = N_("Ruhezone auf dunklem Band unvollständig, Box vergrößern")
NOTHING = N_("Nichts zu drucken")
OUT_ACROSS = N_("Objekt ragt aus dem druckbaren Bereich (quer)")
OUT_ALONG = N_("Objekt ragt über den Labelrand")

_ROTATE = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
           270: Image.Transpose.ROTATE_90}


@dataclass(frozen=True)
class ObjectIssue:
    object_id: str | None       # None = ganzes Label
    level: str                  # "error" | "warning"
    message: str


@dataclass(frozen=True)
class CodeInfo:
    kind: str                   # "qr" | "code128" | "datamatrix"
    module_dots: int
    decodes: bool
    inverted: bool              # dunkles Band: invertiert gedruckt
    version: int | None = None  # nur QR


@dataclass(frozen=True)
class ObjectRender:
    image: Image.Image          # Modus "1", genau w×h der Box (nach Drehung/Spiegelung)
    opaque: bool                # True: ganze Box deckt ab; False: nur schwarze Pixel werden gedruckt
    issues: tuple[ObjectIssue, ...]
    font_size: int | None = None
    code: CodeInfo | None = None


@dataclass(frozen=True)
class DocumentRender:
    landscape: Image.Image
    head: Image.Image
    length_rows: int
    length_mm: float
    tape_mm: float
    boxes: dict[str, tuple[int, int, int, int]]
    font_sizes: dict[str, int]
    codes: dict[str, CodeInfo]
    issues: tuple[ObjectIssue, ...]

    @property
    def errors(self) -> tuple[ObjectIssue, ...]:
        return tuple(i for i in self.issues if i.level == "error")

    @property
    def warnings(self) -> tuple[ObjectIssue, ...]:
        return tuple(i for i in self.issues if i.level == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


class _Failed(Exception):
    """Interner Abbruch eines Objekts: wird zu einem Fehler-Issue und einer leeren Box."""


@dataclass
class _Content:
    image: Image.Image          # Modus "1", genau cw×ch
    opaque: bool = False
    font_size: int | None = None
    code: CodeInfo | None = None


def _white(w: int, h: int) -> Image.Image:
    return Image.new("1", (w, h), 255)


def _centered(image: Image.Image, cw: int, ch: int) -> Image.Image:
    out = _white(cw, ch)
    out.paste(image, ((cw - image.width) // 2, (ch - image.height) // 2))
    return out


def _is_empty_text(obj: LabelObject) -> bool:
    return isinstance(obj, TextObject) and not obj.text.strip()


# --- Text --------------------------------------------------------------------

def _vertical_block(lines: Sequence[str], font: str, size: int) -> Image.Image:
    f = load_font(font, size)
    ascent, descent = f.getmetrics()
    pitch = ascent + descent
    gap = max(2, size // 4)
    columns: list[tuple[int, list[Image.Image | None]]] = []
    for line in lines:
        cells: list[Image.Image | None] = []
        for char in line:
            if not char.strip():
                cells.append(None)
                continue
            try:
                cells.append(render_text_block([char], font, size, "center").image)
            except ValueError:
                cells.append(None)
        width = max((c.width for c in cells if c is not None), default=0)
        columns.append((width, cells))
    total_w = sum(w for w, _ in columns) + gap * max(len(columns) - 1, 0)
    total_h = max((len(cells) for _, cells in columns), default=0) * pitch
    image = _white(max(total_w, 1), max(total_h, 1))
    x = 0
    for width, cells in columns:
        for i, cell in enumerate(cells):
            if cell is not None:
                image.paste(cell, (x + (width - cell.width) // 2, i * pitch + (pitch - cell.height) // 2))
        x += width + gap
    return image


def _vertical_size(lines: Sequence[str], font: str, cw: int, ch: int) -> int | None:
    def fits(size: int) -> bool:
        block = _vertical_block(lines, font, size)
        return block.width <= cw and block.height <= ch

    if not fits(MIN_SIZE):
        return None
    lo, hi = MIN_SIZE, MAX_SIZE
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _text(obj: TextObject, cw: int, ch: int, tape, issues: list[ObjectIssue]) -> _Content:
    if not obj.text.strip():
        issues.append(ObjectIssue(obj.id, "warning", _t(EMPTY_TEXT)))
        return _Content(_white(cw, ch))
    lines = obj.text.split("\n")
    too_big = _t("Text passt nicht in die Box ({cw}×{ch} Punkte)", cw=cw, ch=ch)
    if obj.vertical:
        size = obj.size if obj.size is not None else _vertical_size(lines, obj.font, cw, ch)
        if size is None:
            raise _Failed(too_big)
        block = _vertical_block(lines, obj.font, size)
    elif obj.size is None:
        try:
            text = fit_text(lines, obj.font, max_height=ch, max_width=cw, align=obj.align)
        except ValueError as exc:
            raise _Failed(too_big) from exc
        block, size = text.image, text.font_size
    else:
        try:
            block = render_text_block(lines, obj.font, obj.size, obj.align).image
        except ValueError as exc:
            raise _Failed(too_big) from exc
        size = obj.size
    if block.width > cw or block.height > ch:
        issues.append(ObjectIssue(obj.id, "error", _t("Text größer als die Box (Schrift {size})", size=size)))
    if size < MIN_FONT_SIZE:
        issues.append(ObjectIssue(
            obj.id, "warning", small_font_warning(size)))

    tw, th = block.size
    x = {"left": 0, "center": (cw - tw) // 2, "right": cw - tw}[obj.align]
    y = {"top": 0, "middle": (ch - th) // 2, "bottom": ch - th}[obj.valign]
    if obj.invert:
        image = Image.new("1", (cw, ch), 0)
        image.paste(ImageOps.invert(block.convert("L")).convert("1"), (x, y))
        return _Content(image, opaque=True, font_size=size)
    image = _white(cw, ch)
    image.paste(block, (x, y))
    return _Content(image, font_size=size)


# --- Codes -------------------------------------------------------------------

def _place_code(obj: LabelObject, code: Image.Image, module: int, quiet: int, cw: int, ch: int,
                tape: TapeProfile | None, issues: list[ObjectIssue], *,
                two_d: bool = True) -> tuple[Image.Image, bool]:
    """Setzt den Code mittig; bei dunklem Band je nach Bandprofil invertiert mit Ruhezone."""
    mode = tape.effective_code_mode if tape is not None else "normal"
    if mode == "invert":
        image, _fits = invert_with_quiet(code, quiet, canvas=(cw, ch))
        ax = (cw - code.width) // 2
        ay = (ch - code.height) // 2
        # Bei 1D-Codes (Code128) laufen die Balken quer ohnehin über die Box: dort zählt nur längs.
        avail = min(ax, ay) if two_d else ax
        m = avail // module
        if avail >= quiet:
            pass
        elif m >= 2:
            issues.append(ObjectIssue(
                obj.id, "warning",
                _t("Ruhezone auf dunklem Band nur {m} Module: meist lesbar, vor Serieneinsatz scannen", m=m)))
        else:
            issues.append(ObjectIssue(obj.id, "warning", _t(QUIET_INCOMPLETE)))
        return image, True
    if mode == "warn":
        issues.append(ObjectIssue(obj.id, "warning", _t(DARK_WARN)))
    return _centered(code, cw, ch), False


def _qr(obj: QrObject, cw: int, ch: int, tape, issues) -> _Content:
    if not obj.data:
        raise _Failed(_t("QR ohne Inhalt"))
    side = min(cw, ch)
    try:
        if obj.module is None:
            qr = render_qr(obj.data, side, obj.error)
        else:
            n = len(segno.make_qr(obj.data, error=obj.error, boost_error=False).matrix)
            if obj.module * n > side:
                raise _Failed(_t("QR passt nicht in die Box (braucht {value} Punkte)", value=obj.module * n))
            qr = render_qr(obj.data, obj.module * n, obj.error)
    except (ValueError, segno.DataOverflowError) as exc:
        raise _Failed(str(exc)) from exc
    issues.extend(ObjectIssue(obj.id, "warning", w) for w in qr.warnings)
    image, inverted = _place_code(obj, qr.image, qr.module_dots, QUIET_MODULES * qr.module_dots,
                                  cw, ch, tape, issues)
    info = CodeInfo("qr", qr.module_dots, qr.decodes, inverted, qr.version)
    return _Content(image, opaque=inverted, code=info)


def _code_result(obj: LabelObject, result, cw: int, ch: int, tape, issues, *, two_d: bool) -> _Content:
    issues.extend(ObjectIssue(obj.id, "warning", w) for w in result.warnings)
    image, inverted = _place_code(obj, result.image, result.module_dots, result.quiet_dots,
                                  cw, ch, tape, issues, two_d=two_d)
    info = CodeInfo(result.kind, result.module_dots, result.decodes, inverted)
    return _Content(image, opaque=inverted, code=info)


def _code128(obj: Code128Object, cw: int, ch: int, tape, issues) -> _Content:
    try:
        result = render_code128(obj.data, obj.module, ch, show_text=obj.show_text,
                                text_size=obj.text_size, max_width=cw)
    except ValueError as exc:
        raise _Failed(str(exc)) from exc
    return _code_result(obj, result, cw, ch, tape, issues, two_d=False)


def _datamatrix(obj: DataMatrixObject, cw: int, ch: int, tape, issues) -> _Content:
    try:
        result = render_datamatrix(obj.data, min(cw, ch), obj.module)
    except ValueError as exc:
        raise _Failed(str(exc)) from exc
    return _code_result(obj, result, cw, ch, tape, issues, two_d=True)


# --- Icon, Formen, Bild -------------------------------------------------------

def _icon(obj: IconObject, cw: int, ch: int, tape, issues) -> _Content:
    try:
        icon = render_icon(obj.icon, min(cw, ch))
    except (IconMissing, ValueError, OSError) as exc:
        raise _Failed(str(exc)) from exc
    return _Content(_centered(icon, cw, ch))


def _line(obj: LineObject, cw: int, ch: int, tape, issues) -> _Content:
    if obj.thickness == 1:
        issues.append(ObjectIssue(obj.id, "warning", _t(THIN_LINE)))
    return _Content(draw_line(cw, ch, obj.direction, obj.thickness, obj.dash,
                              obj.arrow_start, obj.arrow_end))


def _rect(obj: RectObject, cw: int, ch: int, tape, issues) -> _Content:
    if obj.thickness == 1:
        issues.append(ObjectIssue(obj.id, "warning", _t(THIN_LINE)))
    image = draw_rect(cw, ch, obj.thickness, obj.radius, obj.fill, obj.stripe)
    return _Content(image, opaque=obj.fill != "none")


def _image(obj: ImageObject, cw: int, ch: int, tape, issues) -> _Content:
    try:
        source = decode_png(obj.png)
    except ValueError as exc:
        raise _Failed(str(exc)) from exc
    fitted = fit_image(source, cw, ch, obj.keep_aspect)
    image = to_1bit(fitted, threshold=obj.threshold, dither=obj.dither, invert=obj.invert)
    return _Content(image.convert("1"), opaque=True)


_RENDERERS = {"text": _text, "qr": _qr, "code128": _code128, "datamatrix": _datamatrix,
              "icon": _icon, "line": _line, "rect": _rect, "image": _image}


# --- Objekt ------------------------------------------------------------------

def render_object(obj: LabelObject, profile: DeviceProfile, *, tape: TapeProfile | None = None) -> ObjectRender:
    cw, ch = (obj.h, obj.w) if obj.rotation in (90, 270) else (obj.w, obj.h)
    issues: list[ObjectIssue] = []
    try:
        content = _RENDERERS[obj.kind](obj, cw, ch, tape, issues)
    except _Failed as exc:
        issues.append(ObjectIssue(obj.id, "error", str(exc)))
        return ObjectRender(_white(obj.w, obj.h), False, tuple(issues))
    image = content.image
    if obj.rotation in _ROTATE:
        image = image.transpose(_ROTATE[obj.rotation])
    if obj.mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return ObjectRender(image, content.opaque, tuple(issues), content.font_size, content.code)


# --- Dokument ----------------------------------------------------------------

def _ink_mask(image: Image.Image) -> Image.Image:
    return ImageOps.invert(image.convert("L")).convert("1")


def render_document(doc: LabelDocument, profile: DeviceProfile, *,
                    tape: TapeProfile | None = None) -> DocumentRender:
    height = profile.content_dots
    visible = [o for o in doc.objects if o.visible]
    front: list[ObjectIssue] = []
    label_issues: list[ObjectIssue] = []

    natural = max(extent(doc) + mm_to_rows(doc.margin_mm, profile), 1)
    if not visible:
        length = 1
    elif doc.length_mode == "fixed":
        length = mm_to_rows(doc.length_mm, profile)
    else:
        length = natural
        if doc.length_mode == "max":
            limit = mm_to_rows(doc.length_mm, profile)
            if natural > limit:
                label_issues.append(ObjectIssue(
                    None, "error",
                    _t("Inhalt passt nicht in {length_mm:.0f} mm (braucht {rows_to_mm:.0f} mm)", length_mm=doc.length_mm, rows_to_mm=rows_to_mm(natural, profile))))
    length = max(length, 1)

    if not visible or all(_is_empty_text(o) for o in visible):
        front.append(ObjectIssue(None, "error", _t(NOTHING)))

    landscape = _white(length, height)
    issues: list[ObjectIssue] = []
    boxes: dict[str, tuple[int, int, int, int]] = {}
    font_sizes: dict[str, int] = {}
    codes: dict[str, CodeInfo] = {}
    for obj in visible:
        rendered = render_object(obj, profile, tape=tape)
        if rendered.opaque:
            landscape.paste(rendered.image, (obj.x, obj.y))
        else:
            landscape.paste(0, (obj.x, obj.y), _ink_mask(rendered.image))
        boxes[obj.id] = bbox(obj)
        if rendered.font_size is not None:
            font_sizes[obj.id] = rendered.font_size
        if rendered.code is not None:
            codes[obj.id] = rendered.code
        issues.extend(rendered.issues)
        if obj.y < 0 or obj.y + obj.h > height:
            issues.append(ObjectIssue(obj.id, "warning", _t(OUT_ACROSS)))
        if obj.x < 0 or obj.x + obj.w > length:
            issues.append(ObjectIssue(obj.id, "warning", _t(OUT_ALONG)))

    length_mm = rows_to_mm(length, profile)
    if length_mm > LONG_LABEL_MM:
        label_issues.append(ObjectIssue(None, "warning", _t("Label ungewöhnlich lang ({length_mm:.0f} mm)", length_mm=length_mm)))

    if doc.rotate180:
        landscape = landscape.transpose(Image.Transpose.ROTATE_180)
    if doc.mirror:
        landscape = landscape.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    head = place_on_head(landscape_to_content(landscape), profile)
    return DocumentRender(
        landscape=landscape, head=head, length_rows=length, length_mm=length_mm,
        tape_mm=length_mm + profile.leader_mm + profile.trailer_mm,
        boxes=boxes, font_sizes=font_sizes, codes=codes,
        issues=tuple(front + issues + label_issues),
    )


def _describe(issue: ObjectIssue) -> str:
    return f"{issue.object_id}: {issue.message}" if issue.object_id else issue.message


def to_render_result(dr: DocumentRender, profile: DeviceProfile) -> RenderResult:
    if dr.errors:
        raise ValueError("; ".join(_describe(i) for i in dr.errors))
    font_size = min(dr.font_sizes.values()) if dr.font_sizes else None
    return RenderResult(
        dr.landscape, dr.head, font_size, None, [i.message for i in dr.warnings],
        dr.length_mm, dr.tape_mm,
        mm_to_rows(profile.leader_mm, profile), mm_to_rows(profile.trailer_mm, profile),
        profile.head_dots - profile.content_offset - profile.content_dots)


def render_spec(spec: LabelSpec, profile: DeviceProfile, tape: TapeProfile | None = None) -> RenderResult:
    mode = tape.effective_code_mode if tape is not None else "normal"
    if not spec.qr or mode == "normal":
        return render_label(spec, profile)
    if mode == "warn":
        result = render_label(spec, profile)
        result.warnings.append(_t(DARK_WARN))
        return result
    from tapesmith.document.from_spec import spec_to_document

    doc = spec_to_document(spec, profile, invert_codes=True)
    return to_render_result(render_document(doc, profile, tape=tape), profile)
