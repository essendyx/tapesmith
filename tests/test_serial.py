import pytest

from tapesmith.templates.serial import (DiskId, SerialNotDerivable, clean_serial, normalize_serial_input,
                                       parse_by_id, shorten)


def test_clean_serial():
    assert clean_serial("  S/N: 1122 3327 4913 ") == "112233274913"
    assert clean_serial("sn 274913") == "274913"
    assert clean_serial("SN:ABC") == "ABC"


@pytest.mark.parametrize("name, model, serial", [
    ("ata-SanDisk_SDSSDHP256G_112233274913", "SanDisk SDSSDHP256G", "112233274913"),
    ("/dev/disk/by-id/ata-SanDisk_SDSSDHP256G_112233274913-part1", "SanDisk SDSSDHP256G", "112233274913"),
    ("nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNX0R123456_1", "Samsung SSD 970 EVO Plus 1TB", "S4EWNX0R123456"),
    ("nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNX0R123456", "Samsung SSD 970 EVO Plus 1TB", "S4EWNX0R123456"),
    ("scsi-SATA_ST4000VN008-2DR1_ZDH1ABCD", "ST4000VN008-2DR1", "ZDH1ABCD"),
    ("usb-SanDisk_Ultra_4C530001220528116393-0:0", "SanDisk Ultra", "4C530001220528116393"),
])
def test_parse_by_id(name, model, serial):
    assert parse_by_id(name) == DiskId(model, serial)


@pytest.mark.parametrize("name", ["wwn-0x5001b448b9a1c2d3", "nvme-eui.0025385b71b0a1c2", "eui.0025385b71b0a1c2",
                                  "scsi-35000c500a1b2c3d4"])
def test_wwn_and_eui_are_not_derivable(name):
    with pytest.raises(SerialNotDerivable, match="lsblk"):
        parse_by_id(name)


def test_unknown_format():
    with pytest.raises(SerialNotDerivable, match="Unbekannt"):
        parse_by_id("dm-name-pve-root")


def test_normalize_and_shorten():
    assert normalize_serial_input("ata-SanDisk_SDSSDHP256G_112233274913").serial == "112233274913"
    assert normalize_serial_input("S/N: 112233274913") == DiskId(None, "112233274913")
    assert shorten("112233274913") == "274913"
    assert shorten("112233274913", 4) == "4913"
    assert shorten("ABC", 6) == "ABC"
    assert shorten("112233274913", 0) == "112233274913"
