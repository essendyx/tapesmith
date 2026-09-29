"""Kurzform (`LabelSpec`) -> Objektmodell (`LabelDocument`).

Normalfall: bildet `render_label` Punkt für Punkt nach (gleiche Längenrechnung, gleiche Fehlertexte),
das gerenderte Dokument ist pixelgleich. Invert-Pfad (dunkles Band): kleineres QR-Modul, damit
quer mindestens 2 Module Ruhezone bleiben, und eine QR-Box, die die Ruhezone einschließt, denn die gedruckte
Ruhezone kann nur innerhalb der Box entstehen. Zwischen Box und Text bleibt ein ungedruckter Abstand
(`INVERT_TEXT_GAP_MM`, mindestens eine Ruhezonenbreite), damit der erste Strich nicht verschmilzt.
"""

from __future__ import annotations

import segno

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.model import LabelDocument, QrObject, TextObject
from tapesmith.render.compose import LabelSpec, mm_to_rows, rows_to_mm
from tapesmith.render.qr import MIN_MODULE_DOTS, QUIET_MODULES, QrResult, render_qr
from tapesmith.render.text import TextBlock, fit_text, render_text_block
from tapesmith.i18n import _t


INVERT_TEXT_GAP_MM = 1.5   # dunkles Band: ungedruckter Abstand zwischen Ruhezonen-Box und Text


def _invert_qr(spec: LabelSpec, height: int) -> QrResult:
    n = len(segno.make_qr(spec.qr, error=spec.qr_error, boost_error=False).matrix)
    module = height // (n + 4)
    if module >= MIN_MODULE_DOTS:
        return render_qr(spec.qr, module * n, spec.qr_error)
    return render_qr(spec.qr, height, spec.qr_error)


def spec_to_document(spec: LabelSpec, profile: DeviceProfile, *, invert_codes: bool = False) -> LabelDocument:
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

    qr: QrResult | None = None
    qr_width = gap = quiet = 0
    lead = tail = margin
    if spec.qr:
        qr = _invert_qr(spec, height) if invert_codes else render_qr(spec.qr, height, spec.qr_error)
        quiet = QUIET_MODULES * qr.module_dots
        lead = max(margin, quiet)
        qr_width = qr.image.width
        if has_text:
            gap = quiet
            if invert_codes:
                # Box endet bei x+qr_width+quiet (gedruckte helle Ruhezone); danach ungedruckter
                # Abstand, sonst verschmilzt der erste Textstrich mit dem Ruhezonen-Block.
                gap = quiet + max(quiet, mm_to_rows(INVERT_TEXT_GAP_MM, profile))
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

    objects = []
    x = offset + lead
    if qr is not None:
        if invert_codes:
            objects.append(QrObject(id="qr1", x=x - quiet, y=0, w=qr_width + 2 * quiet, h=height,
                                    data=spec.qr, error=spec.qr_error, module=qr.module_dots))
        else:
            objects.append(QrObject(id="qr1", x=x, y=(height - qr.image.height) // 2,
                                    w=qr_width, h=qr.image.height,
                                    data=spec.qr, error=spec.qr_error, module=qr.module_dots))
        x += qr_width + gap
    if text is not None:
        objects.append(TextObject(id="text1", x=x, y=(height - text.image.height) // 2,
                                  w=text.image.width, h=text.image.height, text="\n".join(lines),
                                  font=spec.font, size=text.font_size, align=spec.align, valign="middle"))
    margin_mm = spec.margin_mm if 0 <= spec.margin_mm <= 20 else 1.0
    return LabelDocument(objects=tuple(objects), length_mode="fixed",
                         length_mm=rows_to_mm(width, profile), margin_mm=margin_mm)
