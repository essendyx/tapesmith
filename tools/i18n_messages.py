"""Meldungs-Katalog pflegen: Kennungen aus dem Quelltext sammeln und mit den Übersetzungen abgleichen.

Kennungen sind die deutschen Texte in `_t("...")`, `N_("...")` und `translate("...", ...)` unter
`src/tapesmith` (siehe `tapesmith.i18n`). Aufruf:

    python tools/i18n_messages.py            # fehlende und verwaiste Einträge je Sprache zeigen
    python tools/i18n_messages.py --prune    # verwaiste Einträge entfernen
    python tools/i18n_messages.py --stub D   # fehlende Einträge als {"deutsch": ""} in D/<sprache>.todo.json

`tests/test_i18n_messages.py` nutzt `collect_msgids` und `load_catalog` und verlangt Vollständigkeit.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "tapesmith"
CATALOG_DIR = SRC / "locales" / "messages"
LANGS = ("en",)
MARKERS = ("_t", "N_", "translate")


def _literal_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MARKERS \
                and node.args:
            yield node


def collect_msgids(src: Path = SRC) -> dict[str, list[str]]:
    """Alle Kennungen mit Fundstellen (`datei:zeile`)."""
    found: dict[str, list[str]] = {}
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _literal_calls(tree):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                found.setdefault(arg.value, []).append(where)
    return found


def fstring_calls(src: Path = SRC) -> list[str]:
    """Fundstellen, an denen ein f-String als Kennung übergeben wird (nicht erlaubt)."""
    bad = []
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _literal_calls(tree):
            if isinstance(node.args[0], ast.JoinedStr):
                bad.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return bad


def catalog_path(lang: str) -> Path:
    return CATALOG_DIR / f"{lang}.json"


def load_catalog(lang: str) -> dict[str, str]:
    path = catalog_path(lang)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_catalog(lang: str, data: dict[str, str]) -> None:
    text = json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1)
    catalog_path(lang).write_text(text + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prune", action="store_true", help="verwaiste Einträge entfernen")
    parser.add_argument("--stub", type=Path, metavar="ORDNER",
                        help="fehlende Einträge in ORDNER/<sprache>.todo.json schreiben")
    args = parser.parse_args(argv)
    ids = collect_msgids()
    status = 0
    for lang in LANGS:
        data = load_catalog(lang)
        missing = sorted(set(ids) - set(data))
        orphans = sorted(set(data) - set(ids))
        print(f"{lang}: {len(ids)} Kennungen, {len(missing)} fehlen, {len(orphans)} verwaist")
        if args.prune and orphans:
            for key in orphans:
                del data[key]
            write_catalog(lang, data)
        if args.stub and missing:
            args.stub.mkdir(parents=True, exist_ok=True)
            todo = args.stub / f"{lang}.todo.json"
            todo.write_text(json.dumps({k: "" for k in missing}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
            print(f"  -> {todo}")
        if missing:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
