"""`drives.py`: Datenträger-Erkennung über ein injizierbares Backend. Kein Qt,
keine echten Laufwerke."""

from tapesmith.drives import DRIVE_FIXED, DRIVE_REMOVABLE, DriveInfo, list_drives, marketing_size, suggest_label


class FakeBackend:
    def __init__(self, drives: dict) -> None:
        self._drives = drives

    def roots(self) -> list[str]:
        return list(self._drives)

    def drive_type(self, root: str) -> int:
        return self._drives[root]["type"]

    def volume(self, root: str) -> tuple[str, str]:
        d = self._drives[root]
        if d.get("not_ready"):
            raise OSError("Laufwerk nicht bereit")
        return d.get("label", ""), d.get("filesystem", "")

    def space(self, root: str) -> tuple[int, int]:
        d = self._drives[root]
        return d.get("size", 0), d.get("free", 0)

    def bus(self, root: str) -> str:
        return self._drives[root].get("bus", "unbekannt")


DRIVES = {
    "C:\\": {"type": DRIVE_FIXED, "label": "", "filesystem": "NTFS", "bus": "unbekannt",
             "size": 500_000_000_000, "free": 100_000_000_000},
    "E:\\": {"type": DRIVE_REMOVABLE, "label": "FOTOS 2025", "filesystem": "exFAT", "bus": "usb",
             "size": 61_900_000_000, "free": 10_000_000_000},
    "F:\\": {"type": DRIVE_FIXED, "label": "Backup", "filesystem": "NTFS", "bus": "usb",
             "size": 2_000_000_000_000, "free": 1_000_000_000_000},
    "G:\\": {"type": DRIVE_REMOVABLE, "not_ready": True},
}


def test_list_drives_e_und_f_g_uebersprungen_c_nie(monkeypatch):
    monkeypatch.setenv("SystemDrive", "C:")
    drives = list_drives(FakeBackend(DRIVES))
    roots = {d.root for d in drives}
    assert roots == {"E:\\", "F:\\"}
    e = next(d for d in drives if d.root == "E:\\")
    assert e.label == "FOTOS 2025"
    assert e.filesystem == "exFAT"
    assert e.bus == "usb"
    assert e.removable is True
    assert e.size_bytes == 61_900_000_000


def test_list_drives_include_fixed_usb_false_nur_removable(monkeypatch):
    monkeypatch.setenv("SystemDrive", "C:")
    drives = list_drives(FakeBackend(DRIVES), include_fixed_usb=False)
    assert {d.root for d in drives} == {"E:\\"}


def test_marketing_size():
    assert marketing_size(61.9e9) == "64 GB"
    assert marketing_size(31.1e9) == "32 GB"
    assert marketing_size(15.5e9) == "16 GB"
    assert marketing_size(1000.2e9) == "1 TB"
    assert marketing_size(1_990e9) == "2 TB"
    assert marketing_size(12e12) == "12 TB"
    assert marketing_size(512e6) == "512 MB"


def test_suggest_label_grossbuchstaben_werden_wortweise_grossanfang():
    info = DriveInfo(root="E:\\", label="FOTOS 2025", size_bytes=61_900_000_000, free_bytes=0,
                     filesystem="exFAT", bus="usb", removable=True)
    assert suggest_label(info) == ("Fotos 2025", "64 GB · exFAT")


def test_suggest_label_leer_sd():
    info = DriveInfo(root="E:\\", label="", size_bytes=4_000_000_000, free_bytes=0,
                     filesystem="FAT32", bus="sd", removable=True)
    name, _ = suggest_label(info)
    assert name == "SD-Karte"


def test_suggest_label_leer_removable_usb():
    info = DriveInfo(root="E:\\", label="", size_bytes=4_000_000_000, free_bytes=0,
                     filesystem="FAT32", bus="usb", removable=True)
    name, _ = suggest_label(info)
    assert name == "USB-Stick"


def test_suggest_label_leer_fixed_usb_platte():
    info = DriveInfo(root="F:\\", label="", size_bytes=2_000_000_000_000, free_bytes=0,
                     filesystem="NTFS", bus="usb", removable=False)
    name, _ = suggest_label(info)
    assert name == "USB-Platte"


def test_suggest_label_ohne_dateisystem_nur_groesse():
    info = DriveInfo(root="E:\\", label="Stick", size_bytes=4_000_000_000, free_bytes=0,
                     filesystem="", bus="usb", removable=True)
    _, line2 = suggest_label(info)
    assert line2 == marketing_size(4_000_000_000)
