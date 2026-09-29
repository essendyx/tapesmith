from pathlib import Path

from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.protocol.raster import place_on_head

GOLDEN = Path(__file__).parent / "golden"


def test_reference_label_is_byte_identical_to_soburi():
    content = Image.open(GOLDEN / "ref_label.pbm")
    head = place_on_head(content, load_profile())
    ours = job_bytes(build_job(head, load_profile()))
    theirs = (GOLDEN / "ref_stream.bin").read_bytes()
    assert len(ours) == len(theirs)
    assert ours == theirs
