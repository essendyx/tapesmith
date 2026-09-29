"""Tests für die Qt-Hilfen: PIL→QImage/QPixmap und BackgroundCall."""

import threading

import pytest
from PIL import Image
from PySide6.QtGui import qGray

from tapesmith.gui.qtutil import BackgroundCall, pil_to_pixmap, pil_to_qimage


def test_pil_to_qimage_modus_1_schwarz_weiss(qapp):
    img = Image.new("1", (3, 2), 255)
    img.putpixel((0, 0), 0)

    qimg = pil_to_qimage(img)

    assert (qimg.width(), qimg.height()) == (3, 2)
    assert qGray(qimg.pixel(0, 0)) == 0
    assert qGray(qimg.pixel(2, 1)) == 255


def test_pil_to_qimage_modus_l_ungerade_breite_stimmt_pixelgenau(qapp):
    width, height = 5, 3
    img = Image.new("L", (width, height))
    for y in range(height):
        for x in range(width):
            img.putpixel((x, y), (x * 47 + y * 13) % 256)

    qimg = pil_to_qimage(img)

    for y in range(height):
        for x in range(width):
            assert qGray(qimg.pixel(x, y)) == img.getpixel((x, y)), (x, y)


def test_pil_to_qimage_rgb_farbe_erhalten(qapp):
    img = Image.new("RGB", (4, 3), (10, 20, 30))
    img.putpixel((1, 1), (200, 150, 90))

    qimg = pil_to_qimage(img)
    color = qimg.pixelColor(1, 1)

    assert (color.red(), color.green(), color.blue()) == (200, 150, 90)


def test_pil_to_qimage_rgba_farbe_und_alpha_erhalten(qapp):
    img = Image.new("RGBA", (4, 3), (10, 20, 30, 255))
    img.putpixel((2, 2), (1, 2, 3, 128))

    qimg = pil_to_qimage(img)
    color = qimg.pixelColor(2, 2)

    assert (color.red(), color.green(), color.blue(), color.alpha()) == (1, 2, 3, 128)


def test_pil_to_pixmap_skaliert_scharf_fuer_hidpi(qapp):
    img = Image.new("RGB", (10, 4), (5, 5, 5))

    pixmap = pil_to_pixmap(img, scale=3, device_pixel_ratio=2.0)

    assert pixmap.devicePixelRatio() == 2.0
    assert pixmap.width() == 60
    assert pixmap.width() / pixmap.devicePixelRatio() == 30

    with pytest.raises(ValueError):
        pil_to_pixmap(img, scale=0)


def test_pil_to_pixmap_ungueltiger_device_pixel_ratio(qapp):
    img = Image.new("RGB", (2, 2), (0, 0, 0))
    with pytest.raises(ValueError):
        pil_to_pixmap(img, scale=1, device_pixel_ratio=0)


def test_background_call_liefert_ergebnis_ueber_signal(qtbot):
    call = BackgroundCall(lambda: 42)

    with qtbot.waitSignal(call.finished, timeout=3000) as blocker:
        call.start()

    assert blocker.args == [42]


def test_background_call_laeuft_in_eigenem_thread(qtbot):
    seen_ids: dict[str, int] = {}

    def fn():
        seen_ids["worker"] = threading.get_ident()
        return None

    call = BackgroundCall(fn)
    with qtbot.waitSignal(call.finished, timeout=3000):
        call.start()

    assert seen_ids["worker"] != threading.get_ident()


def test_background_call_meldet_fehler_ueber_failed(qtbot):
    def boom():
        raise ValueError("x")

    call = BackgroundCall(boom)

    with qtbot.waitSignal(call.failed, timeout=3000) as blocker:
        call.start()

    assert isinstance(blocker.args[0], ValueError)
    assert str(blocker.args[0]) == "x"

    with qtbot.assertNotEmitted(call.finished, wait=200):
        pass


def test_background_call_abandon_unterdrueckt_signale(qtbot):
    event = threading.Event()

    def fn():
        event.wait(timeout=5)
        return "spät"

    call = BackgroundCall(fn)
    call.start()
    call.abandon()
    event.set()

    assert call.wait(timeout_s=2.0)

    with qtbot.assertNotEmitted(call.finished, wait=200):
        pass


def test_background_call_zweiter_start_wirft(qtbot):
    event = threading.Event()
    call = BackgroundCall(lambda: event.wait(timeout=5))
    call.start()

    with pytest.raises(RuntimeError):
        call.start()

    call.abandon()
    event.set()
    call.wait(timeout_s=2.0)
