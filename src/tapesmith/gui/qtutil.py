"""Qt-Hilfen ohne GUI-Zustand: PIL→Qt-Bildwandlung und Hintergrundaufrufe ohne Einfrieren.

`pil_to_qimage`/`pil_to_pixmap` wandeln Vorschaubilder (Modus "1"/"L"/"RGB"/"RGBA") verlustfrei
und scharf für HiDPI. `BackgroundCall` führt eine Funktion in einem eigenen (Daemon-)Thread aus;
Ergebnis/Fehler kommen als Qt-Signal im Thread des Empfängers an. Ein Aufruf darf „verwaisen“
(z. B. blockierendes Port-Öffnen): `abandon()` trennt die GUI sofort, spätere Ergebnisse
werden verworfen.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap
from tapesmith.i18n import _t


def pil_to_qimage(img: Image.Image) -> QImage:
    """PIL-Bild in ein eigenständiges QImage wandeln (Modus "1"/"L"/"RGB"/"RGBA",
    andere Modi werden nach "RGBA" konvertiert). Modus "1": 0 = schwarz, 255 = weiß."""
    if img.mode == "1":
        img = img.convert("L")
    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGBA")

    if img.mode == "L":
        image_format = QImage.Format.Format_Grayscale8
        bytes_per_pixel = 1
    elif img.mode == "RGB":
        image_format = QImage.Format.Format_RGB888
        bytes_per_pixel = 3
    else:
        image_format = QImage.Format.Format_RGBA8888
        bytes_per_pixel = 4

    width, height = img.size
    data = img.tobytes()
    bytes_per_line = width * bytes_per_pixel
    qimage = QImage(data, width, height, bytes_per_line, image_format)
    return qimage.copy()


def pil_to_pixmap(img: Image.Image, scale: int = 1, device_pixel_ratio: float = 1.0) -> QPixmap:
    """PIL-Bild scharf (ohne Weichzeichnung) für HiDPI in ein QPixmap wandeln. Logische
    Größe = (Breite*scale, Höhe*scale); die physische Pixmap wird zusätzlich mit
    `device_pixel_ratio` vergrößert und als solche markiert (`setDevicePixelRatio`)."""
    if scale < 1:
        raise ValueError(_t("scale muss >= 1 sein"))
    if device_pixel_ratio <= 0:
        raise ValueError(_t("device_pixel_ratio muss > 0 sein"))

    factor = scale * device_pixel_ratio
    target_size = (
        math.ceil(img.width * factor),
        math.ceil(img.height * factor),
    )
    scaled = img.resize(target_size, Image.Resampling.NEAREST)
    pixmap = QPixmap.fromImage(pil_to_qimage(scaled))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap


class BackgroundCall(QObject):
    """Führt `fn` in einem eigenen Python-Thread (daemon) aus; Ergebnis/Fehler kommen als
    Qt-Signal im Thread des Empfängers (GUI) an. Der Thread darf „verwaisen“ (blockierendes
    Port-Öffnen): `abandon()` trennt die GUI sofort, spätere Ergebnisse werden verworfen.
    Ein `BackgroundCall` ist einmal verwendbar; ein zweiter `start()` wirft `RuntimeError`."""

    finished = Signal(object)    # Rückgabewert von fn
    failed = Signal(object)      # BaseException aus fn

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._started = False
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._abandoned = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError(_t("läuft bereits"))
        self._started = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="p12-hintergrund")
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout_s: float = 5.0) -> bool:
        """Nur für Tests/Beenden gedacht; True, wenn `fn` fertig ist (unabhängig von abandon())."""
        return self._done.wait(timeout_s)

    def abandon(self) -> None:
        """GUI sofort vom (evtl. weiterlaufenden) Thread trennen: danach werden weder
        `finished` noch `failed` gesendet."""
        self._abandoned = True

    def _run(self) -> None:
        try:
            result = self._fn()
        except BaseException as exc:  # noqa: BLE001 (bewusst breit, siehe Klassendoc)
            self._done.set()
            if not self._abandoned:
                self.failed.emit(exc)
            return
        self._done.set()
        if not self._abandoned:
            self.finished.emit(result)
