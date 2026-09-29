import io
from pathlib import Path

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.imageinput import image_to_head, load_image_head, read_stdin_text, to_mono
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.protocol.raster import landscape_to_content, place_on_head

GOLDEN = Path(__file__).parent / "golden"
P = load_profile()


def test_full_width_image_is_unchanged():
    img = Image.new("1", (P.head_dots, 40), 255)
    img.putpixel((10, 5), 0)
    head = image_to_head(img, P)
    assert head.size == (P.head_dots, 40)
    assert head.getpixel((10, 5)) == 0
    assert head.getpixel((0, 0)) == 255


def test_narrow_portrait_image_is_placed_right_aligned():
    img = Image.new("1", (40, 100), 0)  # ganz schwarz
    head = image_to_head(img, P)
    expected = place_on_head(img, P)
    assert head.tobytes() == expected.tobytes()
    assert head.size == (P.head_dots, 100)
    x = P.content_offset + P.content_dots - 40
    assert head.getpixel((x, 0)) == 0
    assert head.getpixel((x - 1, 0)) == 255


def test_landscape_image_auto_rotated_matches_manual_placement():
    img = Image.new("1", (300, 60), 0)
    head = image_to_head(img, P, rotate="auto")
    expected = place_on_head(landscape_to_content(img), P)
    assert head.tobytes() == expected.tobytes()
    assert head.height == 300


def test_landscape_image_rotate_none_is_too_big_error():
    img = Image.new("1", (300, 60), 0)
    with pytest.raises(ValueError) as exc:
        image_to_head(img, P, rotate="none")
    assert "Bild zu groß" in str(exc.value)
    assert "--fit" in str(exc.value)


def test_landscape_image_fit_scales_to_content_dots():
    img = Image.new("1", (400, 200), 0)
    head = image_to_head(img, P, rotate="auto", fit=True)
    assert head.width == P.head_dots
    expected_length = round(400 * P.content_dots / 200)
    assert abs(head.height - expected_length) <= 1


def test_rgba_transparency_composites_onto_white():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for x in range(4):
        for y in range(4):
            img.putpixel((x, y), (0, 0, 0, 255))
    mono = to_mono(img)
    assert mono.getpixel((0, 0)) == 0
    assert mono.getpixel((9, 9)) == 255


def test_threshold_grayscale():
    img = Image.new("L", (5, 5), 100)
    assert to_mono(img, threshold=128).getpixel((0, 0)) == 0
    assert to_mono(img, threshold=90).getpixel((0, 0)) == 255
    with pytest.raises(ValueError):
        to_mono(img, threshold=300)


def test_load_image_head_bad_bytes_is_error():
    with pytest.raises(ValueError) as exc:
        load_image_head(b"kein bild", P)
    assert "nicht lesbar" in str(exc.value)


def test_load_image_head_golden_reference_is_byte_identical():
    data = (GOLDEN / "ref_label.pbm").read_bytes()
    head = load_image_head(data, P, rotate="none")
    ours = job_bytes(build_job(head, P))
    theirs = (GOLDEN / "ref_stream.bin").read_bytes()
    assert ours == theirs


def test_load_image_head_from_path():
    head = load_image_head(GOLDEN / "ref_label.pbm", P, rotate="none")
    assert head.width == P.head_dots


def test_read_stdin_text_typical_input_with_bom_and_trailing_blank():
    stream = io.TextIOWrapper(io.BytesIO("pmx10\r\nSSD-1\n\n".encode("utf-8-sig")), encoding="utf-8")
    assert read_stdin_text(stream) == ["pmx10", "SSD-1"]


def test_read_stdin_text_binary_is_error():
    stream = io.TextIOWrapper(io.BytesIO(b"a\x00b"), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        read_stdin_text(stream)
    assert "Binärdaten" in str(exc.value)


def test_read_stdin_text_invalid_utf8_is_error():
    stream = io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        read_stdin_text(stream)
    assert "UTF-8" in str(exc.value)


def test_read_stdin_text_control_char_is_error():
    with pytest.raises(ValueError) as exc:
        read_stdin_text(io.StringIO("\x07"))
    assert "Steuerzeichen" in str(exc.value)


def test_read_stdin_text_too_many_lines_is_error():
    with pytest.raises(ValueError) as exc:
        read_stdin_text(io.StringIO("a\nb\nc\nd"))
    assert "höchstens 3" in str(exc.value)


def test_read_stdin_text_empty_is_error():
    with pytest.raises(ValueError) as exc:
        read_stdin_text(io.StringIO(""))
    assert "leer" in str(exc.value)


def test_read_stdin_text_tab_becomes_space():
    assert read_stdin_text(io.StringIO("x\ty")) == ["x y"]
