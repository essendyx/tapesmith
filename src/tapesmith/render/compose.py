"""Setzt Text und QR zu einem Label im Querformat und liefert das Kopfbild für den Druck."""

from dataclasses import dataclass

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.raster import landscape_to_content, place_on_head
from tapesmith.render.checks import printability_warnings
from tapesmith.render.qr import QUIET_MODULES, QrResult, render_qr
from tapesmith.render.text import TextBlock, fit_text, render_text_block
from tapesmith.i18n import _t


@dataclass(frozen=True)
class LabelSpec:
    lines: tuple[str, ...] = ()
    font: str = "sans"
    align: str = "left"
    font_size: int | None = None
    max_length_mm: float | None = None
    fixed_length_mm: float | None = None
    margin_mm: float = 1.0
    qr: str | None = None
    qr_error: str = "m"


@dataclass
class RenderResult:
    landscape: Image.Image
    head: Image.Image
    font_size: int | None
    qr: QrResult | None
    warnings: list[str]
    length_mm: float
    tape_mm: float
    lead_rows: int
    trail_rows: int
    content_top: int


def mm_to_rows(mm: float, profile: DeviceProfile) -> int:
    return round(mm * profile.dots_per_mm * profile.length_factor)


def rows_to_mm(rows: int, profile: DeviceProfile) -> float:
    return rows / (profile.dots_per_mm * profile.length_factor)


def render_label(spec: LabelSpec, profile: DeviceProfile) -> RenderResult:
    height = profile.content_dots
    lines = tuple(spec.lines)
    has_text = any(line.strip() for line in lines)
    if not has_text and not spec.qr:
        raise ValueError(_t("Nichts zu drucken: weder Text noch QR"))

    margin = mm_to_rows(spec.margin_mm, profile)
    limit = None
    if spec.fixed_length_mm is not None:
        limit = mm_to_rows(spec.fixed_length_mm, profile)
    elif spec.max_length_mm is not None:
        limit = mm_to_rows(spec.max_length_mm, profile)

    qr = None
    qr_width = gap = 0
    lead = tail = margin
    if spec.qr:
        qr = render_qr(spec.qr, height, spec.qr_error)
        quiet = QUIET_MODULES * qr.module_dots
        lead = max(margin, quiet)
        qr_width = qr.image.width
        if has_text:
            gap = quiet
        else:
            tail = max(margin, quiet)

    text: TextBlock | None = None
    if has_text:
        max_width = None if limit is None else limit - lead - qr_width - gap - tail
        if max_width is not None and max_width <= 0:
            raise ValueError(_t("Text passt nicht: Länge reicht nicht einmal für Ränder und QR"))
        if spec.font_size is None:
            text = fit_text(lines, spec.font, height, max_width, spec.align)
        else:
            text = render_text_block(lines, spec.font, spec.font_size, spec.align)
            if text.image.height > height or (max_width is not None and text.image.width > max_width):
                raise ValueError(_t("Text passt nicht bei Schriftgröße {font_size} ({width} × {height} Punkte)", font_size=spec.font_size, width=text.image.width, height=text.image.height))

    content = lead + qr_width + gap + (text.image.width if text else 0) + tail
    if limit is not None and content > limit:
        raise ValueError(_t("Inhalt passt nicht in {rows_to_mm:.0f} mm (braucht {rows_to_mm2:.0f} mm)", rows_to_mm=rows_to_mm(limit, profile), rows_to_mm2=rows_to_mm(content, profile)))
    width = limit if spec.fixed_length_mm is not None else content
    extra = width - content if spec.fixed_length_mm is not None else 0
    if spec.align == "center":
        offset = extra // 2
    elif spec.align == "right":
        offset = extra
    else:
        offset = 0
    landscape = Image.new("1", (width, height), 255)
    x = offset + lead
    if qr is not None:
        landscape.paste(qr.image, (x, (height - qr.image.height) // 2))
        x += qr_width + gap
    if text is not None:
        landscape.paste(text.image, (x, (height - text.image.height) // 2))

    length_mm = rows_to_mm(width, profile)
    font_size = text.font_size if text else None
    warnings = printability_warnings(font_size, qr, length_mm)
    head = place_on_head(landscape_to_content(landscape), profile)
    content_top = profile.head_dots - profile.content_offset - profile.content_dots
    return RenderResult(landscape, head, font_size, qr, warnings, length_mm,
                        length_mm + profile.leader_mm + profile.trailer_mm,
                        mm_to_rows(profile.leader_mm, profile),
                        mm_to_rows(profile.trailer_mm, profile),
                        content_top)


def preview_image(result: RenderResult, scale: int = 4) -> Image.Image:
    """Lesbare Vorschau: Band mit grauem Vor-/Nachlauf, unbedruckbarem Rand grau, Inhalt schwarz/weiß.
    Der vertikale Versatz kommt aus dem Profil (content_top), nicht aus einer angenommenen Zentrierung,
    damit die Vorschau dem tatsaechlich bedruckten Kopfbild entspricht."""
    land = result.landscape
    head_dots = result.head.width
    lead = result.lead_rows
    trail = result.trail_rows
    canvas = Image.new("L", (land.width + lead + trail, head_dots), 200)
    canvas.paste(land.convert("L"), (lead, result.content_top))
    return canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST)
