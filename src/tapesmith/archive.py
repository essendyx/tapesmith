"""Git-Archiv der Drucke: jeder erfolgreiche Druck wird (wenn `archive.dir` gesetzt
ist) als JSON plus 1-Bit-PNG unter `<archive.dir>\\JJJJ\\` abgelegt. Sensible Drucke bekommen
kein PNG und im JSON werden verdächtige Werte zusätzlich maskiert. Ein optionaler Git-Commit
läuft nur nach bestandenem Secret-Scan, niemals `push`.

`archive_hook` wird vom Druckdienst und vom Direktdruck nach jedem Druck aufgerufen;
ein Fehler beim Archivieren darf den Druck selbst nie scheitern lassen.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from tapesmith import __version__
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.export import head_to_landscape
from tapesmith.fileutil import atomic_write_bytes, atomic_write_text
from tapesmith.history import HistoryEntry, HistoryStore
from tapesmith.templates.fill import REDACTED
from tapesmith.i18n import N_, _t

ArchiveHook = Callable[[Any], list[str]]                        # Any = pipeline.PrintOutcome
GitRunner = Callable[[list[str], Path], tuple[int, str, str]]

_UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}
_SLUG_MAX = 40
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SECRET_KEY = re.compile(r"(?i)(password|passwort|pw|pin|token|secret|key)")
_ARCHIVE_EXTS = ("*.json", "*.txt", "*.md", "*.csv")


@dataclass(frozen=True)
class SecretFinding:
    kind: str            # z. B. "privater Schlüssel", "Passwort/Token-Zuweisung", "WLAN-Passwort", …
    excerpt: str         # maskiert: erste 4 Zeichen + "…"


SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (N_("privater Schlüssel"), re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (N_("Passwort/Token-Zuweisung"), re.compile(
        r'(?i)\b(?:password|passwort|kennwort|pass|pwd|token|secret|api[_-]?key)\b'
        r'["\']?\s*[:=]\s*["\']?(?!•)([^\s"\',;]{4,})')),
    (N_("WLAN-Passwort"), re.compile(r"WIFI:[^\n]*?P:(?!;)([^;]+);")),
    ("GitHub-Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    (N_("AWS-Schlüssel"), re.compile(r"AKIA[0-9A-Z]{16}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
)


def _mask(value: str) -> str:
    return f"{value[:4]}…"


def scan_secrets(text: str) -> list[SecretFinding]:
    """Alle verdächtigen Muster in `text`; REDACTED-Werte (`templates.fill.REDACTED`) zählen
    nicht (die Muster schließen sie per negativem Lookahead aus)."""
    findings: list[SecretFinding] = []
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1) if match.groups() else match.group(0)
            findings.append(SecretFinding(kind=_t(kind), excerpt=_mask(value)))
    return findings


def scan_path(path: Path) -> list[tuple[Path, SecretFinding]]:
    """Secret-Scan über eine einzelne Datei oder rekursiv über `*.json`/`*.txt`/`*.md`/`*.csv`
    eines Ordners. Unlesbare Dateien werden übersprungen, nie eine Ausnahme."""
    path = Path(path)
    if path.is_file():
        files = [path]
    else:
        files = sorted({f for pattern in _ARCHIVE_EXTS for f in path.rglob(pattern)})
    results: list[tuple[Path, SecretFinding]] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for finding in scan_secrets(text):
            results.append((file, finding))
    return results


def _slug(text: str) -> str:
    for umlaut, ascii_ in _UMLAUT.items():
        text = text.replace(umlaut, ascii_)
    text = _NON_SLUG.sub("-", text.lower()).strip("-")
    return (text or "label")[:_SLUG_MAX].strip("-") or "label"


def entry_record(entry: HistoryEntry) -> dict:
    """JSON-Datensatz für das Archiv: bei sensiblen Einträgen wird jeder Wert, dessen
    Schlüsselname nach einem Geheimnis aussieht und der nicht schon REDACTED ist, zusätzlich
    maskiert (der Verlauf maskiert Vorlagenwerte bereits; das hier ist ein zweites Netz für
    freie Werte wie Zwischenablage-Text). Der Titel bleibt unverändert."""
    values = dict(entry.values)
    if entry.sensitive:
        values = {k: (REDACTED if (_SECRET_KEY.search(k) and v != REDACTED) else v)
                  for k, v in values.items()}
    return {
        "id": entry.id,
        "created": entry.created.isoformat(),
        "source": entry.source,
        "kind": entry.kind,
        "title": entry.title,
        "template": entry.template,
        "values": values,
        "length_mm": entry.length_mm,
        "tape_mm": entry.tape_mm,
        "copies": entry.copies,
        "chained": entry.chained,
        "status": entry.status,
        "sensitive": entry.sensitive,
        "app_version": __version__,
    }


def _save_png(path: Path, image: Image.Image) -> None:
    buf = BytesIO()
    image.save(buf, "PNG")
    atomic_write_bytes(path, buf.getvalue())


def archive_entry(entry: HistoryEntry, head: Image.Image | None, directory: Path,
                  profile: DeviceProfile) -> list[Path]:
    """Legt einen Verlaufseintrag unter `directory/JJJJ/` ab: immer die JSON, dazu ein
    1-Bit-Querformat-PNG, wenn ein Kopfbild vorliegt und der Eintrag nicht sensibel ist."""
    year_dir = Path(directory) / f"{entry.created.year}"
    base = f"{entry.created:%Y-%m-%d_%H%M%S}_{entry.id:05d}_{_slug(entry.title)}"
    json_path = year_dir / f"{base}.json"
    atomic_write_text(json_path, json.dumps(entry_record(entry), indent=2, ensure_ascii=False, sort_keys=True))
    paths = [json_path]
    if head is not None and not entry.sensitive:
        png_path = year_dir / f"{base}.png"
        _save_png(png_path, head_to_landscape(head, profile).convert("1"))
        paths.append(png_path)
    return paths


def _default_git_runner(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def git_commit(files: Sequence[Path], directory: Path, message: str, *,
              runner: GitRunner | None = None) -> str | None:
    """Committet `files` (relativ zu `directory`), niemals `push`. Vorher ein Secret-Scan über
    alle `.json`-Dateien: ein Treffer verhindert den Commit. Rückgabe `None` bei Erfolg, sonst
    ein deutscher Hinweis."""
    directory = Path(directory)
    run = runner if runner is not None else _default_git_runner

    for file in files:
        file = Path(file)
        if file.suffix != ".json":
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        findings = scan_secrets(text)
        if findings:
            return _t("Nicht committet: {kind} in {file}", kind=findings[0].kind, file=file)

    rc, _out, _err = run(["git", "rev-parse", "--is-inside-work-tree"], directory)
    if rc != 0:
        return _t("Kein Git-Repo: {directory}", directory=directory)

    rel = [Path(f).relative_to(directory).as_posix() for f in files]
    rc, out, err = run(["git", "add", "--", *rel], directory)
    if rc != 0:
        return _t("Git-Commit fehlgeschlagen: {strip}", strip=(err or out).strip())
    rc, out, err = run(["git", "commit", "-m", message, "--", *rel], directory)
    if rc != 0:
        return _t("Git-Commit fehlgeschlagen: {strip}", strip=(err or out).strip())
    return None


def archive_hook(cfg: dict, *, history_factory: Callable[[], HistoryStore] = HistoryStore,
                 profile_loader: Callable[[], DeviceProfile] | None = None,
                 git_runner: GitRunner | None = None) -> ArchiveHook | None:
    """Baut den Archiv-Hook aus der Konfiguration; `None`, wenn `archive.dir` fehlt (Default wie
    in `SECTION_DEFAULTS`: `{"dir": None, "git_commit": False}`). Der Hook fängt jede Ausnahme,
    denn ein Druck darf nie am Archiv scheitern."""
    archive_cfg = cfg.get("archive") or {}
    directory = archive_cfg.get("dir")
    if not directory:
        return None
    directory = Path(directory)
    do_commit = bool(archive_cfg.get("git_commit", False))

    def hook(outcome) -> list[str]:
        if outcome.status != "ok" or outcome.history_id is None:
            return []
        try:
            with history_factory() as store:
                entry = store.get(outcome.history_id)
                head = store.head_image(outcome.history_id)
            profile = profile_loader() if profile_loader is not None else load_profile()
            files = archive_entry(entry, head, directory, profile)
            notes: list[str] = []
            if do_commit:
                message = f"Label #{entry.id}: {entry.title}"
                result = git_commit(files, directory, message, runner=git_runner)
                if result is not None:
                    notes.append(result)
            return notes
        except Exception as exc:  # noqa: BLE001 (ein Druck darf nie am Archiv scheitern)
            return [_t("Archiv: {exc}", exc=exc)]

    return hook
