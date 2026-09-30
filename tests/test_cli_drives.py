"""`tapesmith drives`: Fake-Backend, kein echtes Laufwerk."""

import json

from PIL import Image

from tapesmith import cli
from tapesmith.cli_cmds import drives as drives_cmd
from tapesmith.drives import DRIVE_FIXED, DRIVE_REMOVABLE


class FakeBackend:
    def __init__(self, drives: dict) -> None:
        self._drives = drives

    def roots(self) -> list[str]:
        return list(self._drives)

    def drive_type(self, root: str) -> int:
        return self._drives[root]["type"]

    def volume(self, root: str) -> tuple[str, str]:
        return self._drives[root]["label"], self._drives[root]["filesystem"]

    def space(self, root: str) -> tuple[int, int]:
        d = self._drives[root]
        return d["size"], d.get("free", 0)

    def bus(self, root: str) -> str:
        return self._drives[root]["bus"]


DRIVES = {
    "E:\\": {"type": DRIVE_REMOVABLE, "label": "FOTOS 2025", "filesystem": "exFAT",
             "bus": "usb", "size": 61_900_000_000},
}


def _install_fake(monkeypatch, drives=DRIVES):
    monkeypatch.setattr(drives_cmd, "BACKEND_FACTORY", lambda: FakeBackend(drives))


def test_drives_liste_zeigt_bezeichnung_und_groesse(monkeypatch, capsys):
    _install_fake(monkeypatch)
    assert cli.main(["drives"]) == 0
    out = capsys.readouterr().out
    assert "Fotos 2025" in out
    assert "64 GB" in out


def test_drives_json_ist_parsebar(monkeypatch, capsys):
    _install_fake(monkeypatch)
    assert cli.main(["drives", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["root"] == "E:\\"
    assert data[0]["bus"] == "usb"


def test_drives_label_preview_schreibt_png(monkeypatch, tmp_path):
    _install_fake(monkeypatch)
    png = tmp_path / "v.png"
    rc = cli.main(["drives", "label", "E:", "--preview", str(png)])
    assert rc == 0
    assert png.exists()
    with Image.open(png) as img:
        assert img.size[0] > 0


def test_drives_label_unbekanntes_laufwerk_exit_1(monkeypatch, capsys):
    _install_fake(monkeypatch)
    rc = cli.main(["drives", "label", "X:"])
    assert rc == 1
    assert "nicht gefunden" in capsys.readouterr().err
