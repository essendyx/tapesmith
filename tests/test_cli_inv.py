"""Tests für `tapesmith inv`: Boxen, Gegenstände, Suche, Verleih, Label-Druck, zentrale Zähler."""

from PIL import Image

from tapesmith import cli, config
from tapesmith.cli_cmds import inv as inv_cmd


def test_box_add_item_find_lend_loans_return(app_home, capsys):
    assert cli.main(["inv", "box", "add", "BOX-07", "Keller Regal 2"]) == 0
    capsys.readouterr()

    assert cli.main(["inv", "add", "HDMI-Adapter", "--box", "BOX-07", "--qty", "2"]) == 0
    capsys.readouterr()

    assert cli.main(["inv", "find", "hdmi"]) == 0
    out = capsys.readouterr().out
    assert "BOX-07, Keller Regal 2" in out

    assert cli.main(["inv", "lend", "Akkuschrauber", "Max", "--due", "04.10.2026"]) == 0
    out = capsys.readouterr().out
    assert "Verliehen" in out

    assert cli.main(["inv", "loans"]) == 0
    out = capsys.readouterr().out
    assert "Akkuschrauber" in out
    assert "Max" in out

    # loan_id ist die erste (und einzige) Zeile -> #1
    assert cli.main(["inv", "return", "1"]) == 0
    out = capsys.readouterr().out
    assert "Zurückgegeben" in out

    assert cli.main(["inv", "loans"]) == 0
    out = capsys.readouterr().out
    assert "Keine offenen Verleihposten" in out


def test_box_add_doppelte_id_exit_1(app_home, capsys):
    assert cli.main(["inv", "box", "add", "BOX-07", "Keller"]) == 0
    capsys.readouterr()
    assert cli.main(["inv", "box", "add", "BOX-07", "Anderswo"]) == 1
    assert "Fehler" in capsys.readouterr().err


def test_box_rm_mit_inhalt_exit_1(app_home, capsys):
    cli.main(["inv", "box", "add", "BOX-07", "Keller"])
    cli.main(["inv", "add", "HDMI-Adapter", "--box", "BOX-07"])
    capsys.readouterr()
    assert cli.main(["inv", "box", "rm", "BOX-07"]) == 1
    assert "Fehler" in capsys.readouterr().err


def test_add_unbekannte_box_exit_1(app_home, capsys):
    assert cli.main(["inv", "add", "Kabel", "--box", "BOX-99"]) == 1
    assert "Fehler" in capsys.readouterr().err


def test_mv_und_rm_item(app_home, capsys):
    cli.main(["inv", "box", "add", "BOX-07", "Keller"])
    cli.main(["inv", "box", "add", "BOX-08", "Dachboden"])
    cli.main(["inv", "add", "Kabel", "--box", "BOX-07"])
    capsys.readouterr()

    assert cli.main(["inv", "mv", "1", "BOX-08"]) == 0
    out = capsys.readouterr().out
    assert "BOX-08" in out

    assert cli.main(["inv", "mv", "1", "-"]) == 0
    capsys.readouterr()

    assert cli.main(["inv", "rm", "1"]) == 0
    assert "Entfernt" in capsys.readouterr().out

    assert cli.main(["inv", "rm", "1"]) == 1
    assert "Fehler" in capsys.readouterr().err


# ---------- Label-Druck ----------

def test_label_box_preview_erzeugt_png_ohne_druck(app_home, capsys, tmp_path):
    cli.main(["inv", "box", "add", "BOX-07", "Keller Regal 2"])
    capsys.readouterr()

    png = tmp_path / "b.png"
    assert cli.main(["inv", "label", "box", "BOX-07", "--preview", str(png)]) == 0
    out = capsys.readouterr().out
    assert "Vorschau" in out
    with Image.open(png) as img:
        assert img.width > 0


def test_label_box_unbekannt_exit_1(app_home, capsys, tmp_path):
    png = tmp_path / "b.png"
    assert cli.main(["inv", "label", "box", "BOX-99", "--preview", str(png)]) == 1
    assert "Fehler" in capsys.readouterr().err


def test_label_content_und_loan_preview(app_home, capsys, tmp_path):
    cli.main(["inv", "box", "add", "BOX-07", "Keller Regal 2"])
    cli.main(["inv", "add", "HDMI-Adapter", "--box", "BOX-07"])
    cli.main(["inv", "lend", "Akkuschrauber", "Max"])
    capsys.readouterr()

    content_png = tmp_path / "content.png"
    assert cli.main(["inv", "label", "content", "BOX-07", "--preview", str(content_png)]) == 0
    capsys.readouterr()
    assert content_png.exists()

    loan_png = tmp_path / "loan.png"
    assert cli.main(["inv", "label", "loan", "1", "--preview", str(loan_png)]) == 0
    assert loan_png.exists()


# ---------- Zentrale Zähler ----------

def test_label_box_nutzt_zentralen_zaehler_genau_einmal(app_home, capsys, tmp_path, monkeypatch):
    numbering_dir = tmp_path / "zentral"
    config.save_config({"numbering": {"dir": str(numbering_dir)}})
    cli.main(["inv", "box", "add", "BOX-07", "Keller Regal 2"])
    capsys.readouterr()

    counter_calls = []
    original_counter_store = inv_cmd.numbering.counter_store

    def counter_spy(cfg):
        store = original_counter_store(cfg)
        counter_calls.append(store)
        return store

    render_calls = []
    original_render = inv_cmd.render_box_label

    def render_spy(box, profile, *, counters, **kw):
        render_calls.append(counters)
        return original_render(box, profile, counters=counters, **kw)

    monkeypatch.setattr(inv_cmd.numbering, "counter_store", counter_spy)
    monkeypatch.setattr(inv_cmd, "render_box_label", render_spy)

    png = tmp_path / "b.png"
    assert cli.main(["inv", "label", "box", "BOX-07", "--preview", str(png)]) == 0

    assert len(counter_calls) == 1
    assert len(render_calls) == 1
    assert render_calls[0] is counter_calls[0]
    assert counter_calls[0].path == numbering_dir / "counters.json"
    assert not (numbering_dir / "counters.json").exists()   # --preview: nichts committet
