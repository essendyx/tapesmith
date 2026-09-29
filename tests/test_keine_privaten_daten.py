"""Schutztests für die Veröffentlichung: keine persönlichen Daten im Repository.

1. Private Kennungen (Namen, Hosts, Adressen, Seriennummern ...) stehen in einer Datei AUSSERHALB
   des Repos, eine Zeile je regulärem Ausdruck (Python `re`, ohne Groß/Klein-Unterschied, Zeilen
   mit `#` am Anfang sind Kommentare). Ihr Pfad kommt aus der Umgebungsvariable
   `TAPESMITH_PRIVATE_PATTERNS` (Rückfall `P12_PRIVATE_PATTERNS`). Ohne Variable wird dieser Test
   übersprungen, so bleibt die Liste selbst privat. Durchsucht werden alle versionierten
   Textdateien (auch hexkodiert), alle Dateinamen und die Texte in PNG-Metadaten.

   Einzige Ausnahme: die öffentliche Adresse des Projekt-Repositorys in genau diesen Formen,
   `github:essendyx/tapesmith` (Standard-Update-Quelle) und `github.com/essendyx/tapesmith`
   (Links auf das Repository). Sie werden vor der Prüfung aus dem Text entfernt.

2. Ohne Liste läuft immer eine allgemeine Prüfung: keine konkreten privaten IPv4-Hostadressen
   (10/8, 172.16/12, 192.168/16) in Code, Vorlagen und Doku. Netzangaben in CIDR-Form
   (z. B. `192.168.0.0/16`) und die Basisadressen der drei Bereiche sind erlaubt. Beispiele nutzen
   die Dokumentationsnetze 192.0.2.0/24 und 198.51.100.0/24. Ausgenommen sind nur die unten
   benannten Testdateien der LAN- und Netzlogik, die private Adressen als Testdaten brauchen.
"""

from __future__ import annotations

import ipaddress
import os
import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_REPO_FORMS = ("github:essendyx/tapesmith", "github.com/essendyx/tapesmith")

# Testdaten der LAN- und Netzlogik: private Adressen sind hier Absicht (Adressen außerhalb bzw.
# innerhalb freigegebener Netze, Docker-Bridge, IPv4-Erkennung). Keine echte Infrastruktur.
LAN_TEST_FILES = {
    "tests/test_netinfo.py": "lokale Adressen und Netzprüfung",
    "tests/test_obsidian.py": "IPv4-Erkennung in Notizen",
    "tests/test_plausi.py": "IP außerhalb der erwarteten Netze",
    "tests/test_proxmox.py": "Auswahl der Gast-Adresse (Docker-Bridge, fremde Netze)",
    "tests/test_e2e_lan_automation.py": "Zugriff aus nicht freigegebenem Netz",
    "tests/test_webapi_access_roles.py": "LAN-Richtlinie, Adressen außerhalb des Netzes",
    "tests/test_webapi_lan.py": "Zugriff aus nicht freigegebenem Netz",
}

PRIVATE_BLOCKS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
BLOCK_BASES = {str(n.network_address) for n in PRIVATE_BLOCKS}
IPV4_RE = re.compile(r"(?<![0-9.])(\d{1,3}(?:\.\d{1,3}){3})(?![0-9])(/\d{1,2})?")


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        names = [n for n in out.stdout.decode("utf-8").split("\0") if n]
        if names:
            return names
    except (OSError, subprocess.CalledProcessError):
        pass
    skip = {".git", ".venv", "node_modules", "__pycache__", ".superpowers", "dist", "build"}
    result = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if path.is_file() and not any(part in skip for part in rel.parts):
            result.append(rel.as_posix())
    return result


def _text(raw: bytes) -> str | None:
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def png_texts(raw: bytes) -> list[str]:
    """Texte aus tEXt-, zTXt- und iTXt-Blöcken einer PNG-Datei."""
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return []
    texts, pos = [], 8
    while pos + 8 <= len(raw):
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        data = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if kind == b"tEXt":
                texts.append(data.decode("latin-1"))
            elif kind == b"zTXt":
                key, _, rest = data.partition(b"\x00")
                texts.append(key.decode("latin-1") + " " + zlib.decompress(rest[1:]).decode("latin-1"))
            elif kind == b"iTXt":
                key, _, rest = data.partition(b"\x00")
                compressed, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _tkey, _, value = rest.partition(b"\x00")
                if compressed:
                    value = zlib.decompress(value)
                texts.append(key.decode("latin-1") + " " + value.decode("utf-8", "replace"))
        except (zlib.error, IndexError, UnicodeDecodeError):
            texts.append(data.decode("latin-1", "replace"))
        if kind == b"IEND":
            break
    return texts


