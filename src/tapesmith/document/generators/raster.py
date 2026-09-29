"""Generator Raster-Streifen: Felder im festen Raster (Port, TE oder freie Fachbreite).

Grenzen werden **kumulativ** in Millimetern aufsummiert und erst am Ende in Zeilen gerundet
(`mm_to_rows`), damit keine Rundungsdrift durch viele einzeln gerundete Felder entsteht.
Leere Felder (Leerzeile in der Belegung, oder ein freier Port) bekommen kein Textobjekt,
zählen aber für Raster und Länge.

Jede Zelle hat einen Innenabstand (`innenabstand_mm`, Standard 1 mm) zu den Trennstrichen und zum
Rand quer; Text berührt die Trennstriche nie. Schriftgröße (Wert `schriftgroesse`, siehe
`render.textsize`): "auto" setzt alle Felder in einer einheitlichen Größe (die größte, bei der jedes
Feld passt) auf gemeinsamer Grundlinie, "auto-feld" passt jedes Feld einzeln ein, eine feste
Texthöhe in mm wird je Feld nötigenfalls verkleinert (mit Warnung), nie abgeschnitten.
"""

from __future__ import annotations

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.generators import GeneratorOutput
from tapesmith.document.model import LabelDocument, LineObject, TextObject
from tapesmith.render import textsize
from tapesmith.render.compose import mm_to_rows, rows_to_mm
from tapesmith.render.text import MIN_SIZE, fit_size, ink_extent
from tapesmith.i18n import N_, _t

PARAMS = {"einheit": "port", "raster_mm": 15.875, "te_mm": 17.5, "trennstrich": True, "rand_mm": 0.0,
          "innenabstand_mm": 1.0}
FONT = "sans"
EINHEITEN = ("port", "te", "frei")
NO_FIELDS = N_("Belegung enthält keine beschrifteten Felder")
NOT_CALIBRATED = N_("Vorschub noch nicht kalibriert: für maßgenaue Raster erst „Lineal drucken“")


def _to_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_assignment(text: str) -> list[tuple[str, float | None]]:
    """Zeilen (Trenner "\\n" oder ";"), je Zeile "Name" oder "Name|Breite"; leere Zeile
    ergibt ein leeres Feld ("", None). `None` bedeutet "keine Breite angegeben"; das ist
    kein Wert, sondern ein Sentinel, damit "Name" (keine Breite) von "Name|1" (explizit
    1 mm/TE/Port) unterschieden werden kann."""
    result: list[tuple[str, float | None]] = []
    for raw_line in _SPLIT(text):
        line = raw_line.strip("\r")
        if "|" in line:
            name, _, width_raw = line.partition("|")
            width = _to_float(width_raw)
            if width is None:
                raise ValueError(_t("Belegung: Breite '{width_raw}' ist keine Zahl", width_raw=width_raw))
        else:
            name, width = line, None
        result.append((name.strip(), width))
    return result


def _SPLIT(text: str) -> list[str]:
    out = [""]
    for ch in text:
        if ch in "\n;":
            out.append("")
        else:
            out[-1] += ch
    return out


def _sep_x(boundary: int, length_rows: int) -> int:
    return min(max(0, boundary - 1), length_rows - 2)


def _text_objects(cells, mode, box_y: int, box_h: int, profile: DeviceProfile,
                  warnings: list[str]) -> list[TextObject]:
    if mode == textsize.AUTO_FIELD:
        return [TextObject(id=f"field{i + 1}", x=x, y=box_y, w=w, h=box_h, text=name, size=None,
                           align="center", font=FONT) for i, name, x, w in cells]

    fits = {i: _fit(name, box_h, w) for i, name, _x, w in cells}
    sizes: dict[int, int | None] = {}
    if mode == textsize.AUTO:
        fitting = [f for f in fits.values() if f is not None]
        uniform = min(fitting) if fitting else None
        # Gemeinsame Grundlinie: die Vereinigung aller Tintenhöhen muss ebenfalls passen.
        while uniform is not None and uniform > MIN_SIZE and _union_height(cells, fits, uniform) > box_h:
            uniform -= 1
        for i, _name, _x, _w in cells:
            sizes[i] = uniform if fits[i] is not None else None
    else:
        wanted = textsize.mm_to_font_size(mode, profile.dots_per_mm)
        for i, name, _x, _w in cells:
            fit = fits[i]
            if fit is not None and fit < wanted:
                warnings.append(textsize.shrink_warning(
                    _t("Feld '{name}'", name=name), mode, textsize.font_size_to_mm(fit, profile.dots_per_mm)))
                sizes[i] = fit
            else:
                sizes[i] = wanted if fit is not None else None

    extents = {i: ink_extent([name], FONT, sizes[i]) for i, name, _x, _w in cells if sizes[i] is not None}
    top = min((e[0] for e in extents.values()), default=0)
    bottom = max((e[1] for e in extents.values()), default=0)
    shared = bottom - top <= box_h
    baseline = box_y + (box_h - (bottom - top)) // 2 - top

    objects = []
    for i, name, x, w in cells:
        size = sizes[i]
        if size is None:
            # Passt nicht einmal in kleinster Schrift: der Renderer meldet es als Fehler.
            objects.append(TextObject(id=f"field{i + 1}", x=x, y=box_y, w=w, h=box_h, text=name,
                                      size=None, align="center", font=FONT))
            continue
        ink_top, ink_bottom, _width = extents[i]
        if shared:
            y, h = baseline + ink_top, ink_bottom - ink_top
        else:
            y, h = box_y, box_h
        objects.append(TextObject(id=f"field{i + 1}", x=x, y=y, w=w, h=h, text=name, size=size,
                                  align="center", font=FONT))
    return objects


