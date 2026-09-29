"""Tests für das Git-Archiv der Drucke."""

from datetime import datetime

import pytest
from PIL import Image

from tapesmith.archive import (
    SecretFinding,
    archive_entry,
    archive_hook,
    entry_record,
    git_commit,
    scan_path,
    scan_secrets,
)
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintOutcome
from tapesmith.templates.fill import REDACTED

PROFILE = load_profile()
FIXED_NOW = datetime(2026, 9, 27, 10, 15, 0)


def fixed_clock():
    return FIXED_NOW


def make_head(width=None, height=200, fill=255):
    return Image.new("1", (width or PROFILE.head_dots, height), fill)


def make_landscape(width=40, height=30, fill=255):
    return Image.new("1", (width, height), fill)


# ---------- scan_secrets ----------

@pytest.mark.parametrize("text,kind", [
    ("password=Geheim123", "Passwort/Token-Zuweisung"),
    ('"api_key": "abcd1234"', "Passwort/Token-Zuweisung"),
    ("WIFI:T:WPA;S:Gast;P:supergeheim;;", "WLAN-Passwort"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "privater Schlüssel"),
    ("ghp_" + "a" * 36, "GitHub-Token"),
    ("AKIA" + "A" * 16, "AWS-Schlüssel"),
])
def test_scan_secrets_findet_je_ein_treffer_passender_art(text, kind):
    findings = scan_secrets(text)
    assert len(findings) == 1
    assert findings[0].kind == kind
    assert isinstance(findings[0], SecretFinding)


@pytest.mark.parametrize("text", [
    f"password={REDACTED}",
    "WIFI:T:WPA;S:Gast;P:;;",
    "SN 274913",
])
def test_scan_secrets_keine_treffer(text):
    assert scan_secrets(text) == []


def test_scan_path_datei(tmp_path):
    path = tmp_path / "geheim.txt"
    path.write_text("token=abcd1234efgh", encoding="utf-8")
    findings = scan_path(path)
    assert len(findings) == 1
    assert findings[0][0] == path
    assert findings[0][1].kind == "Passwort/Token-Zuweisung"


def test_scan_path_ordner_rekursiv(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "eins.json").write_text('{"password": "abcd1234"}', encoding="utf-8")
    (tmp_path / "zwei.md").write_text("nichts hier: SN 274913", encoding="utf-8")
    (tmp_path / "unwichtig.png").write_bytes(b"\x89PNG")
    findings = scan_path(tmp_path)
    assert len(findings) == 1
    assert findings[0][0].name == "eins.json"


# ---------- archive_entry ----------

def test_archive_entry_schreibt_json_und_png(tmp_path):
    with HistoryStore(tmp_path / "h.db", clock=fixed_clock) as store:
        meta = JobMeta(title="pmx10 SSD 1", source="cli", kind="text",
                       values={"a": "1"}, template="etikett")
        entry_id = store.record(meta, landscape=make_landscape(), head=make_head(),
                                length_mm=12.0, tape_mm=36.0, copies=1, chained=False, status="ok")
        entry = store.get(entry_id)
        head = store.head_image(entry_id)

    archive_dir = tmp_path / "archiv"
    files = archive_entry(entry, head, archive_dir, PROFILE)

    json_path = archive_dir / "2026" / "2026-09-27_101500_00001_pmx10-ssd-1.json"
    png_path = archive_dir / "2026" / "2026-09-27_101500_00001_pmx10-ssd-1.png"
    assert files == [json_path, png_path]
    assert json_path.exists()
    assert png_path.exists()

    import json as jsonlib
    data = jsonlib.loads(json_path.read_text(encoding="utf-8"))
    assert data["title"] == "pmx10 SSD 1"
    assert data["values"] == {"a": "1"}
    assert data["sensitive"] is False

    with Image.open(png_path) as png:
        assert png.mode == "1"
        assert png.width > png.height   # Querformat


def test_archive_entry_sensibel_nur_json_ohne_klartext(tmp_path):
    with HistoryStore(tmp_path / "h.db", clock=fixed_clock) as store:
        meta = JobMeta(title="WLAN Gast", source="gui", kind="qr", sensitive=True,
                       values={"ssid": "Gast", "password": REDACTED})
        entry_id = store.record(meta, landscape=make_landscape(), head=make_head(),
                                length_mm=10.0, tape_mm=20.0)
        entry = store.get(entry_id)
        head = store.head_image(entry_id)   # sensibel -> ohnehin kein Kopfbild gespeichert

    archive_dir = tmp_path / "archiv"
    files = archive_entry(entry, head, archive_dir, PROFILE)

    assert len(files) == 1
    assert files[0].suffix == ".json"

    import json as jsonlib
    data = jsonlib.loads(files[0].read_text(encoding="utf-8"))
    assert data["sensitive"] is True
    assert data["values"]["password"] == REDACTED
    assert REDACTED == "•••"
    assert "Gast" not in jsonlib.dumps(data["values"]) or data["values"]["ssid"] == "Gast"


def test_archive_entry_maskiert_klartext_geheimwert_bei_sensiblem_eintrag(tmp_path):
    """Zweites Netz: ein sensibler Eintrag mit einem Klartext-Geheimwert in einem
    verdächtig benannten Feld (kein REDACTED, z. B. weil eine Vorlage es nicht maskiert hat)
    wird im Archiv trotzdem maskiert."""
    with HistoryStore(tmp_path / "h.db", clock=fixed_clock) as store:
        meta = JobMeta(title="Zugang", source="cli", kind="text", sensitive=True,
                       values={"pin": "1234", "name": "Alice"})
        entry_id = store.record(meta, landscape=make_landscape(), head=None,
                                length_mm=10.0, tape_mm=20.0)
        entry = store.get(entry_id)

    record = entry_record(entry)
    assert record["values"]["pin"] == REDACTED
    assert record["values"]["name"] == "Alice"


