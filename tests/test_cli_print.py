import io
import sys
from pathlib import Path

from PIL import Image

from tapesmith import cli

GOLDEN = Path(__file__).parent / "golden"


def test_print_text_preview_writes_png(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    png = tmp_path / "p.png"
    assert cli.main(["print", "SSD-1", "--preview", str(png)]) == 0
    assert png.exists()


def test_print_reads_stdin_when_no_args_and_not_a_tty(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("pmx10 SSD-1\n"))
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "print"]) == 0
    data = job.read_bytes()
    assert data.startswith(bytes.fromhex("1f1138"))


def test_print_dash_reads_stdin(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("pmx10 SSD-1\n"))
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "print", "-"]) == 0
    assert job.read_bytes().startswith(bytes.fromhex("1f1138"))


def test_print_image_via_file_transport_is_golden(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "print", "--image", str(GOLDEN / "ref_label.pbm")]) == 0
    assert job.read_bytes() == (GOLDEN / "ref_stream.bin").read_bytes()


def test_print_image_and_text_together_is_exit_1(tmp_path, capsys):
    img = tmp_path / "x.png"
    Image.new("1", (40, 20), 255).save(img)
    assert cli.main(["print", "Text", "--image", str(img), "--preview", str(tmp_path / "p.png")]) == 1
    assert "Fehler:" in capsys.readouterr().err


def test_print_stdin_binary_is_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\x00\x01"), encoding="utf-8"))
    assert cli.main(["print"]) == 1
    assert "Binärdaten" in capsys.readouterr().err


def test_print_without_text_and_tty_stdin_is_exit_1(monkeypatch, capsys):
    class FakeTtyStream:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", FakeTtyStream())
    assert cli.main(["print"]) == 1
    assert "Kein Text" in capsys.readouterr().err
