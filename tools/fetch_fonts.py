"""Lädt DejaVu 2.37 (freie Lizenz, siehe LICENSE) und legt die benötigten Schnitte ins Paket.

Idempotent: vorhandene Dateien werden nicht erneut geladen.
Aufruf: .venv\\Scripts\\python tools\\fetch_fonts.py
"""

import io
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
TARGET = Path(__file__).resolve().parent.parent / "src" / "tapesmith" / "fonts"
WANTED = {
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf": "DejaVuSans.ttf",
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf": "DejaVuSans-Bold.ttf",
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf": "DejaVuSansMono.ttf",
    "dejavu-fonts-ttf-2.37/LICENSE": "LICENSE",
}


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if all((TARGET / name).exists() for name in WANTED.values()):
        print("Schriften bereits vorhanden")
        return
    data = urllib.request.urlopen(URL, timeout=60).read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member, name in WANTED.items():
            (TARGET / name).write_bytes(zf.read(member))
            print(f"{name}: {(TARGET / name).stat().st_size} Bytes")


if __name__ == "__main__":
    main()
