"""Kalibrier-Labels: Kantentest (welche Kopfzeilen landen auf dem Band) und Lineal (Vorschub)."""

from PIL import Image, ImageDraw, ImageFont

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.raster import landscape_to_content

EDGE_STEP_DOTS = 4
EDGE_PITCH = 40


def edge_test_head(profile: DeviceProfile) -> Image.Image:
    height = profile.head_dots
    steps = height // EDGE_STEP_DOTS
    land = Image.new("1", (steps * EDGE_PITCH, height), 255)
    draw = ImageDraw.Draw(land)
    font = ImageFont.load_default(size=14)
    for k in range(steps):
        row = k * EDGE_STEP_DOTS
        top = height - EDGE_STEP_DOTS - row
        x = k * EDGE_PITCH
        draw.rectangle([x, top, x + 15, top + EDGE_STEP_DOTS - 1], fill=0)
        draw.text((x + 18, height // 2 - 8), str(row), font=font, fill=0)
    return landscape_to_content(land)


def ruler_content(profile: DeviceProfile, length_mm: int = 100) -> Image.Image:
    """Prüf-Lineal MIT dem aktuellen Längenfaktor (`mm_to_rows`): so zeigt jeder neue Druck, ob die
    Kalibrierung stimmt. Der neue Faktor ist dann alt * Solllänge / gemessen."""
    from tapesmith.render.compose import mm_to_rows
    height = profile.content_dots
    land = Image.new("1", (mm_to_rows(length_mm, profile) + 2, height), 255)
    draw = ImageDraw.Draw(land)
    font = ImageFont.load_default(size=16)
    for mm in range(length_mm + 1):
        x = mm_to_rows(mm, profile)
        if mm % 10 == 0:
            tick = height // 2
        elif mm % 5 == 0:
            tick = height // 3
        else:
            tick = height // 6
        draw.line([x, 0, x, tick - 1], fill=0)
        if mm % 10 == 0 and mm < length_mm:
            draw.text((x + 3, height // 2 + 4), str(mm), font=font, fill=0)
    return landscape_to_content(land)
