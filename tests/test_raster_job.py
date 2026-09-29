import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.protocol.job import Packet, build_job, job_bytes, job_parts, raster_header
from tapesmith.protocol.raster import encode_rows, landscape_to_content, place_on_head


@pytest.fixture
def profile():
    return load_profile()


def test_place_on_head_right_aligns_like_soburi(profile):
    content = Image.new("1", (88, 3), 0)          # komplett schwarz
    head = place_on_head(content, profile)
    assert head.size == (96, 3)
    assert head.getpixel((7, 0)) == 255           # Rand weiß
    assert head.getpixel((8, 0)) == 0             # Inhalt beginnt bei Offset 8
    narrow = place_on_head(Image.new("1", (40, 1), 0), profile)
    assert narrow.getpixel((55, 0)) == 255
    assert narrow.getpixel((56, 0)) == 0          # 96 - 40


def test_place_on_head_rejects_too_wide(profile):
    with pytest.raises(ValueError, match="breiter"):
        place_on_head(Image.new("1", (89, 1), 0), profile)


def test_landscape_rotation_maps_top_row_to_last_column():
    land = Image.new("1", (10, 4), 1)
    land.putpixel((2, 0), 0)                       # oben, x=2
    content = landscape_to_content(land)
    assert content.size == (4, 10)
    assert content.getpixel((3, 2)) == 0           # x' = H-1-y, y' = x


def test_encode_rows_msb_first_black_is_one():
    head = Image.new("1", (16, 2), 1)
    head.putpixel((0, 0), 0)
    head.putpixel((15, 1), 0)
    assert encode_rows(head) == bytes([0x80, 0x00, 0x00, 0x01])


def test_encode_rows_requires_byte_width():
    with pytest.raises(ValueError):
        encode_rows(Image.new("1", (10, 1), 1))


def test_raster_header_little_endian():
    assert raster_header(12, 0x0102) == bytes.fromhex("1b401d763000" "0c00" "0201")


def test_build_job_sequence(profile):
    head = Image.new("1", (96, 2), 1)
    packets = build_job(head, profile)
    assert [p.data for p in packets[:6]] == list(profile.init_packets)
    assert packets[6] == Packet(raster_header(12, 2), False)
    assert packets[7] == Packet(bytes(24), False)
    assert packets[8] == Packet(profile.feed_command, False)
    assert job_bytes(packets).endswith(bytes.fromhex("1b640d1b640d"))


def test_build_job_rejects_wrong_width(profile):
    with pytest.raises(ValueError, match="96"):
        build_job(Image.new("1", (88, 2), 1), profile)


def test_build_job_awaits_only_init_packets(profile):
    packets = build_job(Image.new("1", (96, 5), 1), profile)
    assert [p.await_response for p in packets] == [True] * 6 + [False, False, False]


def test_job_parts_sum_to_job_bytes(profile):
    head = Image.new("1", (96, 7), 1)
    head.putpixel((50, 3), 0)
    init, header, raster, feed = job_parts(head, profile)
    assert all(p.await_response for p in init)
    assert header == raster_header(12, 7)
    assert raster == encode_rows(head)
    assert feed == profile.feed_command
    assert b"".join(p.data for p in init) + header + raster + feed == job_bytes(build_job(head, profile))


def test_job_parts_rejects_wrong_width(profile):
    with pytest.raises(ValueError, match="96"):
        job_parts(Image.new("1", (88, 2), 1), profile)
