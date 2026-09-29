"""Linien, Pfeile, Rahmen, Warnbalken-Schraffur. Alle Formen liefern genau w×h,
Modus "1", Hintergrund 255."""

from PIL import Image, ImageDraw
from tapesmith.i18n import _t

DIRECTIONS = ("h", "v", "down", "up")


def warning_stripes(w: int, h: int, stripe: int = 6) -> Image.Image:
    """45°-Diagonalen (von links unten nach rechts oben), Periode 2*stripe."""
    img = Image.new("1", (w, h), 255)
    px = img.load()
    for y in range(h):
        for x in range(w):
            if ((x + y) // stripe) % 2 == 0:
                px[x, y] = 0
    return img


def _endpoints(w: int, h: int, direction: str) -> tuple[tuple[float, float], tuple[float, float]]:
    if direction == "h":
        y = (h - 1) / 2
        return (0.0, y), (w - 1.0, y)
    if direction == "v":
        x = (w - 1) / 2
        return (x, 0.0), (x, h - 1.0)
    if direction == "down":
        return (0.0, 0.0), (w - 1.0, h - 1.0)
    if direction == "up":
        return (0.0, h - 1.0), (w - 1.0, 0.0)
    raise ValueError(_t("unbekannte Richtung '{direction}' (erlaubt: {items})", direction=direction, items=', '.join(DIRECTIONS)))


def _draw_arrowhead(draw: ImageDraw.ImageDraw, tip: tuple[float, float], direction: tuple[float, float],
                     length: float, width: float, w: int, h: int) -> None:
    ux, uy = direction
    # Senkrechte zur Richtung, fuer die Basisbreite.
    px, py = -uy, ux
    base_x, base_y = tip[0] - ux * length, tip[1] - uy * length
    p1 = (base_x + px * width / 2, base_y + py * width / 2)
    p2 = (base_x - px * width / 2, base_y - py * width / 2)

    def clamp(pt: tuple[float, float]) -> tuple[float, float]:
        return max(0.0, min(w - 1.0, pt[0])), max(0.0, min(h - 1.0, pt[1]))

    draw.polygon([clamp(tip), clamp(p1), clamp(p2)], fill=0)


def draw_line(w: int, h: int, direction: str, thickness: int, dash: int = 0,
              arrow_start: bool = False, arrow_end: bool = False) -> Image.Image:
    img = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(img)
    (sx, sy), (ex, ey) = _endpoints(w, h, direction)
    dx, dy = ex - sx, ey - sy
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        draw.line([(sx, sy), (ex, ey)], fill=0, width=thickness)
        return img
    ux, uy = dx / steps, dy / steps

    arrow_len = min(max(3 * thickness, 6), steps)
    arrow_w = max(3 * thickness, 6)

    def point_at(t: float) -> tuple[float, float]:
        return sx + ux * t, sy + uy * t

    line_start_t = arrow_len if arrow_start else 0.0
    line_end_t = steps - arrow_len if arrow_end else steps

    if line_end_t > line_start_t:
        if dash > 0:
            t = line_start_t
            k = 0
            while t < line_end_t:
                seg_end = min(t + dash, line_end_t)
                if k % 2 == 0 and seg_end > t:
                    draw.line([point_at(t), point_at(max(seg_end - 1, t))], fill=0, width=thickness)
                t += dash
                k += 1
        else:
            draw.line([point_at(line_start_t), point_at(line_end_t)], fill=0, width=thickness)

    if arrow_start:
        _draw_arrowhead(draw, (sx, sy), (-ux, -uy), arrow_len, arrow_w, w, h)
    if arrow_end:
        _draw_arrowhead(draw, (ex, ey), (ux, uy), arrow_len, arrow_w, w, h)
    return img


def draw_rect(w: int, h: int, thickness: int, radius: int = 0, fill: str = "none",
              stripe: int = 6) -> Image.Image:
    img = Image.new("1", (w, h), 255)
    if fill == "solid":
        ImageDraw.Draw(img).rectangle([0, 0, w - 1, h - 1], fill=0)
    elif fill == "stripes":
        img.paste(warning_stripes(w, h, stripe), (0, 0))
    elif fill != "none":
        raise ValueError(_t("unbekannte fill-Art '{fill}' (erlaubt: none, solid, stripes)", fill=fill))

    if thickness > 0:
        draw = ImageDraw.Draw(img)
        half = thickness / 2 - 0.5
        box = [half, half, w - 1 - half, h - 1 - half]
        if radius > 0:
            draw.rounded_rectangle(box, radius=radius, outline=0, width=thickness)
        else:
            draw.rectangle(box, outline=0, width=thickness)
    return img
