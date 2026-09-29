"""Bildeingaben für 'p12 print': Bilddateien/-bytes zu einem druckfertigen Kopfbild wandeln,
sowie robustes Einlesen von Textzeilen aus stdin.

Konvention wie im übrigen Projekt: Pillow-Modus "1", 0 = schwarz, weiße Flächen mit 255.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.raster import landscape_to_content, place_on_head
from tapesmith.i18n import _t

ROTATE_MODES = ("auto", "none", "landscape")

_MAX_ROWS = 65535


def to_mono(img: Image.Image, threshold: int = 128) -> Image.Image:
    """Wandelt ein beliebiges Bild nach Modus "1". Transparenz wird auf Weiß compositet,
    danach nach "L" gewandelt: v >= threshold -> weiß (255), sonst schwarz (0).
    Ist das Bild schon Modus "1", bleibt es unverändert."""
    if not 0 <= threshold <= 255:
        raise ValueError(_t("threshold muss zwischen 0 und 255 liegen, nicht {threshold}", threshold=threshold))
    if img.mode == "1":
        return img
    rgba = img.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.paste(rgba, (0, 0), rgba)
    gray = background.convert("L")
    return gray.point(lambda v: 255 if v >= threshold else 0, mode="1")


def image_to_head(img: Image.Image, profile: DeviceProfile, *, threshold: int = 128,
                   rotate: str = "auto", fit: bool = False) -> Image.Image:
    """Setzt ein beliebiges Bild auf den Druckkopf (Breite = quer zum Band, Höhe = Labellänge).
    Breite gleich Kopfbreite oder höchstens Inhaltsbreite: hochkant übernehmen; sonst quer, wenn die
    Höhe passt (`auto`/`landscape`); mit `fit` auf die Inhaltsbreite skalieren; sonst Fehler."""
    if rotate not in ROTATE_MODES:
        raise ValueError(_t("unbekannter rotate-Wert {rotate!r} (erlaubt: {items})", rotate=rotate, items=', '.join(ROTATE_MODES)))
    content_dots = profile.content_dots
    head_dots = profile.head_dots
    w, h = img.width, img.height

    def finish(mono: Image.Image, landscape: bool) -> Image.Image:
        if landscape:
            head = place_on_head(landscape_to_content(mono), profile)
        elif mono.width == head_dots:
            head = mono
        else:
            head = place_on_head(mono, profile)
        if head.height > _MAX_ROWS:
            raise ValueError(_t("Kopfbild ist {height} Zeilen lang, mehr als {max_rows} sind nicht möglich", height=head.height, max_rows=_MAX_ROWS))
        return head

    if rotate in ("none", "auto") and w == head_dots:
        return finish(to_mono(img, threshold), landscape=False)
    if rotate in ("none", "auto") and w <= content_dots:
        return finish(to_mono(img, threshold), landscape=False)
    if rotate == "auto" and w > content_dots and h <= content_dots:
        return finish(to_mono(img, threshold), landscape=True)
    if rotate == "landscape" and h <= content_dots:
        return finish(to_mono(img, threshold), landscape=True)

    if fit:
        cross = w if rotate == "none" else h
        scale = content_dots / cross
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        scaled = img.convert("L").resize(new_size, Image.LANCZOS)
        return finish(to_mono(scaled, threshold), landscape=rotate != "none")

    raise ValueError(
        _t("Bild zu groß: {w}×{h} Punkte, quer zum Band höchstens {content_dots} Punkte (oder genau {head_dots}). Mit --fit verkleinern.", w=w, h=h, content_dots=content_dots, head_dots=head_dots))


def load_image_head(source: "Path | bytes", profile: DeviceProfile, **kw) -> Image.Image:
    """Öffnet ein Bild aus einer Datei (Path) oder aus Bytes und setzt es auf den Druckkopf."""
    try:
        if isinstance(source, Path):
            img = Image.open(source)
        else:
            img = Image.open(BytesIO(source))
        img.load()
    except Exception as exc:
        raise ValueError(_t("Bild nicht lesbar: {exc}", exc=exc)) from exc
    return image_to_head(img, profile, **kw)


def read_stdin_text(stream, max_lines: int = 3) -> list[str]:
    """Liest Textzeilen aus stdin: erkennt Binärdaten/Encoding-Fehler, normalisiert Zeilenenden
    und Tabs, verbietet Steuerzeichen, entfernt führende/abschließende Leerzeilen."""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        raw = buffer.read()
        if b"\x00" in raw:
            raise ValueError(_t("stdin enthält Binärdaten, Bilder bitte mit --image übergeben"))
        try:
            text = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(_t("stdin ist kein UTF-8-Text")) from exc
    else:
        text = stream.read()
        if isinstance(text, bytes):
            if b"\x00" in text:
                raise ValueError(_t("stdin enthält Binärdaten, Bilder bitte mit --image übergeben"))
            try:
                text = text.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(_t("stdin ist kein UTF-8-Text")) from exc

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    for ch in text:
        if ch != "\n" and ord(ch) < 0x20:
            raise ValueError(_t("stdin enthält Steuerzeichen"))

    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()

    if not lines:
        raise ValueError(_t("stdin ist leer"))
    if len(lines) > max_lines:
        raise ValueError(_t("höchstens {max_lines} Zeilen erlaubt, {count} erhalten", max_lines=max_lines, count=len(lines)))
    return lines
