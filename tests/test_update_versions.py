"""Versionsauswahl: Liste aller installierbaren Versionen, ausdrückliche Installation einer
bestimmten (auch älteren) Version mit Sicherung, Signaturpflicht, gescheiterte Versionen."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

from tapesmith.install import layout
from tapesmith.update.errors import UpdateError
from tapesmith.update.service import UpdateService
from tapesmith.update.sources import FileSource
from update_fakes import FakeVenvRun, install_layout, make_test_key, publish_dir


def _service(tmp_path: Path, *, versions=("0.1.0", "0.2.0"), installed=True, channel="stable", backup=None,
             source_factory=None, clock=None):
    private, keys = make_test_key()
    feed = tmp_path / "feed"
    root = tmp_path / "root"
    if installed:
        install_layout(root, versions=versions)
        exe = str(layout.version_dir(versions[-1], root) / "Scripts" / "pythonw.exe")
    else:
        exe = sys.executable
    spawned: list = []
    backups: list = []
    cfg = {"update": {"source": f"file:{feed}", "channel": channel}}

    def default_backup(c):
        backups.append(c)
        return tmp_path / "sicherung.zip"

    kwargs = {}
    if source_factory is not None:
        kwargs["source_factory"] = source_factory
    svc = UpdateService(lambda: cfg, keys_loader=lambda: keys, root=root, spawn=spawned.append, run=FakeVenvRun(),
                        now=lambda: datetime(2026, 10, 2, 8, 0), executable=exe, app_version=lambda: versions[-1],
                        backup=backup or default_backup, clock=clock or (lambda: 1000.0), **kwargs)
    return svc, private, feed, root, spawned, backups


def _feed(feed: Path, private, *specs) -> None:
    """Je Version ein Unterordner; die höchste zusätzlich direkt im Ordner (wie bisher)."""
    for version, channel in specs:
        publish_dir(feed / version, version, private, channel=channel, notes=f"Neu in {version}")
    top = max(specs, key=lambda s: layout.parse_version(s[0]))
    publish_dir(feed, top[0], private, channel=top[1], notes=f"Neu in {top[0]}")


def test_liste_quelle_und_lokal_neueste_zuerst(tmp_path):
    svc, private, feed, _root, _spawned, _b = _service(tmp_path)
    _feed(feed, private, ("0.1.5", "stable"), ("0.3.0", "stable"), ("0.4.0b1", "beta"))
    data = svc.versions()
    assert data["error"] is None and data["current"] == "0.2.0"
    rows = {v["version"]: v for v in data["versions"]}
    assert [v["version"] for v in data["versions"]] == ["0.3.0", "0.2.0", "0.1.5", "0.1.0"]
    assert rows["0.3.0"]["newer"] and not rows["0.3.0"]["installed"] and rows["0.3.0"]["notes"] == "Neu in 0.3.0"
    assert rows["0.2.0"]["current"] and rows["0.2.0"]["installed"]
    assert rows["0.1.0"]["installed"] and not rows["0.1.0"]["in_source"] and not rows["0.1.0"]["newer"]
    # Vorabversionen nur auf Wunsch bzw. im Kanal beta
    assert "0.4.0b1" in [v["version"] for v in svc.versions(include_prerelease=True)["versions"]]


def test_kanal_beta_zeigt_vorabversionen(tmp_path):
    svc, private, feed, *_ = _service(tmp_path, channel="beta")
    _feed(feed, private, ("0.3.0", "stable"), ("0.4.0b1", "beta"))
    assert [v["version"] for v in svc.versions()["versions"]][0] == "0.4.0b1"


def test_liste_wird_zwischengespeichert(tmp_path):
    calls = []
    now = [1000.0]

    def factory(text, **kw):
        source = FileSource(Path(text[len("file:"):]))
        original = source.list_releases

        def counted():
            calls.append(1)
            return original()

        source.list_releases = counted
        return source

    svc, private, feed, *_ = _service(tmp_path, source_factory=factory, clock=lambda: now[0])
    _feed(feed, private, ("0.3.0", "stable"))
    svc.versions()
    svc.versions()
    assert len(calls) == 1
    svc.versions(refresh=True)
    assert len(calls) == 2
    now[0] += 601
    svc.versions()
    assert len(calls) == 3


def test_quelle_nicht_erreichbar_zeigt_lokale_versionen(tmp_path):
    svc, _private, _feed_dir, *_ = _service(tmp_path)   # Ordner fehlt
    data = svc.versions()
    assert data["error"]["code"] == "update.source_unreachable"
    assert [v["version"] for v in data["versions"]] == ["0.2.0", "0.1.0"]


def test_aeltere_version_nur_ausdruecklich_mit_sicherung(tmp_path):
    svc, private, feed, root, spawned, backups = _service(tmp_path)
    _feed(feed, private, ("0.1.5", "stable"), ("0.3.0", "stable"))
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.1.5")
    assert info.value.code == "update.apply_failed"
    assert svc.is_downgrade("0.1.5") and not svc.is_downgrade("0.3.0")
    target = svc.prepare("0.1.5", explicit=True)
    assert target == layout.version_dir("0.1.5", root)
    with pytest.raises(UpdateError):
        svc.start_install("0.1.5")          # ohne explicit nie zurück
    assert spawned == [] and backups == []
    argv = svc.start_install("0.1.5", explicit=True)
    assert argv[argv.index("--version") + 1] == "0.1.5"
    assert len(backups) == 1 and spawned == [argv]


def test_lokal_vorhandene_aeltere_version_ohne_download(tmp_path):
    svc, _private, _feed_dir, _root, spawned, backups = _service(tmp_path)
    svc.prepare("0.1.0", explicit=True)     # liegt schon unter versions, keine Quelle nötig
    svc.start_install("0.1.0", explicit=True)
    assert backups and spawned


def test_sicherung_scheitert_nichts_umgestellt(tmp_path):
    def broken(_cfg):
        raise OSError("voll")

    svc, _private, _feed_dir, _root, spawned, _b = _service(tmp_path, backup=broken)
    with pytest.raises(UpdateError) as info:
        svc.start_install("0.1.0", explicit=True)
    assert info.value.code == "update.apply_failed" and spawned == []


def test_aktive_version_wird_nicht_erneut_installiert(tmp_path):
    svc, *_ = _service(tmp_path)
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.2.0", explicit=True)
    assert "bereits installiert" in str(info.value)


def test_signatur_ist_pflicht(tmp_path):
    svc, private, feed, root, spawned, _b = _service(tmp_path)
    _feed(feed, private, ("0.1.5", "stable"), ("0.3.0", "stable"))
    other, _keys = make_test_key()
    publish_dir(feed / "0.1.5", "0.1.5", other)   # mit fremdem Schlüssel signiert
    with pytest.raises(UpdateError) as info:
        svc.prepare("0.1.5", explicit=True)
    assert info.value.code.startswith("update.signature")
    assert not layout.version_dir("0.1.5", root).exists() and spawned == []


def test_gescheiterte_version_wird_nicht_installiert_und_markiert(tmp_path):
    svc, private, feed, root, spawned, _b = _service(tmp_path)
    _feed(feed, private, ("0.1.5", "stable"))
    st = layout.read_state(root)
    st.failed.append("0.1.5")
    layout.write_state(st, root)
    assert {v["version"]: v for v in svc.versions()["versions"]}["0.1.5"]["failed"] is True
    with pytest.raises(UpdateError):
        svc.prepare("0.1.5", explicit=True)
    with pytest.raises(UpdateError):
        svc.start_install("0.1.5", explicit=True)
    assert spawned == []


def test_vorabversion_ausdruecklich_im_kanal_stable(tmp_path):
    svc, private, feed, root, _spawned, _b = _service(tmp_path)
    _feed(feed, private, ("0.3.0", "stable"), ("0.4.0b1", "beta"))
    with pytest.raises(UpdateError):
        svc.prepare("0.4.0b1")
    assert svc.prepare("0.4.0b1", explicit=True) == layout.version_dir("0.4.0b1", root)
