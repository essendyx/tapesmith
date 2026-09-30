"""CLI-Befehl `tapesmith sn-scan`."""

from io import BytesIO

import zxingcpp
from PIL import Image

from tapesmith import cli


def _code128_png(path, text: str) -> None:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Code128)
    img = barcode.to_image(scale=3, add_quiet_zones=True)
    mv = memoryview(img)
    rows, cols = mv.shape
    pil = Image.frombytes("L", (cols, rows), bytes(mv)).convert("RGB")
    canvas = Image.new("RGB", (pil.width + 40, pil.height + 40), (255, 255, 255))
    canvas.paste(pil, (20, 20))
    canvas.save(path, format="PNG")


def test_sn_scan_prints_only_the_best_serial(tmp_path, capsys):
    img = tmp_path / "aufkleber.png"
    _code128_png(img, "S/N ONLYME123456")
    assert cli.main(["sn-scan", str(img)]) == 0
    assert capsys.readouterr().out.strip() == "ONLYME123456"


def test_sn_scan_alle_lists_candidates(tmp_path, capsys):
    ean = zxingcpp.create_barcode("4006381333931", zxingcpp.BarcodeFormat.EAN13)
    code128 = zxingcpp.create_barcode("S/N MULTI123456789", zxingcpp.BarcodeFormat.Code128)

    def to_pil(barcode):
        img = barcode.to_image(scale=3, add_quiet_zones=True)
        mv = memoryview(img)
        rows, cols = mv.shape
        return Image.frombytes("L", (cols, rows), bytes(mv)).convert("L")

    ean_img, code_img = to_pil(ean), to_pil(code128)
    width = max(ean_img.width, code_img.width) + 40
    height = ean_img.height + code_img.height + 60
    canvas = Image.new("L", (width, height), 255)
    canvas.paste(ean_img, (20, 10))
    canvas.paste(code_img, (20, ean_img.height + 30))
    img_path = tmp_path / "aufkleber.png"
    canvas.convert("RGB").save(img_path, format="PNG")

    assert cli.main(["sn-scan", str(img_path), "--alle"]) == 0
    out = capsys.readouterr().out
    assert "MULTI123456789" in out
    assert "4006381333931" in out
    assert out.count("\n") >= 2


def test_sn_scan_no_serial_is_exit_1(tmp_path, capsys):
    img = tmp_path / "leer.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(img, format="PNG")
    assert cli.main(["sn-scan", str(img)]) == 1
    assert "Keine Seriennummer erkannt" in capsys.readouterr().err


def test_sn_scan_print_writes_preview_file(tmp_path):
    img = tmp_path / "aufkleber.png"
    _code128_png(img, "S/N PRINTME123456")
    preview = tmp_path / "p.png"
    assert (
        cli.main(
            ["sn-scan", str(img), "--print", "--host", "pmx10", "--slot", "SSD-1", "--preview", str(preview)]
        )
        == 0
    )
    assert preview.exists()
