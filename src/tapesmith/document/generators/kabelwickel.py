"""Generator Kabelwickel: Kabel-ID so oft wiederholt, wie sie auf den Umfang passt.

Länge = Umfang (π·d) + Überlappung (Standard: ein voller Umfang). Alle Wiederholungen der
Kabel-ID haben dieselbe (auto-gefittete) Schriftgröße und sind gleichmäßig über die Länge verteilt.
"""

from __future__ import annotations

import math

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.generators import GeneratorOutput
from tapesmith.document.generators.kabelfahne import cable_diameter
from tapesmith.document.model import LabelDocument, TextObject
from tapesmith.render.compose import mm_to_rows, rows_to_mm
from tapesmith.render.text import fit_text
from tapesmith.i18n import N_, _t

MIN_DIAMETER_MM = 5.0
MIN_REPEAT_FONT = 24  # Punkte (≈ 3 mm); darunter wird nur einmal statt zweimal gesetzt
PARAMS = {"ueberlappung_mm": 0.0, "abstand_mm": 3.0}

TOO_FEW_REPEATS = N_("Kabel-ID passt nur einmal auf den Umfang, kürzere ID oder Kabelfahne verwenden")
TOO_THIN = N_("Unter 5 mm Durchmesser löst sich der Wickel leicht, Kabelfahne verwenden")


def generate(params: dict, values: dict[str, str], profile: DeviceProfile) -> GeneratorOutput:
    kabel_id = values.get("kabel_id", "").strip()
    if not kabel_id:
        raise ValueError(_t("Kabelwickel: kabel_id fehlt"))
    d = cable_diameter(values)

    u_mm = math.pi * d
    overlap_mm = params["ueberlappung_mm"] or u_mm
    length_mm = u_mm + overlap_mm
    abstand_mm = params["abstand_mm"]

    content_h = profile.content_dots
    length_rows = mm_to_rows(length_mm, profile)
    doc_length_mm = rows_to_mm(length_rows, profile)
    abstand_rows = mm_to_rows(abstand_mm, profile)

    max_w2 = (length_rows - 3 * abstand_rows) // 2
    fitted2 = None
    if max_w2 >= 1:
        try:
            fitted2 = fit_text([kabel_id], "sans", content_h, max_w2, "center")
        except ValueError:
            fitted2 = None
    if fitted2 is not None and fitted2.font_size >= MIN_REPEAT_FONT:
        size = fitted2.font_size
        text_w = fitted2.image.width
    else:
        max_w1 = max(1, length_rows - 2 * abstand_rows)
        fitted1 = fit_text([kabel_id], "sans", content_h, max_w1, "center")
        size = fitted1.font_size
        text_w = fitted1.image.width
    text_w_mm = rows_to_mm(text_w, profile)

    k = max(1, math.floor((length_mm + abstand_mm) / (text_w_mm + abstand_mm)))

    gap = max(0.0, (length_rows - k * text_w) / (k + 1))
    objects = []
    x = gap
    for i in range(k):
        objects.append(TextObject(id=f"text{i + 1}", x=round(x), y=0, w=text_w, h=content_h,
                                   text=kabel_id, size=size, align="center"))
        x += text_w + gap

    doc = LabelDocument(objects=tuple(objects), length_mode="fixed", length_mm=doc_length_mm)

    notes = (_t("Wickelbereich {u_mm:.1f} mm, Überlappung {overlap_mm:.1f} mm", u_mm=u_mm, overlap_mm=overlap_mm),)
    warnings = []
    if k < 2:
        warnings.append(_t(TOO_FEW_REPEATS))
    if d < MIN_DIAMETER_MM:
        warnings.append(_t(TOO_THIN))

    wrap_rows = mm_to_rows(u_mm, profile)
    overlap_rows = mm_to_rows(u_mm + overlap_mm, profile) - wrap_rows
    extra = {"wrap_rows": wrap_rows, "overlap_rows": overlap_rows, "repeats": k}
    return GeneratorOutput(document=doc, notes=notes, warnings=tuple(warnings), extra=extra)
