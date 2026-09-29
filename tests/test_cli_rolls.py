"""Rolle und Schwarzanteil auch in der CLI: jeder Druck (file:-Transport, kein echter Drucker) zieht von der Rolle
des aktuellen Bandes ab, warnt bei zu kurzer/fast leerer Rolle und prüft den Schwarzanteil."""

from tapesmith import cli
from tapesmith.tape.rolls import RollStore


def _print(tmp_path, *extra, name="job.bin"):
    return cli.main(["--transport", f"file:{tmp_path / name}", "print", *extra])


def test_cli_druck_zieht_von_rolle_ab(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["tape", "new-roll"]) == 0
    assert _print(tmp_path, "pmx10 SSD-1", "--qr", "S4EWNX0R123456") == 0
    assert _print(tmp_path, "pmx10 SSD-1", name="job2.bin") == 0
    roll = RollStore().current("schwarz-weiss")
    assert roll.jobs == 2
    assert roll.used_mm > 0
    capsys.readouterr()
    assert cli.main(["tape", "roll"]) == 0
    assert "noch ca." in capsys.readouterr().out


def test_cli_vorschau_zieht_nichts_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["tape", "new-roll"]) == 0
    assert cli.main(["print", "SSD-1", "--preview", str(tmp_path / "p.png")]) == 0
    assert RollStore().current("schwarz-weiss").jobs == 0


def test_cli_warnt_bei_zu_kurzer_rolle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["tape", "new-roll", "--length-m", "0.01"]) == 0
    capsys.readouterr()
    assert _print(tmp_path, "pmx10 SSD-1") == 0
    assert "reicht wahrscheinlich nicht" in capsys.readouterr().err


def test_cli_warnt_bei_fast_leerer_rolle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["tape", "new-roll", "--length-m", "0.2"]) == 0
    capsys.readouterr()
    assert _print(tmp_path, "pmx10 SSD-1") == 0
    assert "fast leer" in capsys.readouterr().err


def test_cli_n7_schwarzanteil(tmp_path, monkeypatch, capsys):
    from PIL import Image

    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    img = tmp_path / "schwarz.png"
    Image.new("1", (400, 88), 0).save(img)
    assert _print(tmp_path, "--image", str(img)) == 0
    assert "unbekanntem Akkustand" in capsys.readouterr().err


def test_cli_bandwechsel_zaehlt_gegen_neues_band(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["tape", "new-roll"]) == 0                  # Rolle A: schwarz-weiss
    assert cli.main(["tape", "set", "weiss-schwarz"]) == 0
    assert _print(tmp_path, "pmx10 SSD-1") == 0                  # B hat keine Rolle
    assert RollStore().current("schwarz-weiss").jobs == 0        # A unverändert
    assert cli.main(["tape", "new-roll"]) == 0                  # Rolle B
    assert _print(tmp_path, "pmx10 SSD-1", name="job2.bin") == 0
    assert RollStore().current("schwarz-weiss").jobs == 0
    assert RollStore().current("weiss-schwarz").jobs == 1


def test_tape_set_zeigt_rolle_des_neuen_bandes(capsys):
    assert cli.main(["tape", "new-roll"]) == 0
    capsys.readouterr()
    assert cli.main(["tape", "set", "weiss-schwarz"]) == 0
    assert "Rolle: Keine Rolle erfasst" in capsys.readouterr().out
    assert cli.main(["tape", "set", "schwarz-weiss"]) == 0
    assert "Rolle: noch ca. 4,0 m" in capsys.readouterr().out
