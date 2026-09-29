"""Export eines Labels bzw. einer Kette als PNG, PDF oder PBM.

PNG/PDF sind fuer die Doku gedacht (z. B. Einbettung in eine Obsidian-Notiz), PBM fuer
Altskripte (`phomemo_print_p12 datei.pbm`). Keine neue Abhaengigkeit: PDF wird mit
Pillow-Bordmitteln erzeugt.
"""

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.render.compose import RenderResult, mm_to_rows
from tapesmith.i18n import _t

FORMATS = ("png", "pdf", "pbm")

_GAP = 8
_TAPE_GRAY = 200


def head_to_landscape(head: Image.Image, profile: DeviceProfile) -> Image.Image:
    """Kehrt place_on_head(landscape_to_content(land)) um: Inhaltsbereich ausschneiden
    und zurueckdrehen. Nur fuer Inhalte mit voller content_dots-Hoehe (wie render_label
    sie erzeugt)."""
    content = head.crop((
        profile.content_offset, 0,
        profile.content_offset + profile.content_dots, head.height,
    ))
    return content.rotate(90, expand=True)


def format_for(path: Path, fmt: str | None = None) -> str:
    candidate = fmt if fmt is not None else Path(path).suffix.lstrip(".")
    candidate = candidate.lower()
    if candidate not in FORMATS:
        raise ValueError(_t("Unbekanntes Exportformat '{candidate}' (erlaubt: png, pdf, pbm)", candidate=candidate))
    return candidate


def export_heads(path: Path, heads: Sequence[Image.Image], profile: DeviceProfile, *,
                  fmt: str | None = None, scale: int = 4, with_tape: bool = False) -> Path:
    return _export(path, heads, None, profile, fmt=fmt, scale=scale, with_tape=with_tape)


def export_result(path: Path, result: RenderResult, profile: DeviceProfile, *,
                   fmt: str | None = None, scale: int = 4, with_tape: bool = False) -> Path:
    return _export(path, [result.head], [result.landscape], profile,
                    fmt=fmt, scale=scale, with_tape=with_tape)


def _export(path: Path, heads: Sequence[Image.Image], landscapes: Sequence[Image.Image] | None,
            profile: DeviceProfile, *, fmt: str | None, scale: int, with_tape: bool) -> Path:
    if scale < 1:
        raise ValueError(_t("scale muss >= 1 sein, nicht {scale}", scale=scale))
    path = Path(path)
    kind = format_for(path, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "pbm":
        _write_pbm(path, heads)
    else:
        lands = list(landscapes) if landscapes is not None else [
            head_to_landscape(head, profile) for head in heads
        ]
        if kind == "png":
            _write_png(path, lands, profile, scale=scale, with_tape=with_tape)
        else:
            _write_pdf(path, lands, profile, with_tape=with_tape)
    return path


def _write_pbm(path: Path, heads: Sequence[Image.Image]) -> None:
    heads = list(heads)
    width = heads[0].width
    total_height = sum(head.height for head in heads)
    combined = Image.new("1", (width, total_height), 255)
    y = 0
    for head in heads:
        combined.paste(head.convert("1"), (0, y))
        y += head.height
    combined.save(path, "PPM")


def _tape_row(land: Image.Image, profile: DeviceProfile, mode: str) -> Image.Image:
    if mode != "L":
        return land
    lead = mm_to_rows(profile.leader_mm, profile)
    trail = mm_to_rows(profile.trailer_mm, profile)
    row = Image.new("L", (lead + land.width + trail, land.height), _TAPE_GRAY)
    row.paste(land.convert("L"), (lead, 0))
    return row


def _write_png(path: Path, lands: Sequence[Image.Image], profile: DeviceProfile, *,
                scale: int, with_tape: bool) -> None:
    mode = "L" if with_tape else "1"
    rows = [_tape_row(land, profile, mode) for land in lands]
    width = max(row.width for row in rows)
    height = sum(row.height for row in rows) + _GAP * (len(rows) - 1)
    canvas = Image.new(mode, (width, height), 255)
    y = 0
    for row in rows:
        canvas.paste(row, (0, y))
        y += row.height + _GAP
    scaled = canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST)
    dpi = profile.dots_per_mm * 25.4
    scaled.save(path, dpi=(dpi * scale, dpi * scale))


def _write_pdf(path: Path, lands: Sequence[Image.Image], profile: DeviceProfile, *,
               with_tape: bool) -> None:
    mode = "L" if with_tape else "1"
    dpi = profile.dots_per_mm * 25.4
    pages = [_tape_row(land, profile, mode).convert("RGB") for land in lands]
    first, rest = pages[0], pages[1:]
    first.save(path, "PDF", resolution=dpi, save_all=True, append_images=rest)
