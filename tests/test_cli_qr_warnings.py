from tapesmith import cli


# 13
def test_qr_warnings_are_printed_once(tmp_path, capsys):
    text = "x" * 60   # Byte-Modus, Version 4 -> Modul 2 Punkte
    assert cli.main(["qr", "text", text, "--preview", str(tmp_path / "v.png")]) == 0
    err = capsys.readouterr().err
    warnings = [line for line in err.splitlines() if line.startswith("Warnung:")]
    assert warnings, err
    assert any("Modul" in w for w in warnings), err
    assert len(warnings) == len(set(warnings)), err
