"""Belegung eines Raster-Streifens als CSV, PNG oder PDF exportieren."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw

from tapesmith.document.generators import GeneratorOutput
from tapesmith.render.fonts import load_font
from tapesmith.i18n import N_, _t

CSV_HEADER = (N_("Nr"), N_("Bezeichnung"), N_("Start (mm)"), N_("Breite (mm)"))
_FORMATS = (".csv", ".png", ".pdf")


def assignment_rows(output: GeneratorOutput) -> list[dict]:
    fields = output.extra.get("fields", [])
    return [
        {"nr": i, "name": f["name"], "start_mm": f["start_mm"], "width_mm": f["width_mm"]}
        for i, f in enumerate(fields, start=1)
    ]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow([_t(h) for h in CSV_HEADER])
        for row in rows:
            writer.writerow([row["nr"], row["name"], f"{row['start_mm']:.1f}", f"{row['width_mm']:.1f}"])


def _table_image(rows: list[dict]) -> Image.Image:
    font = load_font("sans", 14)
    header = [_t(h) for h in CSV_HEADER]
    lines = [header] + [
        [str(r["nr"]), r["name"] or "-", f"{r['start_mm']:.1f}", f"{r['width_mm']:.1f}"] for r in rows
    ]
    pad = 12
    col_widths = [max(font.getlength(line[c]) for line in lines) for c in range(len(header))]
    col_x = [0.0]
    for w in col_widths:
        col_x.append(col_x[-1] + w + pad)
    ascent, descent = font.getmetrics()
    row_h = ascent + descent + 8
    width = max(1, round(col_x[-1] + pad))
    height = row_h * len(lines) + pad
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for r, line in enumerate(lines):
        y = pad // 2 + r * row_h
        for c, text in enumerate(line):
            draw.text((col_x[c] + pad // 2, y), text, font=font, fill=0)
    return image


def export_assignment(output: GeneratorOutput, path: Path) -> Path:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in _FORMATS:
        raise ValueError(_t("Unbekanntes Exportformat '{suffix}' (erlaubt: {items})", suffix=suffix, items=', '.join(_FORMATS)))
    rows = assignment_rows(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        _write_csv(path, rows)
    else:
        image = _table_image(rows)
        if suffix == ".png":
            image.save(path)
        else:
            image.convert("RGB").save(path, "PDF", resolution=150)
    return path
