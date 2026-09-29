import pytest

from tapesmith import cli


# 12
def test_cut_pause_option_prints_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    code = cli.main(["--transport", f"file:{job}", "text", "X", "--copies", "2",
                     "--cut-pause", "0.01"])
    assert code == 0
    err = capsys.readouterr().err
    assert err.count("Label 1/2 abschneiden") == 1
    assert "Label 2/2" not in err


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_cut_pause_must_be_positive(tmp_path, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["text", "X", "--cut-pause", value, "--preview", str(tmp_path / "p.png")])
    assert exc.value.code == 2
    assert "--cut-pause" in capsys.readouterr().err
