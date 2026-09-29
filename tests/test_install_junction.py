"""Tests für `tapesmith.install.junction` (Verzeichnis-Junction `current`).

Echte Temp-Ordner (Junctions brauchen kein Adminrecht), nie außerhalb von `tmp_path`."""

from __future__ import annotations

import subprocess

import pytest

from tapesmith.install import junction


def _make_target(tmp_path, name, content="hallo"):
    target = tmp_path / name
    target.mkdir()
    (target / "datei.txt").write_text(content, encoding="utf-8")
    return target


# ---------- create_junction ----------

def test_create_junction_und_lesen(tmp_path):
    target = _make_target(tmp_path, "ziel-a")
    link = tmp_path / "current"

    junction.create_junction(link, target)

    assert link.is_dir()
    assert (link / "datei.txt").read_text(encoding="utf-8") == "hallo"
    gelesen = junction.read_junction(link)
    assert gelesen is not None
    assert gelesen.name == "ziel-a"


def test_create_junction_fehlendes_ziel_wirft(tmp_path):
    with pytest.raises(ValueError):
        junction.create_junction(tmp_path / "current", tmp_path / "gibt-es-nicht")


def test_create_junction_fallback_ueber_runner(tmp_path, monkeypatch):
    target = _make_target(tmp_path, "ziel-fallback")
    link = tmp_path / "current"
    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        link.mkdir()  # simuliert, was mklink /J täte (für den Test reicht ein Ordner)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(junction._winapi, "CreateJunction", None, raising=False)
    junction.create_junction(link, target, runner=fake_runner)

    assert calls
    assert calls[0][:3] == ["cmd", "/c", "mklink"]


def test_create_junction_fallback_fehlschlag_wirft(tmp_path, monkeypatch):
    target = _make_target(tmp_path, "ziel-fail")
    link = tmp_path / "current"

    def fake_runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Zugriff verweigert")

    monkeypatch.setattr(junction._winapi, "CreateJunction", None, raising=False)
    with pytest.raises(OSError):
        junction.create_junction(link, target, runner=fake_runner)


# ---------- read_junction ----------

def test_read_junction_kein_link_gibt_none(tmp_path):
    normaler_ordner = tmp_path / "normal"
    normaler_ordner.mkdir()
    assert junction.read_junction(normaler_ordner) is None


def test_read_junction_fehlender_pfad_gibt_none(tmp_path):
    assert junction.read_junction(tmp_path / "gibt-es-nicht") is None


# ---------- switch_junction ----------

def test_switch_junction_stellt_auf_neues_ziel_um(tmp_path):
    ziel_a = _make_target(tmp_path, "ziel-a", "A")
    ziel_b = _make_target(tmp_path, "ziel-b", "B")
    link = tmp_path / "current"
    junction.create_junction(link, ziel_a)

    junction.switch_junction(link, ziel_b)

    assert (link / "datei.txt").read_text(encoding="utf-8") == "B"
    # Inhalt des alten Ziels bleibt erhalten (nie shutil.rmtree auf den Link).
    assert (ziel_a / "datei.txt").read_text(encoding="utf-8") == "A"


def test_switch_junction_ohne_vorhandenen_link_legt_neu_an(tmp_path):
    ziel = _make_target(tmp_path, "ziel-neu")
    link = tmp_path / "current"

    junction.switch_junction(link, ziel)

    assert (link / "datei.txt").exists()


def test_switch_junction_entfernt_rest_von_new(tmp_path):
    ziel_a = _make_target(tmp_path, "ziel-a")
    ziel_b = _make_target(tmp_path, "ziel-b", "B")
    link = tmp_path / "current"
    junction.create_junction(link, ziel_a)
    # Rest einer abgebrochenen vorigen Umstellung simulieren.
    junction.create_junction(tmp_path / "current.new", ziel_a)

    junction.switch_junction(link, ziel_b)

    assert (link / "datei.txt").read_text(encoding="utf-8") == "B"
    assert not (tmp_path / "current.new").exists()


def test_switch_junction_mehrfach_bleibt_konsistent(tmp_path):
    ziel_a = _make_target(tmp_path, "ziel-a", "A")
    ziel_b = _make_target(tmp_path, "ziel-b", "B")
    ziel_c = _make_target(tmp_path, "ziel-c", "C")
    link = tmp_path / "current"

    junction.create_junction(link, ziel_a)
    junction.switch_junction(link, ziel_b)
    junction.switch_junction(link, ziel_c)

    assert (link / "datei.txt").read_text(encoding="utf-8") == "C"
    assert (ziel_a / "datei.txt").read_text(encoding="utf-8") == "A"
    assert (ziel_b / "datei.txt").read_text(encoding="utf-8") == "B"
