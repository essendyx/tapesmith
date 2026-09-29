"""Erzeugt die Golden Files einmalig aus soburi phomemo-p12-tools 0.0.5 (MIT).

Kein COM-Port: Der Datenstrom wird von einem Fake-Port mitgeschnitten.
Aufruf: .venv\\Scripts\\python tools\\make_golden.py
"""

import subprocess
import sys
from pathlib import Path

import phomemo.print_p12 as soburi

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden"
TEXT = "pmx10 SSD-1 SN 274913"


class CapturePort:
    def __init__(self):
        self.data = bytearray()

    def write(self, chunk):
        self.data.extend(chunk)
        return len(chunk)

    def flush(self):
        pass

    def read(self):
        return b""


def main():
    GOLDEN.mkdir(parents=True, exist_ok=True)
    render = Path(sys.executable).with_name("phomemo_render_label.exe")
    pbm = subprocess.run([str(render), "--font-size", "44", TEXT], check=True, capture_output=True).stdout
    (GOLDEN / "ref_label.pbm").write_bytes(pbm)

    port = CapturePort()
    soburi.header(port)
    soburi.print_image(port, soburi.preprocess_image(pbm, 96))
    soburi.tape_feed(port)
    (GOLDEN / "ref_stream.bin").write_bytes(bytes(port.data))
    print(f"ref_label.pbm: {len(pbm)} Bytes, ref_stream.bin: {len(port.data)} Bytes")


if __name__ == "__main__":
    main()
