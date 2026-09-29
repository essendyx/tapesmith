from pathlib import Path

import pytest
from PIL import Image

from tapesmith import config
from tapesmith.device.profile import load_profile
from tapesmith.printer import PrinterSession
from tapesmith.protocol.raster import place_on_head
from tapesmith.transport.resolve import open_transport

GOLDEN = Path(__file__).parent / "golden"


@pytest.mark.hardware
def test_handshake_gets_answers():
    cfg = config.load_config()
    with PrinterSession(open_transport("auto", cfg["mac"]), load_profile()) as s:
        answers = b"".join(resp for _, resp in s.handshake())
    assert answers, "Drucker hat auf keinen Handshake-Teil geantwortet"


@pytest.mark.hardware
def test_print_reference_label():
    cfg = config.load_config()
    profile = load_profile()
    head = place_on_head(Image.open(GOLDEN / "ref_label.pbm"), profile)
    with PrinterSession(open_transport("auto", cfg["mac"]), profile) as s:
        result = s.print_image(head)
    assert result.rows == head.height