def _fit(name: str, box_h: int, box_w: int) -> int | None:
    try:
        return fit_size([name], FONT, box_h, box_w)
    except ValueError:      # Name ohne sichtbare Tinte
        return None


def _union_height(cells, fits, size: int) -> int:
    extents = [ink_extent([name], FONT, size) for i, name, _x, _w in cells if fits[i] is not None]
    if not extents:
        return 0
    return max(e[1] for e in extents) - min(e[0] for e in extents)


def generate(params: dict, values: dict[str, str], profile: DeviceProfile) -> GeneratorOutput:
    einheit = params["einheit"]
    if einheit not in EINHEITEN:
        raise ValueError(_t("Raster: einheit '{einheit}' unbekannt (erlaubt: {items})", einheit=einheit, items=', '.join(EINHEITEN)))

    raster_mm = _to_float(values.get("raster_mm", "")) or params["raster_mm"]
    te_mm = params["te_mm"]
    rand_mm = params["rand_mm"]
    trennstrich = params["trennstrich"]

    mode = textsize.parse(values.get(textsize.TEXT_SIZE_FIELD, ""))
    warnings: list[str] = []

    raw_fields = parse_assignment(values.get("belegung", ""))
    fields_mm: list[tuple[str, float]] = []
    for name, width in raw_fields:
        if einheit == "port":
            width_mm = (1.0 if width is None else width) * raster_mm
        elif einheit == "te":
            te_count = 1.0 if width is None else width
            if te_count != int(te_count) or not 1 <= te_count <= 4:
                raise ValueError(_t("Raster: TE-Breite {te_count:g} ungültig (1..4)", te_count=te_count))
            width_mm = te_count * te_mm
        else:  # "frei"
            width_mm = raster_mm if width is None else width
        fields_mm.append((name, width_mm))

    if not any(name for name, _ in fields_mm):
        raise ValueError(_t(NO_FIELDS))

    boundaries_mm = [rand_mm]
    cum = rand_mm
    for _name, width_mm in fields_mm:
        cum += width_mm
        boundaries_mm.append(cum)
    boundaries = [mm_to_rows(b, profile) for b in boundaries_mm]

    content_h = profile.content_dots
    length_rows = boundaries[-1] + mm_to_rows(rand_mm, profile)
    sep_xs = [_sep_x(b, length_rows) for b in boundaries]
    pad = mm_to_rows(params["innenabstand_mm"], profile)
    pad_q = round(params["innenabstand_mm"] * profile.dots_per_mm)
    box_y, box_h = pad_q, max(1, content_h - 2 * pad_q)

    objects = []
    field_info = []
    cells: list[tuple[int, str, int, int]] = []   # (Index, Name, box_x, box_w)
    for i, (name, width_mm) in enumerate(fields_mm):
        start_row, end_row = boundaries[i], boundaries[i + 1]
        field_info.append({
            "name": name, "start_mm": boundaries_mm[i], "width_mm": width_mm,
            "start_row": start_row, "end_row": end_row,
        })
        if name:
            # Trennstrich belegt sep_x und sep_x + 1; dazwischen bleibt je Seite `pad` frei.
            box_x = sep_xs[i] + 2 + pad
            box_w = max(1, sep_xs[i + 1] - pad - box_x)
            cells.append((i, name, box_x, box_w))

    objects.extend(_text_objects(cells, mode, box_y, box_h, profile, warnings))

    n = len(boundaries)
    for i, x in enumerate(sep_xs):
        is_edge = i == 0 or i == n - 1
        if is_edge and not trennstrich:
            continue
        objects.append(LineObject(id=f"sep{i}", x=x, y=0, w=2, h=content_h,
                                   direction="v", thickness=2))
    doc = LabelDocument(objects=tuple(objects), length_mode="fixed",
                         length_mm=rows_to_mm(length_rows, profile))

    total_mm = rows_to_mm(length_rows, profile)
    notes = [_t("{count} Felder, {total_mm:.1f} mm", count=len(fields_mm), total_mm=total_mm)]
    if "length" not in profile.verified and profile.length_factor == 1.0:
        notes.append(_t(NOT_CALIBRATED))

    extra = {"fields": field_info}
    return GeneratorOutput(document=doc, notes=tuple(notes), warnings=tuple(warnings), extra=extra)
