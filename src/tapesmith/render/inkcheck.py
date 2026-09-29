"""Schwarzanteil je Zeile/Job und Hinweistext."""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image
from tapesmith.i18n import _t

HEAVY_ROW_RATIO = 0.6        # Zeile gilt als "fast voll", wenn >= 60 % der Kopfpunkte schwarz
HEAVY_JOB_RATIO = 0.35
HEAVY_ROWS_MIN = 40           # >= 40 fast volle Zeilen (5 mm) zählen als großflächig
LOW_BATTERY = 30


@dataclass(frozen=True)
class InkStats:
    job_ratio: float          # schwarze Punkte / alle Punkte des Kopfbilds
    max_row_ratio: float
    heavy_rows: int


def ink_stats(head: Image.Image) -> InkStats:
    w, h = head.size
    if w == 0 or h == 0:
        return InkStats(0.0, 0.0, 0)
    row_bytes = (w + 7) // 8
    data = head.tobytes()
    total_black = 0
    max_ratio = 0.0
    heavy_rows = 0
    for y in range(h):
        row = data[y * row_bytes:(y + 1) * row_bytes]
        ones = sum(byte.bit_count() for byte in row)
        black = w - ones
        ratio = black / w
        total_black += black
        if ratio > max_ratio:
            max_ratio = ratio
        if ratio >= HEAVY_ROW_RATIO:
            heavy_rows += 1
    job_ratio = total_black / (w * h)
    return InkStats(job_ratio, max_ratio, heavy_rows)


def ink_warnings(heads: Sequence[Image.Image], battery_percent: int | None) -> list[str]:
    heavy = False
    max_row = 0.0
    heavy_rows = 0
    for head in heads:
        stats = ink_stats(head)
        if stats.job_ratio >= HEAVY_JOB_RATIO or stats.heavy_rows >= HEAVY_ROWS_MIN:
            heavy = True
            max_row = max(max_row, stats.max_row_ratio)
            heavy_rows = max(heavy_rows, stats.heavy_rows)
    if not heavy:
        return []

    unknown = battery_percent is None or battery_percent > 100
    if not unknown and battery_percent >= LOW_BATTERY:
        return []

    akku = _t("unbekanntem Akkustand") if unknown else _t("Akku {battery_percent} %", battery_percent=battery_percent)
    return [
        _t("Viel Schwarz im Druck (bis {max_row:.0%} je Zeile, {heavy_rows} fast volle Zeilen) bei {akku}: Druck kann blass werden oder abbrechen (Schätzung, nicht belegt)", max_row=max_row, heavy_rows=heavy_rows, akku=akku)
    ]
