"""Farbvorschau nach Band: Druckbild in Band-/Druckfarbe statt Schwarz/Weiß.

Transparentes Band zeigt den Hintergrund als Schachbrett (`CHECKER`) statt einer
Bandfarbe. Ohne Python-Pixelschleife über die volle Fläche: Ink/Band laufen über eine
Maske (`Image.point`/`Image.paste`), das Schachbrett wird kachelweise aufgebaut.
"""

from __future__ import annotations

from PIL import Image

from tapesmith.tape.profiles import TapeProfile

CHECKER = ((236, 236, 236), (255, 255, 255))
CHECKER_SIZE = 4

_DEFAULT_BACKGROUND = (255, 255, 255)
_DEFAULT_INK = (0, 0, 0)


def tape_colors(tape: TapeProfile | None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """(Hintergrund, Druckfarbe); `None` -> Weiß/Schwarz."""
    if tape is None:
        return (_DEFAULT_BACKGROUND, _DEFAULT_INK)
    return (tape.background, tape.ink)


def _checkerboard(size: tuple[int, int], checker: int) -> Image.Image:
    dark, light = CHECKER
    tile = Image.new("RGB", (2 * checker, 2 * checker), light)
    tile.paste(dark, (0, 0, checker, checker))
    tile.paste(dark, (checker, checker, 2 * checker, 2 * checker))
    canvas = Image.new("RGB", size)
    for y in range(0, size[1], tile.height):
        for x in range(0, size[0], tile.width):
            canvas.paste(tile, (x, y))
    return canvas


def colorize(image: Image.Image, tape: TapeProfile | None, *, checker: int = CHECKER_SIZE) -> Image.Image:
    """Modus "1" -> "RGB": Pixel 0 (gedruckt) -> Druckfarbe, 255 -> Bandfarbe (oder
    Schachbrett bei transparentem Band)."""
    background, ink = tape_colors(tape)
    ink_mask = image.convert("L").point(lambda p: 255 if p < 128 else 0)
    if tape is not None and tape.transparent:
        rgb = _checkerboard(image.size, checker)
    else:
        rgb = Image.new("RGB", image.size, background)
    rgb.paste(ink, (0, 0), ink_mask)
    return rgb
