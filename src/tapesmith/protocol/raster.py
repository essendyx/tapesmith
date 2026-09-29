"""Bildaufbereitung: Inhalt auf Kopfbreite setzen und in Rasterbytes wandeln.

Konvention: Pillow-Modus "1", 0 = schwarz. Breite = quer zum Band, Höhe = Labellänge.
"""

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.i18n import _t


def place_on_head(content: Image.Image, profile: DeviceProfile) -> Image.Image:
    img = content.convert("1")
    if img.width > profile.content_dots:
        raise ValueError(_t("Inhalt ist {width} Punkte breiter als erlaubt ({content_dots})", width=img.width, content_dots=profile.content_dots))
    head = Image.new("1", (profile.head_dots, img.height), 255)
    head.paste(img, (profile.content_offset + profile.content_dots - img.width, 0))
    return head


def landscape_to_content(landscape: Image.Image) -> Image.Image:
    return landscape.rotate(270, expand=True)


def encode_rows(head: Image.Image) -> bytes:
    if head.width % 8:
        raise ValueError(_t("Breite {width} ist kein Vielfaches von 8", width=head.width))
    return bytes(b ^ 0xFF for b in head.convert("1").tobytes())
