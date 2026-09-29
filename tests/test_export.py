import re

import pytest
from PIL import Image, ImageChops

from tapesmith.device.profile import load_profile
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.protocol.raster import place_on_head
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label
from tapesmith.export import export_heads, export_result, format_for, head_to_landscape


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def result(profile):
    return render_label(LabelSpec(lines=("SSD-1",), max_length_mm=30), profile)


def test_head_to_landscape_ist_pixelgleich_zu_landscape(result, profile):
    land = head_to_landscape(result.head, profile)
    diff = ImageChops.difference(land.convert("L"), result.landscape.convert("L"))
    assert diff.getbbox() is None


def test_png_export_result_groesse_und_modus(tmp_path, result, profile):
    path = export_result(tmp_path / "a.png", result, profile, scale=4)
    assert path == tmp_path / "a.png"
    with Image.open(path) as img:
        assert img.size == (result.landscape.width * 4, profile.content_dots * 4)
        assert img.mode == "1"
        dpi = img.info.get("dpi")
        assert dpi is not None
        assert dpi[0] == pytest.approx(203.2 * 4, abs=0.5)
        assert dpi[1] == pytest.approx(203.2 * 4, abs=0.5)


def test_png_export_mit_band(tmp_path, result, profile):
    path = export_result(tmp_path / "b.png", result, profile, scale=4, with_tape=True)
    with Image.open(path) as img:
        lead = mm_to_rows(profile.leader_mm, profile)
        trail = mm_to_rows(profile.trailer_mm, profile)
        expected_width = (lead + result.landscape.width + trail) * 4
        assert img.size == (expected_width, profile.content_dots * 4)
        assert img.mode == "L"
        assert img.getpixel((0, 0)) == 200


def test_png_export_zwei_kopfbilder_hoehe(tmp_path, result, profile):
    path = export_heads(tmp_path / "c.png", [result.head, result.head], profile, scale=1)
    with Image.open(path) as img:
        assert img.size[1] == 2 * profile.content_dots + 8


def test_pbm_export_ein_kopfbild(tmp_path, result, profile):
    path = export_heads(tmp_path / "d.pbm", [result.head], profile)
    raw = path.read_bytes()
    assert raw.startswith(b"P4")
    with Image.open(path) as img:
        assert img.size == result.head.size
    with Image.open(path) as reread_raw:
        reread = reread_raw.convert("1")
    job_a = job_bytes(build_job(reread, profile))
    job_b = job_bytes(build_job(result.head, profile))
    assert job_a == job_b


def test_pbm_export_zwei_kopfbilder_hoehe(tmp_path, result, profile):
    path = export_heads(tmp_path / "e.pbm", [result.head, result.head], profile)
    with Image.open(path) as img:
        assert img.size[1] == 2 * result.head.height
        assert img.size[0] == result.head.width


def test_pdf_export_zwei_seiten_und_breite(tmp_path, result, profile):
    path = export_heads(tmp_path / "f.pdf", [result.head, result.head], profile)
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF")
    pages = re.findall(rb"/Type\s*/Page[^s]", raw)
    assert len(pages) == 2
    boxes = re.findall(rb"/MediaBox \[ ?0 0 ([\d.]+) ([\d.]+)", raw)
    assert boxes
    width_pt = float(boxes[0][0])
    expected = result.landscape.width / 203.2 * 72
    assert width_pt == pytest.approx(expected, abs=1)


def test_format_for():
    from pathlib import Path

    assert format_for(Path("x.PNG")) == "png"
    assert format_for(Path("x.pbm")) == "pbm"
    assert format_for(Path("x.Pdf")) == "pdf"
    with pytest.raises(ValueError, match="png, pdf, pbm"):
        format_for(Path("x.jpg"))
    assert format_for(Path("x.jpg"), fmt="pbm") == "pbm"


def test_export_legt_elternordner_an_und_gibt_pfad_zurueck(tmp_path, result, profile):
    target = tmp_path / "sub" / "dir" / "out.png"
    path = export_result(target, result, profile)
    assert path == target
    assert target.exists()


def test_export_scale_kleiner_eins_ist_fehler(tmp_path, result, profile):
    with pytest.raises(ValueError):
        export_result(tmp_path / "x.png", result, profile, scale=0)
