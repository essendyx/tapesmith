"""Generator Kabelfahne: Fahne mit Wickelzone (π·d + Zugabe) und Knicklinien.

Aufbau längs des Bands: Rand | Texthälfte A | Wickelzone | Texthälfte B | Rand.
Hälfte B wird um 180° gedreht, wenn die Fahne am waagerecht laufenden Kabel *hängt*
(damit beide Hälften nach dem Zusammenkleben richtig herum lesbar sind); sie bleibt
ungedreht, wenn sie am senkrecht laufenden Kabel *seitlich absteht*.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.generators import GeneratorOutput
from tapesmith.document.model import LabelDocument, LineObject, TextObject
from tapesmith.render.compose import mm_to_rows, rows_to_mm
from tapesmith.render.text import fit_text
from tapesmith.i18n import _t

CABLE_TYPES = {"Cat6": 6.2, "Cat6a": 7.5, "Kaltgeräte": 8.0, "DAC": 4.5, "LWL": 2.0}
PARAMS = {"zugabe_mm": 3.0, "rand_mm": 2.0, "text_mm": 0.0}
VERLAUF_HAENGT = "haengt"
VERLAUF_STEHT_AB = "steht_ab"
MIN_TEXT_MM = 15.0
THIN_CABLE_MM = 3.0


def _to_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def cable_diameter(values: dict[str, str]) -> float:
    """`durchmesser_mm` (Komma oder Punkt) hat Vorrang vor `kabeltyp`; ist beides unbrauchbar, ValueError."""
    explicit = _to_float(values.get("durchmesser_mm", ""))
    if explicit is not None:
        return explicit
    kabeltyp = values.get("kabeltyp", "").strip()
    if kabeltyp in CABLE_TYPES:
        return CABLE_TYPES[kabeltyp]
    raise ValueError(
        _t("Kabelfahne: Kabeltyp '{kabeltyp}' unbekannt und kein Durchmesser angegeben (erlaubt: {items})", kabeltyp=kabeltyp, items=', '.join(CABLE_TYPES)))


def generate(params: dict, values: dict[str, str], profile: DeviceProfile) -> GeneratorOutput:
    kabel_id = values.get("kabel_id", "").strip()
    if not kabel_id:
        raise ValueError(_t("Kabelfahne: kabel_id fehlt"))
    verlauf = values.get("verlauf", "").strip() or VERLAUF_HAENGT
    if verlauf not in (VERLAUF_HAENGT, VERLAUF_STEHT_AB):
        raise ValueError(
            _t("Kabelfahne: verlauf '{verlauf}' unbekannt (erlaubt: {verlauf_haengt}, {verlauf_steht_ab})", verlauf=verlauf, verlauf_haengt=VERLAUF_HAENGT, verlauf_steht_ab=VERLAUF_STEHT_AB))
    d = cable_diameter(values)
    quelle = values.get("quelle", "").strip()
    ziel = values.get("ziel", "").strip()

    lines = [kabel_id]
    if quelle or ziel:
        lines.append(f"{quelle} → {ziel}")
    text = "\n".join(lines)

    content_h = profile.content_dots
    text_mm = params["text_mm"]
    if text_mm:
        half_w = mm_to_rows(text_mm, profile)
    else:
        half_w = fit_text(lines, "sans", content_h, None, "center").image.width
        half_w = max(half_w, mm_to_rows(MIN_TEXT_MM, profile))

    rand = mm_to_rows(params["rand_mm"], profile)
    wrap_w = mm_to_rows(math.pi * d + params["zugabe_mm"], profile)

    x0 = rand
    x1 = x0 + half_w
    x2 = x1 + wrap_w
    x3 = x2 + half_w
    length = x3 + rand

    text_a = TextObject(id="text_a", x=x0, y=0, w=half_w, h=content_h, text=text, size=None, align="center")
    fold1 = LineObject(id="fold1", x=x1, y=0, w=1, h=content_h, direction="v", thickness=1, dash=4)
    fold2 = LineObject(id="fold2", x=x2 - 1, y=0, w=1, h=content_h, direction="v", thickness=1, dash=4)
    rotation = 180 if verlauf == VERLAUF_HAENGT else 0
    text_b = TextObject(id="text_b", x=x2, y=0, w=half_w, h=content_h, text=text, size=None, align="center",
                         rotation=rotation)

    doc = LabelDocument(objects=(text_a, fold1, fold2, text_b), length_mode="fixed",
                         length_mm=rows_to_mm(length, profile))

    a_mm = rows_to_mm(x1, profile)
    b_mm = rows_to_mm(x2, profile)
    if verlauf == VERLAUF_HAENGT:
        b_note = _t("Hälfte B um 180° gedreht (Fahne hängt am waagerechten Kabel)")
    else:
        b_note = _t("Hälfte B nicht gedreht (Fahne steht seitlich am senkrechten Kabel ab)")
    notes = (
        _t("Knicklinien bei {a_mm:.1f} mm und {b_mm:.1f} mm (ab Labelanfang)", a_mm=a_mm, b_mm=b_mm),
        _t("2 Stück drucken: je eins pro Kabelende"),
        b_note,
    )
    warnings = ()
    if d < THIN_CABLE_MM:
        warnings = (_t("Sehr dünnes Kabel, Fahne gut andrücken"),)

    extra = {"fold_rows": (x1, x2), "diameter_mm": d, "orientation": verlauf}
    return GeneratorOutput(document=doc, notes=notes, warnings=warnings, extra=extra)


def side_view(output: GeneratorOutput, profile: DeviceProfile, height: int = 120) -> Image.Image:
    """Skizze von der Seite (nur für die Anzeige): Kabelquerschnitt und die zusammengeklebte
    Fahne: bei „hängt“ nach unten, bei „steht ab“ zur Seite."""
    orientation = output.extra["orientation"]
    width = height
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2
    r = max(6, min(width, height) // 2 - 34)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline="black", width=2)

    flag_short = max(12, r)
    flag_long = max(24, r * 2)
    if orientation == VERLAUF_HAENGT:
        x0 = cx - flag_short // 2
        y0 = cy + r
        x1 = cx + flag_short // 2
        y1 = min(height - 4, y0 + flag_long)
        mid = (y0 + y1) // 2
        draw.rectangle((x0, y0, x1, y1), outline="black", width=2)
        draw.line((x0, mid, x1, mid), fill="black", width=1)
        draw.text((x0 + 4, y0 + 4), "A", fill="black")
        draw.text((x0 + 4, mid + 4), "B", fill="black")
    else:
        x0 = cx + r
        y0 = cy - flag_short // 2
        x1 = min(width - 4, x0 + flag_long)
        y1 = cy + flag_short // 2
        mid = (x0 + x1) // 2
        draw.rectangle((x0, y0, x1, y1), outline="black", width=2)
        draw.line((mid, y0, mid, y1), fill="black", width=1)
        draw.text((x0 + 4, y0 + 4), "A", fill="black")
        draw.text((mid + 4, y0 + 4), "B", fill="black")
    return image
