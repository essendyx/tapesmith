"""Support-Bericht „Problem melden“, Qt-frei.

`build_report` erzeugt ein Zip mit `bericht.txt` (Version, Python, Windows, Betriebsart, Transport,
Druckerstatus, Warteschlange), `config.json` (maskiert) und den Protokollen aus `paths.log_dir()`
(je Datei höchstens die letzten 512 KB, maskiert). Tokens, Passwörter und Schlüssel werden ersetzt,
Secret-Referenzen (`keyring:`, `file:`, `env:`) bleiben lesbar. Nichts wird verschickt: das Zip
gibt der Nutzer selbst weiter.
"""

from __future__ import annotations

import copy
import io
import json
import os
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PureWindowsPath

import tapesmith
from tapesmith import paths, secretref
from tapesmith.i18n import N_, _t

MAX_LOG_BYTES = 512 * 1024
MASK = "***"
TRUNCATED_NOTE = N_("[gekürzt: nur die letzten 512 KB]\n")

_LOG_NAME_RE = re.compile(r"^[^\\/]+\.log(\.[123])?$")
_SECRET_PARTS = ("token", "password", "passwort", "secret", "kennwort")
_TEXT_PATTERNS = (
    re.compile(r"(?i)(X-P12-Token\s*[:=]\s*)[^\s,;\"']+"),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(\bAuthorization\s*[:=]\s*(?!Bearer\b)[A-Za-z]+\s+)[^\s,;\"']+"),
    re.compile(r"(?<![A-Za-z0-9_])(t=)[^&\s#\"'<>]+"),
    re.compile(r"(?i)((?:token|password|passwort|secret|api_?key)[\"']?\s*[:=]\s*[\"']?)"
               r"(?!\*\*\*)(?!(?:keyring|file|env):)[^\"'\s&,;}]+"),
)


def report_filename(now: datetime) -> str:
    return f"tapesmith-bericht-{now:%Y%m%d-%H%M}.zip"


def mask_text(text: str) -> str:
    """Ersetzt Tokens in Protokoll- oder Konfigurationstext (`X-P12-Token: …`, `Bearer …`,
    `t=…`, `#t=…`, `token=…`, `password: …`) durch `***`."""
    for pattern in _TEXT_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return text


def _secret_key(name: str) -> bool:
    lowered = name.casefold()
    if any(part in lowered for part in _SECRET_PARTS):
        return True
    return "key" in re.split(r"[_.\-\s]+", lowered) or lowered.endswith("apikey")


def _mask_value(value, secret: bool):
    if isinstance(value, dict):
        return {k: _mask_value(v, secret or _secret_key(str(k))) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v, secret) for v in value]
    if isinstance(value, str):
        if secretref.is_ref(value):
            return value
        if secret and value:
            return MASK
        return mask_text(value)
    return value


def mask_config(cfg: dict) -> dict:
    """Kopie von `cfg`, in der jeder Text unter einem Schlüssel mit `token`, `password`, `secret`
    oder `key` zu `***` wird; Secret-Referenzen, Zahlen, Schalter und None bleiben stehen."""
    return {k: _mask_value(copy.deepcopy(v), _secret_key(str(k))) for k, v in cfg.items()}


def run_mode(*, executable: str | None = None, frozen: bool | None = None,
             localappdata: str | None = None) -> str:
    """`installiert` (unter `%LOCALAPPDATA%\\Programs\\Tapesmith`), `portabel` (gebaute EXE) oder
    `Entwicklung`."""
    executable = sys.executable if executable is None else executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    localappdata = os.environ.get("LOCALAPPDATA", "") if localappdata is None else localappdata
    if localappdata:
        root = PureWindowsPath(localappdata, "Programs", "Tapesmith")
        exe = PureWindowsPath(executable)
        if str(exe).casefold().startswith(str(root).casefold() + "\\"):
            return "installiert"
    return "portabel" if frozen else _t("Entwicklung")


def _jobs_text(queue) -> str:
    if isinstance(queue, dict):
        jobs = queue.get("jobs")
        count = len(jobs) if isinstance(jobs, list) else None
    elif isinstance(queue, int) and not isinstance(queue, bool):
        count = queue
    else:
        count = None
    if count is None:
        return "unbekannt"
    return _t("1 Auftrag") if count == 1 else _t("{count} Aufträge", count=count)


def decoder_line() -> str:
    """Status des optionalen Barcode-Decoders (zxing-cpp) für den Bericht."""
    from tapesmith.render import zxing  # spät: der Bericht soll auch ohne Renderer bauen

    try:
        return _t("Barcode-Decoder: {status_text}", status_text=zxing.status_text())
    except Exception as exc:  # noqa: BLE001 (Bericht nie am Status scheitern lassen)
        return _t("Barcode-Decoder: unbekannt ({exc})", exc=exc)


def _report_text(cfg: dict, status: dict | None, now: datetime) -> str:
    lines = [
        _t("Tapesmith: Problembericht"),
        _t("Erstellt: {isoformat}", isoformat=now.isoformat(sep=' ', timespec='seconds')),
        _t("Version: {version}", version=tapesmith.__version__),
        f"Python: {platform.python_version()}",
        f"Windows: {platform.platform()}",
        _t("Betrieb: {run_mode}", run_mode=run_mode()),
        f"Transport: {cfg.get('transport', 'auto')}",
        decoder_line(),
    ]
    if status is None:
        lines.append(_t("Drucker: unbekannt (Druckdienst nicht erreichbar)"))
        lines.append(_t("Warteschlange: unbekannt"))
    else:
        view = status.get("view") if isinstance(status.get("view"), dict) else {}
        title = view.get("title") or view.get("chip") or _t("unbekannt")
        lines.append(_t("Drucker: {title}", title=title))
        detail = str(view.get("detail") or "").strip()
        if detail:
            lines.append(_t("Details:"))
            lines.extend(f"  {line}" for line in detail.splitlines())
        lines.append(_t("Warteschlange: {jobs_text}", jobs_text=_jobs_text(status.get('queue'))))
    lines += ["", _t("Tokens, Passwörter und Schlüssel sind in diesem Bericht durch *** ersetzt.")]
    return mask_text("\n".join(lines) + "\n")


def _log_files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and _LOG_NAME_RE.match(p.name))
    except OSError:
        return []


def _read_tail(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > MAX_LOG_BYTES:
            handle.seek(size - MAX_LOG_BYTES)
            data = handle.read()
            newline = data.find(b"\n")
            if 0 <= newline < len(data) - 1:
                data = data[newline + 1:]
            return _t(TRUNCATED_NOTE) + data.decode("utf-8", errors="replace")
        return handle.read().decode("utf-8", errors="replace")


def build_report(cfg: dict, *, status: dict | None, now: datetime) -> bytes:
    """Zip-Bytes des Support-Berichts (siehe Moduldokumentation)."""
    buffer = io.BytesIO()
    stamp = (now.year, now.month, now.day, now.hour, now.minute, now.second)

    def add(name: str, text: str) -> None:
        info = zipfile.ZipInfo(name, date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, text.encode("utf-8"))

    with zipfile.ZipFile(buffer, "w") as archive:
        add("bericht.txt", _report_text(cfg, status, now))
        add("config.json", json.dumps(mask_config(cfg), ensure_ascii=False, indent=2, default=str) + "\n")
        for path in _log_files(paths.log_dir()):
            try:
                text = _read_tail(path)
            except OSError as exc:
                text = _t("[nicht lesbar: {exc}]\n", exc=exc)
            add(f"logs/{path.name}", mask_text(text))
    return buffer.getvalue()