def _strip_allowed(text: str) -> str:
    for form in ALLOWED_REPO_FORMS:
        text = re.sub(re.escape(form), " ", text, flags=re.IGNORECASE)
    return text


def _load_patterns() -> list[re.Pattern]:
    path = os.environ.get("TAPESMITH_PRIVATE_PATTERNS") or os.environ.get("P12_PRIVATE_PATTERNS")
    if not path:
        pytest.skip("TAPESMITH_PRIVATE_PATTERNS nicht gesetzt (private Kennungsliste liegt außerhalb des Repos)")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    patterns = [re.compile(line.strip(), re.IGNORECASE) for line in lines
                if line.strip() and not line.lstrip().startswith("#")]
    assert patterns, "Kennungsliste ist leer"
    return patterns


_LITERAL = re.compile(r"^[A-Za-z0-9 _:-]+$")


def _hex_variants(pattern: re.Pattern) -> list[str]:
    """Hexform reiner Literal-Kennungen (z. B. Seriennummer in einem Protokoll-Mitschnitt)."""
    src = pattern.pattern.replace("\\b", "")
    if not _LITERAL.match(src) or len(src) < 6:
        return []
    return [src.encode("utf-8").hex(), src.upper().encode("utf-8").hex()]


def test_keine_privaten_kennungen():
    patterns = _load_patterns()
    findings: list[str] = []
    files = _tracked_files()
    for rel in files:
        for pattern in patterns:
            if pattern.search(_strip_allowed(rel)):
                findings.append(f"Dateiname {rel}: {pattern.pattern}")
        path = ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        chunks = png_texts(raw) if rel.lower().endswith(".png") else []
        text = _text(raw)
        if text is not None:
            chunks.append(text)
        for chunk in chunks:
            cleaned = _strip_allowed(chunk)
            lowered = cleaned.lower()
            for pattern in patterns:
                match = pattern.search(cleaned)
                if match:
                    line = cleaned.count("\n", 0, match.start()) + 1
                    findings.append(f"{rel}:{line}: {pattern.pattern}")
                for hexed in _hex_variants(pattern):
                    if hexed.lower() in lowered:
                        findings.append(f"{rel}: {pattern.pattern} (hexkodiert)")
    assert not findings, "Private Kennungen gefunden:\n" + "\n".join(sorted(set(findings)))


def _private_host(address: str, cidr: str | None) -> bool:
    if cidr or address in BLOCK_BASES:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in block for block in PRIVATE_BLOCKS)


def test_keine_privaten_ip_adressen():
    findings: list[str] = []
    for rel in _tracked_files():
        if rel in LAN_TEST_FILES:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        text = _text(path.read_bytes())
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in IPV4_RE.finditer(line):
                if _private_host(match.group(1), match.group(2)):
                    findings.append(f"{rel}:{number}: {match.group(0)}")
    assert not findings, ("Private IPv4-Hostadressen gefunden (Beispiele bitte aus 192.0.2.0/24 oder "
                          "198.51.100.0/24):\n" + "\n".join(findings))


def test_ausnahmeliste_zeigt_auf_vorhandene_dateien():
    for rel in LAN_TEST_FILES:
        assert (ROOT / rel).is_file(), f"veraltete Ausnahme: {rel}"


def test_png_texte_werden_gelesen():
    import io

    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Author", "Beispiel Autor")
    info.add_text("Comment", "komprimiert", zip=True)
    buffer = io.BytesIO()
    Image.new("1", (4, 4), 255).save(buffer, format="PNG", pnginfo=info)
    texts = " ".join(png_texts(buffer.getvalue()))
    assert "Beispiel Autor" in texts and "komprimiert" in texts
