"""Keine Gedankenstriche (Halbgeviertstrich U+2013, Geviertstrich U+2014) in eigenen Quelltexten,
Übersetzungen und Doku.

Statt eines Gedankenstrichs stehen Komma, Punkt, Doppelpunkt oder Klammern. Ausgenommen sind nur
Dateien Dritter, die unverändert bleiben müssen (Lizenztexte, eingebettete Daten von Icon-Sets,
Schriften, das npm-Lockfile) und das gebaute Web-Bundle, das aus `web/src` neu entsteht.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)

TEXT_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".txt", ".toml", ".cfg",
    ".ini", ".yaml", ".yml", ".ps1", ".psm1", ".psd1", ".sh", ".cmd", ".bat", ".css", ".html",
    ".svg", ".spec", ".gitignore",
}

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".superpowers", "dist", "build",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", ".claude"}

# Drittanbieter-Dateien und gebaute Artefakte (Pfade relativ zum Repo, mit "/").
EXEMPT_PREFIXES = (
    "src/tapesmith/webui/static/",   # gebautes Web-Bundle (tools/build_web.py)
    "src/tapesmith/fonts/",          # DejaVu-Schriften und ihre Lizenz
)
EXEMPT_FILES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "web/package-lock.json",
    "src/tapesmith/icons/LICENSE-tabler.txt",
    "src/tapesmith/icons/tabler-index.json",
    "src/tapesmith/icons/simple/LICENSE-simple-icons.txt",
    "src/tapesmith/icons/simple/index.json",
}


def _is_exempt(rel: str) -> bool:
    return rel in EXEMPT_FILES or rel.startswith(EXEMPT_PREFIXES)


def _own_text_files() -> list[Path]:
    files: list[Path] = []
    stack = [ROOT]
    while stack:
        folder = stack.pop()
        for entry in folder.iterdir():
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
                continue
            if entry.suffix.lower() not in TEXT_SUFFIXES and entry.name not in {"LICENSE"}:
                continue
            rel = entry.relative_to(ROOT).as_posix()
            if not _is_exempt(rel):
                files.append(entry)
    return sorted(files)


def _findings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    rel = path.relative_to(ROOT).as_posix()
    return [f"{rel}:{lineno}: {line.strip()[:120]!r}"
            for lineno, line in enumerate(text.splitlines(), start=1)
            if EN_DASH in line or EM_DASH in line]


def test_scan_findet_die_eigenen_quellen():
    rels = {p.relative_to(ROOT).as_posix() for p in _own_text_files()}
    for expected in ("README.md", "docs/handbuch.md", "src/tapesmith/cli.py",
                     "web/src/locales/de/einstellungen.json", "web/src/locales/en/einstellungen.json"):
        assert expected in rels, expected
    assert not any(rel.startswith("src/tapesmith/webui/static/") for rel in rels)


def test_keine_gedankenstriche_in_eigenen_dateien():
    hits = [hit for path in _own_text_files() for hit in _findings(path)]
    assert hits == [], "Gedankenstriche gefunden (Komma, Punkt, Doppelpunkt oder Klammern verwenden):\n" + "\n".join(hits)


def test_ausnahmen_sind_nur_drittanbieter_oder_build():
    for rel in EXEMPT_FILES:
        name = rel.rsplit("/", 1)[-1]
        assert (name.startswith(("LICENSE", "THIRD_PARTY")) or name.endswith(("index.json", "package-lock.json"))), rel
