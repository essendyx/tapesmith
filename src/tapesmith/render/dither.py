"""Bildaufbereitung: Einpassen, Schwellwert, Floyd-Steinberg, Bayer."""

from PIL import Image
from tapesmith.i18n import _t

BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
DITHERS = ("none", "floyd", "bayer")


def fit_image(image: Image.Image, w: int, h: int, keep_aspect: bool = True) -> Image.Image:
    """Transparenz auf Weiß, Modus "L"; keep_aspect -> größtmöglich eingepasst (LANCZOS) und auf
    weißer w×h-Fläche zentriert; sonst auf w×h gestreckt. Ergebnis genau w×h."""
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.paste(rgba, (0, 0), rgba)
    gray = background.convert("L")

    if not keep_aspect:
        return gray.resize((w, h), Image.LANCZOS)

    scale = min(w / gray.width, h / gray.height)
    new_size = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
    resized = gray.resize(new_size, Image.LANCZOS)
    canvas = Image.new("L", (w, h), 255)
    x = (w - resized.width) // 2
    y = (h - resized.height) // 2
    canvas.paste(resized, (x, y))
    return canvas


def to_1bit(image: Image.Image, *, threshold: int = 128, dither: str = "none",
            invert: bool = False) -> Image.Image:
    """"none": p >= threshold -> 255 sonst 0. "floyd": FLOYDSTEINBERG (threshold wirkt vorher als
    Helligkeitsverschiebung). "bayer": 4×4-Bayer-Matrix. invert=True kehrt das Ergebnis um."""
    gray = image.convert("L")

    if dither == "none":
        result = gray.point(lambda p: 255 if p >= threshold else 0, mode="1")
    elif dither == "floyd":
        shift = 128 - threshold
        shifted = gray.point(lambda p: max(0, min(255, p + shift)))
        result = shifted.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    elif dither == "bayer":
        w, h = gray.size
        src = gray.load()
        out = Image.new("1", (w, h), 255)
        dst = out.load()
        for y in range(h):
            for x in range(w):
                threshold_eff = (BAYER4[y % 4][x % 4] + 0.5) * 16 + (threshold - 128)
                dst[x, y] = 255 if src[x, y] >= threshold_eff else 0
        result = out
    else:
        raise ValueError(_t("unbekanntes dither '{dither}' (erlaubt: {items})", dither=dither, items=', '.join(DITHERS)))

    if invert:
        result = result.point(lambda p: 255 - p, mode="1")
    return result
