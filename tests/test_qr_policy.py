"""Einheitliche QR-Regel: dieselbe Lesbarkeitsregel auf allen Wegen,
`render_label` (Vorlagen, `tapesmith text --qr`), `tapesmith qr` (CLI) und `suggest_fixes`."""

import pytest

from tapesmith import cli
from tapesmith.device.profile import load_profile
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.render.fixes import suggest_fixes
from tapesmith.render.qr import render_qr
from tapesmith.render.qrcontent import capacity_report, text_content

P = load_profile()


def test_render_label_rejects_module_1_instead_of_warning_only():
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        render_label(LabelSpec(lines=("X",), qr="x" * 120), P)


def test_render_label_warns_for_module_2():
    assert capacity_report(text_content("x" * 60), P, "m").module_dots == 2
    result = render_label(LabelSpec(qr="x" * 60), P)
    assert any("QR-Modul nur 2 Punkte" in w for w in result.warnings)


def test_cli_text_and_cli_qr_reject_the_same_way(tmp_path, capsys):
    job = tmp_path / "job.bin"
    png = tmp_path / "t1.png"
    assert cli.main(["--transport", f"file:{job}", "text", "X", "--qr", "x" * 120, "--preview", str(png)]) == 1
    err = capsys.readouterr().err
    assert "passt nicht lesbar" in err
    assert not png.exists()

    png2 = tmp_path / "t2.png"
    assert cli.main(["qr", "text", "x" * 120, "--error", "m", "--preview", str(png2)]) == 1
    err = capsys.readouterr().err
    assert "passt nicht lesbar" in err
    assert not png2.exists()


def test_cli_text_and_cli_qr_warn_the_same_way(tmp_path, capsys):
    m2 = "x" * 60
    assert capacity_report(text_content(m2), P, "m").module_dots == 2
    assert capacity_report(text_content(m2), P, "l").module_dots == 2

    job = tmp_path / "job.bin"
    png3 = tmp_path / "t3.png"
    assert cli.main(["--transport", f"file:{job}", "text", "X", "--qr", m2, "--preview", str(png3)]) == 0
    err = capsys.readouterr().err
    assert "QR-Modul nur 2 Punkte" in err

    png4 = tmp_path / "t4.png"
    assert cli.main(["qr", "text", m2, "--error", "m", "--preview", str(png4)]) == 0
    err = capsys.readouterr().err
    assert "QR-Modul nur 2 Punkte" in err

    png5 = tmp_path / "t5.png"
    assert cli.main(["qr", "text", m2, "--preview", str(png5)]) == 0
    err = capsys.readouterr().err
    assert "QR-Modul nur 2 Punkte" in err


def test_suggest_fixes_offers_qr_ecc_l_for_a_rejected_qr():
    content = None
    for k in range(40, 131):
        candidate = "x" * k
        try:
            render_qr(candidate, P.content_dots, "m")
            m_ok = True
        except ValueError:
            m_ok = False
        if m_ok:
            continue
        try:
            render_qr(candidate, P.content_dots, "l")
            l_ok = True
        except ValueError:
            l_ok = False
        if l_ok:
            content = candidate
            break
    if content is None:
        pytest.skip("kein Inhalt zwischen 40 und 130 Zeichen gefunden, der bei M abgelehnt und bei L angenommen wird")

    fixes = suggest_fixes(LabelSpec(qr=content), P)
    assert "qr_ecc_l" in {f.id for f in fixes}