# ---------- git_commit ----------

class FakeGitRunner:
    def __init__(self, rc_by_argv0=None):
        self.calls: list[list[str]] = []
        self._rc_by_argv0 = rc_by_argv0 or {}

    def __call__(self, argv, cwd):
        self.calls.append(argv)
        key = argv[1] if len(argv) > 1 else argv[0]
        rc = self._rc_by_argv0.get(key, 0)
        return rc, "", ""


def test_git_commit_erfolg(tmp_path):
    directory = tmp_path / "archiv"
    directory.mkdir()
    json_path = directory / "eintrag.json"
    json_path.write_text('{"title": "ok"}', encoding="utf-8")

    runner = FakeGitRunner()
    result = git_commit([json_path], directory, "Label #1: ok", runner=runner)

    assert result is None
    assert runner.calls[0][:2] == ["git", "rev-parse"]
    assert runner.calls[1][:2] == ["git", "add"]
    assert "--" in runner.calls[1]
    assert runner.calls[2][:2] == ["git", "commit"]
    assert all("push" not in call for call in runner.calls)


def test_git_commit_secret_verhindert_commit(tmp_path):
    directory = tmp_path / "archiv"
    directory.mkdir()
    json_path = directory / "eintrag.json"
    json_path.write_text('{"token": "abcd1234efgh"}', encoding="utf-8")

    runner = FakeGitRunner()
    result = git_commit([json_path], directory, "Label #1", runner=runner)

    assert result is not None
    assert "Nicht committet" in result
    assert not any(c[:2] == ["git", "add"] for c in runner.calls)
    assert not any(c[:2] == ["git", "commit"] for c in runner.calls)


def test_git_commit_kein_repo(tmp_path):
    directory = tmp_path / "archiv"
    directory.mkdir()
    json_path = directory / "eintrag.json"
    json_path.write_text('{"title": "ok"}', encoding="utf-8")

    runner = FakeGitRunner(rc_by_argv0={"rev-parse": 1})
    result = git_commit([json_path], directory, "Label #1", runner=runner)

    assert result is not None
    assert "Kein Git-Repo" in result


# ---------- archive_hook ----------

def _fixed_history_factory(path):
    return lambda: HistoryStore(path, clock=fixed_clock)


def _make_outcome(status: str, history_id=None) -> PrintOutcome:
    return PrintOutcome(status=status, plan=None, history_id=history_id)


def test_archive_hook_ohne_dir_gibt_none():
    assert archive_hook({}) is None
    assert archive_hook({"archive": {}}) is None
    assert archive_hook({"archive": {"dir": None}}) is None


def test_archive_hook_schreibt_dateien_bei_ok(tmp_path):
    db_path = tmp_path / "h.db"
    archive_dir = tmp_path / "archiv"
    with HistoryStore(db_path, clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(title="Hook-Label"), landscape=make_landscape(),
                                head=make_head(), length_mm=5.0, tape_mm=10.0, status="ok")

    hook = archive_hook({"archive": {"dir": str(archive_dir)}},
                        history_factory=_fixed_history_factory(db_path),
                        profile_loader=lambda: PROFILE)
    assert hook is not None

    notes = hook(_make_outcome("ok", history_id=entry_id))
    assert notes == []
    written = list((archive_dir / "2026").glob("*.json"))
    assert len(written) == 1


def test_archive_hook_ignoriert_nicht_ok(tmp_path):
    archive_dir = tmp_path / "archiv"
    hook = archive_hook({"archive": {"dir": str(archive_dir)}})
    assert hook is not None

    notes = hook(_make_outcome("abgebrochen", history_id=None))
    assert notes == []
    assert not archive_dir.exists() or not any(archive_dir.iterdir())


def test_archive_hook_fehler_wird_zu_hinweis_ohne_ausnahme(tmp_path):
    db_path = tmp_path / "h.db"
    # Ordner ist eine Datei -> Schreiben scheitert.
    blocked = tmp_path / "blocked"
    blocked.write_text("ich bin eine Datei, kein Ordner", encoding="utf-8")

    with HistoryStore(db_path, clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(title="Kaputt"), landscape=make_landscape(),
                                head=make_head(), length_mm=5.0, tape_mm=10.0, status="ok")

    hook = archive_hook({"archive": {"dir": str(blocked)}},
                        history_factory=_fixed_history_factory(db_path),
                        profile_loader=lambda: PROFILE)
    notes = hook(_make_outcome("ok", history_id=entry_id))
    assert len(notes) == 1
    assert notes[0].startswith("Archiv:")


def test_archive_hook_git_commit_mit_fake_runner(tmp_path):
    db_path = tmp_path / "h.db"
    archive_dir = tmp_path / "archiv"
    with HistoryStore(db_path, clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(title="Commit-Label"), landscape=make_landscape(),
                                head=make_head(), length_mm=5.0, tape_mm=10.0, status="ok")

    runner = FakeGitRunner()
    hook = archive_hook({"archive": {"dir": str(archive_dir), "git_commit": True}},
                        history_factory=_fixed_history_factory(db_path),
                        profile_loader=lambda: PROFILE, git_runner=runner)
    notes = hook(_make_outcome("ok", history_id=entry_id))
    assert notes == []
    assert any(c[:2] == ["git", "commit"] for c in runner.calls)
    assert all("push" not in c for c in runner.calls)
