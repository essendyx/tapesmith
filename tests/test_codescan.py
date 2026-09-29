"""Seriennummer vom Aufkleber scannen. Testbilder werden hier erzeugt, keine
Binärdateien eingecheckt."""

from io import BytesIO

import pytest
import segno
import zxingcpp
from PIL import Image

from tapesmith.integrations import codescan

pytestmark = pytest.mark.filterwarnings("error")


def _to_pil(barcode_img) -> Image.Image:
    mv = memoryview(barcode_img)
    rows, cols = mv.shape
    return Image.frombytes("L", (cols, rows), bytes(mv))


def _code128(text: str, scale: int = 3) -> Image.Image:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Code128)
    return _to_pil(barcode.to_image(scale=scale, add_quiet_zones=True))


def _ean13(text: str, scale: int = 3) -> Image.Image:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.EAN13)
    return _to_pil(barcode.to_image(scale=scale, add_quiet_zones=True))


def _datamatrix(text: str, scale: int = 6, *, gs1: bool = False) -> Image.Image:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.DataMatrix, gs1=gs1)
    return _to_pil(barcode.to_image(scale=scale, add_quiet_zones=True))


def _qr(text: str, scale: int = 3) -> Image.Image:
    qr = segno.make_qr(text)
    buf = BytesIO()
    qr.save(buf, kind="png", scale=scale, border=4)
    buf.seek(0)
    return Image.open(buf).convert("L")


def _paste(canvas: Image.Image, piece: Image.Image, xy: tuple[int, int]) -> None:
    canvas.paste(piece.convert("L"), xy)


def _to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format=fmt)
    return buf.getvalue()


def test_sticker_with_ean_code128_and_qr_picks_code128_serial():
    ean = _ean13("4006381333931")
    code128 = _code128("S/N S5Y1NX0R123456")
    qr = _qr("https://example.com/p/1")

    width = max(ean.width, code128.width, qr.width) + 40
    height = ean.height + code128.height + qr.height + 80
    canvas = Image.new("L", (width, height), 255)
    _paste(canvas, ean, (20, 10))
    _paste(canvas, code128, (20, ean.height + 30))
    _paste(canvas, qr, (20, ean.height + code128.height + 50))

    result = codescan.scan(_to_bytes(canvas))
    assert result.best is not None
    assert result.best.serial == "S5Y1NX0R123456"

    by_serial = {c.serial: c for c in result.candidates}
    assert by_serial["4006381333931"].score < 0
    url_candidates = [c for c in result.candidates if "example.com" in c.serial]
    assert url_candidates and url_candidates[0].score < 0


def test_gs1_datamatrix_best_serial_and_reason():
    dm = _datamatrix("(01)04012345678901(21)ABC123456", gs1=True)
    canvas = Image.new("L", (dm.width + 40, dm.height + 40), 255)
    _paste(canvas, dm, (20, 20))

    result = codescan.scan(_to_bytes(canvas))
    assert result.best is not None
    assert result.best.serial == "ABC123456"
    assert "GS1" in result.best.reason


def test_gs1_serial_parses_parenthesized_ai():
    assert codescan.gs1_serial("(01)04012345678901(21)XYZ789") == "XYZ789"


def test_gs1_serial_parses_raw_prefix_and_fixed_length_ai():
    raw = "]d2" + "0104012345678901" + "21ABC123456"
    assert codescan.gs1_serial(raw) == "ABC123456"


def test_rotated_and_shrunk_image_still_decodes():
    code128 = _code128("S/N ROTATED123456")
    canvas = Image.new("L", (code128.width + 40, code128.height + 40), 255)
    _paste(canvas, code128, (20, 20))
    rotated = canvas.rotate(90, expand=True)
    small = rotated.resize((rotated.width // 2, rotated.height // 2), Image.LANCZOS)

    result = codescan.scan(_to_bytes(small))
    assert any(h.text == "S/N ROTATED123456" for h in result.hits)


def test_inverted_image_still_decodes():
    from PIL import ImageChops

    code128 = _code128("S/N INVERTED12345")
    canvas = Image.new("L", (code128.width + 40, code128.height + 40), 255)
    _paste(canvas, code128, (20, 20))
    inverted = ImageChops.invert(canvas)

    result = codescan.scan(_to_bytes(inverted))
    assert any(h.text == "S/N INVERTED12345" for h in result.hits)


def test_exif_orientation_is_applied():
    code128 = _code128("S/N EXIFTEST123456")
    canvas = Image.new("RGB", (code128.width + 40, code128.height + 40), (255, 255, 255))
    _paste(canvas, code128, (20, 20))
    # Um 90 Grad im Uhrzeigersinn gedreht ablegen, EXIF-Orientation 6 (rotate 270 beim Anzeigen
    # dreht es wieder richtig) markiert es zum automatischen Zurückdrehen.
    rotated_source = canvas.rotate(-90, expand=True)
    buf = BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    rotated_source.save(buf, format="JPEG", exif=exif)

    result = codescan.scan(buf.getvalue())
    assert any(h.text == "S/N EXIFTEST123456" for h in result.hits)


def test_empty_white_image_has_no_hits():
    canvas = Image.new("L", (400, 200), 255)
    result = codescan.scan(_to_bytes(canvas))
    assert result.hits == ()
    assert result.best is None


def test_no_image_raises_value_error():
    with pytest.raises(ValueError):
        codescan.scan(b"abc")


def test_too_large_file_raises_value_error():
    data = b"x" * (codescan.MAX_BYTES + 1)
    with pytest.raises(ValueError):
        codescan.scan(data)


def test_multiword_text_without_prefix_is_penalized_for_embedded_space():
    # clean_serial() entfernt jedes Leerzeichen (auch eingebettete), das Leerzeichen-Kriterium
    # muss also VOR clean_serial geprueft werden, sonst greift die -80 Strafe nie (Regressionstest).
    text = "ARTIKEL NUMMER 12345678"
    code128 = _code128(text)
    canvas = Image.new("L", (code128.width + 40, code128.height + 40), 255)
    _paste(canvas, code128, (20, 20))

    result = codescan.scan(_to_bytes(canvas))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.score < 0
    assert "Leerzeichen" in candidate.reason
    assert result.best is None


def test_by_id_text_in_code128_yields_serial_candidate():
    text = "ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456"
    code128 = _code128(text)
    canvas = Image.new("L", (code128.width + 40, code128.height + 40), 255)
    _paste(canvas, code128, (20, 20))

    result = codescan.scan(_to_bytes(canvas))
    serials = {c.serial for c in result.candidates}
    assert "S5Y1NX0R123456" in serials
