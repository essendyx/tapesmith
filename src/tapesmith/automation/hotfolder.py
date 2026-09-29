"""Addon Hotfolder: überwachter Ordner für Stapeldruck.

`Hotfolder` pollt `root` selbst (kein `watchdog`, läuft auch auf SMB-Freigaben zuverlässig). Jede
`*.json`, `*.txt`, `*.csv`, `*.png`-Datei wird zu einem oder mehreren Druckaufträgen (Quelle
`hotfolder`) über die Fassade (`tapesmith.automation.facade.LabelFacade` bzw. den HTTP-Adapter
`HttpPrinter` aus `cli_cmds/hotfolder.py`). Erfolgreiche Dateien wandern nach `done\\`, fehlerhafte
nach `error\\` mit einer `.log`-Datei daneben. Ein rotierendes Protokoll `hotfolder.log` hält jede
Verarbeitung fest, sensible Werte (Vorlagenfelder mit `secret: true`) nur maskiert.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tapesmith import config, paths, sourcelimits
from tapesmith.dataimport.mapping import apply_mapping, auto_map
from tapesmith.dataimport.table import read_csv
from tapesmith.pipeline import DOUBLE_PRESS_REASON
from tapesmith.templates.fill import REDACTED
from tapesmith.i18n import _t

__all__ = ["Hotfolder", "ProcessResult", "create"]

_LOG_NAME = "tapesmith.hotfolder"
_FORMATS = (".json", ".txt", ".csv", ".png")

log = logging.getLogger(__name__)


class _HotfolderError(ValueError):
    """Interner Fehler beim Verarbeiten einer Hotfolder-Datei (deutsche Meldung, kein Druck)."""


@dataclass
class _Job:
    source: dict
    options: dict  # vollstaendiges Options-Dict aus der Datei (u. a. "copies", "confirmed")

    @property
    def copies(self) -> object:
        return self.options.get("copies", 1)


@dataclass
class _MergedJob:
    source: dict
    options: dict  # Options ohne "copies" (nach der Zusammenfassung), z. B. "confirmed", "cut_marks"
    copies: int
    count: int


@dataclass
class ProcessResult:
    file: str
    ok: bool
    jobs: int
    message: str
    moved_to: str


def _is_ignored_name(name: str) -> bool:
    if name.startswith("~") or name.startswith("."):
        return True
    lower = name.lower()
    return lower.endswith(".tmp") or lower.endswith(".part")


class Hotfolder:
    """Überwacht `root` und druckt abgelegte Dateien über `facade` (Quelle `hotfolder`)."""

    name = "hotfolder"

    def __init__(self, facade, root: Path, *, poll_s: float = 2.0, settle_s: float = 1.5,
                 max_bytes: int = 2_000_000, clock=time.monotonic, now=datetime.now,
                 sleep_event: threading.Event | None = None, sleep=time.sleep,
                 retry_delay_s: float = 1.6):
        self.facade = facade
        self.root = Path(root)
        self.done_dir = self.root / "done"
        self.error_dir = self.root / "error"
        self._poll_s = float(poll_s)
        self._settle_s = float(settle_s)
        self._max_bytes = int(max_bytes)
        self._clock = clock
        self._now = now
        self._sleep = sleep
        self._retry_delay_s = float(retry_delay_s)
        self._stop_event = sleep_event if sleep_event is not None else threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, float, float]] = {}
        self._pending: dict[tuple[str, int, float], dict] = {}
        self._ignored_logged: set[str] = set()
        self._processed = 0
        self._errors = 0
        self._last_error: str | None = None
        self._log_handler: RotatingFileHandler | None = None
        self._log = logging.getLogger(_LOG_NAME)

    # ---------- Lebenszyklus ----------

    def start(self) -> None:
        self._ensure_dirs()
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="p12-hotfolder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001: der Thread darf nie sterben
                self._last_error = str(exc)
                log.error("Hotfolder-Durchlauf fehlgeschlagen: %s", exc)
            self._stop_event.wait(self._poll_s)

    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        detail = _t("{root} · {processed} verarbeitet, {errors} Fehler", root=self.root, processed=self._processed, errors=self._errors)
        return {"name": self.name, "running": running, "error": self._last_error, "detail": detail}

    # ---------- Ordner/Protokoll ----------

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.done_dir.mkdir(parents=True, exist_ok=True)
        self.error_dir.mkdir(parents=True, exist_ok=True)
        if self._log_handler is not None:
            return
        handler = RotatingFileHandler(self.root / "hotfolder.log", maxBytes=500_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger = logging.getLogger(_LOG_NAME)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        for old in list(logger.handlers):
            logger.removeHandler(old)
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        logger.addHandler(handler)
        self._log_handler = handler
        self._log = logger

    # ---------- Ein Durchlauf ----------

    def scan_once(self) -> list[ProcessResult]:
        self._ensure_dirs()
        results: list[ProcessResult] = []
        try:
            entries = sorted((p for p in self.root.iterdir() if p.is_file()), key=lambda p: p.name)
        except OSError as exc:
            self._last_error = str(exc)
            return results
        now = self._clock()
        seen_now: set[str] = set()
        for path in entries:
            key_path = str(path)
            seen_now.add(key_path)
            try:
                st = path.stat()
            except OSError:
                continue
            key = (key_path, st.st_size, st.st_mtime)
            if key in self._pending:
                result = self._retry_pending(path, key)
                if result is not None:
                    results.append(result)
                continue
            name = path.name
            if _is_ignored_name(name):
                continue
            if path.suffix.lower() not in _FORMATS:
                self._log_ignored_once(path)
                continue
            if not self._stable(key_path, st.st_size, st.st_mtime, now):
                continue
            if not self._openable(path):
                continue
            results.append(self._process_file(path, st))
        for tracked in list(self._seen):
            if tracked not in seen_now:
                self._seen.pop(tracked, None)
        return results

    def _log_ignored_once(self, path: Path) -> None:
        key = str(path)
        if key in self._ignored_logged:
            return
        self._ignored_logged.add(key)
        self._log.info("IGNORIERT %s: Dateityp wird nicht verarbeitet", path.name)

    def _stable(self, key: str, size: int, mtime: float, now: float) -> bool:
        if self._settle_s <= 0:
            return True
        prev = self._seen.get(key)
        if prev is None or prev[0] != size or prev[1] != mtime:
            self._seen[key] = (size, mtime, now)
            return False
        return (now - prev[2]) >= self._settle_s

    @staticmethod
    def _openable(path: Path) -> bool:
        try:
            with open(path, "rb"):
                return True
        except PermissionError:
            return False

    # ---------- Verarbeitung je Datei ----------

    def _process_file(self, path: Path, st) -> ProcessResult:
        key = (str(path), st.st_size, st.st_mtime)
        try:
            if st.st_size > self._max_bytes:
                raise _HotfolderError(
                    _t("Datei ist zu groß ({st_size} Bytes, erlaubt sind höchstens {max_bytes} Bytes)", st_size=st.st_size, max_bytes=self._max_bytes))
            cfg = self.facade.config()
            jobs, summaries = self._build_jobs(path, cfg)
            for job in jobs:
                err = sourcelimits.copies_error(cfg, "hotfolder", job.copies)
                if err:
                    raise _HotfolderError(err)
            merged = self._merge_jobs(jobs)
            limit = sourcelimits.max_copies(cfg, "hotfolder")
            for group in merged:
                if group.copies > limit:
                    raise _HotfolderError(
                        _t("Datei enthält {count} gleiche Aufträge (zusammen {copies} Kopien), erlaubt sind höchstens {limit} Kopien je Auftrag", count=group.count, copies=group.copies, limit=limit))
            ok, done, message = self._print_all(merged, summaries, cfg)
        except _HotfolderError as exc:
            return self._finish(path, key, ok=False, jobs=0, message=str(exc))
        except Exception as exc:  # noqa: BLE001: eine kaputte Datei darf den Hotfolder nicht stoppen
            return self._finish(path, key, ok=False, jobs=0, message=str(exc))
        return self._finish(path, key, ok=ok, jobs=done, message=message)

    def _finish(self, path: Path, key: tuple[str, int, float], *, ok: bool, jobs: int,
               message: str) -> ProcessResult:
        if ok:
            self._processed += 1
            target_dir, target_name = self.done_dir, "done"
        else:
            self._errors += 1
            target_dir, target_name = self.error_dir, "error"
        self._log.info("%s %s %d Aufträge: %s", "OK" if ok else "FEHLER", path.name, jobs, message)
        self._seen.pop(str(path), None)
        dest = self._unique_dest(target_dir, path.name)
        if self._do_move(path, dest):
            if not ok:
                self._write_sidecar(dest, message)
            return ProcessResult(file=path.name, ok=ok, jobs=jobs, message=message, moved_to=str(dest))
        self._pending[key] = {"target": target_name, "ok": ok, "jobs": jobs, "message": message}
        return ProcessResult(file=path.name, ok=ok, jobs=jobs, message=message, moved_to=str(dest))

    def _retry_pending(self, path: Path, key: tuple[str, int, float]) -> ProcessResult | None:
        info = self._pending[key]
        target_dir = self.done_dir if info["target"] == "done" else self.error_dir
        dest = self._unique_dest(target_dir, path.name)
        if not self._do_move(path, dest):
            return None
        if info["target"] == "error":
            self._write_sidecar(dest, info["message"])
        del self._pending[key]
        return ProcessResult(file=path.name, ok=info["ok"], jobs=info["jobs"], message=info["message"],
                             moved_to=str(dest))

    def _write_sidecar(self, dest: Path, message: str) -> None:
        log_path = dest.with_name(dest.name + ".log")
        text = f"{self._now().isoformat(timespec='seconds')} {message}\n"
        log_path.write_text(text, encoding="utf-8")

    def _unique_dest(self, target_dir: Path, name: str) -> Path:
        dest = target_dir / name
        if not dest.exists():
            return dest
        stem, suffix = Path(name).stem, Path(name).suffix
        ts = self._now().strftime("-%Y%m%d-%H%M%S")
        candidate = target_dir / f"{stem}{ts}{suffix}"
        n = 2
        while candidate.exists():
            candidate = target_dir / f"{stem}{ts}-{n}{suffix}"
            n += 1
        return candidate

    @staticmethod
    def _do_move(src: Path, dest: Path) -> bool:
        try:
            os.replace(src, dest)
            return True
        except OSError:
            return False

    # ---------- Dateiformate ----------

    def _build_jobs(self, path: Path, cfg: dict) -> tuple[list[_Job], dict[str, dict]]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self._jobs_json(path)
        if suffix == ".txt":
            return self._jobs_txt(path)
        if suffix == ".csv":
            return self._jobs_csv(path)
        if suffix == ".png":
            return self._jobs_png(path)
        raise _HotfolderError(_t("Dateityp '{suffix}' wird nicht unterstützt", suffix=suffix))  # pragma: no cover

    @staticmethod
    def _decode_txt(path: Path) -> str:
        raw = path.read_bytes()
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode("cp1252")

    def _jobs_json(self, path: Path) -> tuple[list[_Job], dict[str, dict]]:
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise _HotfolderError(_t("JSON: Datei nicht lesbar ({exc})", exc=exc)) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _HotfolderError(_t("JSON ungültig: {exc}", exc=exc)) from exc
        if isinstance(data, list):
            if len(data) > 100:
                raise _HotfolderError(_t("JSON-Liste: höchstens 100 Objekte erlaubt"))
            objects = data
        elif isinstance(data, dict):
            objects = [data]
        else:
            raise _HotfolderError(_t("JSON: Objekt oder Liste von Objekten erwartet"))
        jobs = [self._job_from_object(o) for o in objects]
        names = sorted({j.source["template"] for j in jobs if j.source.get("kind") == "template"})
        summaries = {s["name"]: s for s in self.facade.template_summaries(names)} if names else {}
        return jobs, summaries

    @staticmethod
    def _job_from_object(obj: object) -> _Job:
        if not isinstance(obj, dict):
            raise _HotfolderError(_t("JSON: jedes Element muss ein Objekt sein"))
        if "template" in obj:
            name = obj["template"]
            if not isinstance(name, str):
                raise _HotfolderError(_t("JSON: 'template' muss ein Text sein"))
            values = obj.get("values")
            vars_ = obj.get("vars")
            if values is not None and vars_ is not None:
                raise _HotfolderError(_t("values und vars nicht zugleich angeben"))
            values = values if values is not None else (vars_ if vars_ is not None else {})
            if not isinstance(values, dict):
                raise _HotfolderError(_t("JSON: 'values'/'vars' muss ein Objekt sein"))
            source = {"kind": "template", "template": name, "values": values}
            options = {"copies": obj.get("copies", 1), "confirmed": bool(obj.get("confirmed", False))}
        elif "text" in obj:
            text = obj["text"]
            if isinstance(text, list) and all(isinstance(line, str) for line in text):
                lines = list(text)
            elif isinstance(text, str):
                lines = text.split("\n")
            else:
                raise _HotfolderError(_t("JSON: 'text' muss ein Text oder eine Liste von Texten sein"))
            source = {"kind": "text", "lines": lines}
            options = {"copies": obj.get("copies", 1), "confirmed": bool(obj.get("confirmed", False))}
        elif "source" in obj:
            source = obj["source"]
            if not isinstance(source, dict):
                raise _HotfolderError(_t("JSON: 'source' muss ein Objekt sein"))
            options = obj.get("options") or {}
            if not isinstance(options, dict):
                raise _HotfolderError(_t("JSON: 'options' muss ein Objekt sein"))
            options = dict(options)
        else:
            raise _HotfolderError(_t("JSON-Objekt: weder 'template', 'text' noch 'source' angegeben"))
        return _Job(source=source, options=options)

    def _jobs_txt(self, path: Path) -> tuple[list[_Job], dict[str, dict]]:
        text = self._decode_txt(path)
        lines = text.splitlines()
        template_name = None
        start = 0
        if lines and lines[0].strip().startswith("#template="):
            template_name = lines[0].strip()[len("#template="):].strip()
            start = 1
        summaries: dict[str, dict] = {}
        field_id = None
        if template_name:
            summaries = {s["name"]: s for s in self.facade.template_summaries([template_name])}
            summary = summaries.get(template_name)
            if summary is None:
                raise _HotfolderError(_t("Vorlage '{template_name}' nicht gefunden", template_name=template_name))
            fields = summary.get("input_fields") or []
            if not fields:
                raise _HotfolderError(_t("Vorlage '{template_name}' hat keine Eingabefelder", template_name=template_name))
            field_id = fields[0]["id"]
        jobs: list[_Job] = []
        for raw_line in lines[start:]:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if template_name:
                source = {"kind": "template", "template": template_name, "values": {field_id: line}}
            else:
                source = {"kind": "text", "lines": [line]}
            jobs.append(_Job(source=source, options={"copies": 1, "confirmed": False}))
        return jobs, summaries

    def _jobs_csv(self, path: Path) -> tuple[list[_Job], dict[str, dict]]:
        text = self._decode_txt(path)
        first_line, _, rest = text.partition("\n")
        if not first_line.strip().startswith("#template="):
            raise _HotfolderError(_t("CSV braucht eine erste Zeile #template=<name>"))
        name = first_line.strip()[len("#template="):].strip()
        summaries = {s["name"]: s for s in self.facade.template_summaries([name])}
        summary = summaries.get(name)
        if summary is None:
            raise _HotfolderError(_t("Vorlage '{name}' nicht gefunden", name=name))
        fields = summary.get("input_fields") or []
        table = read_csv(rest, name=path.name)
        pairs = [(f["id"], f["label"]) for f in fields]
        mapping = auto_map(table.headers, pairs)
        rows = apply_mapping(table, mapping)
        jobs: list[_Job] = []
        for row in rows:
            if not any(v.strip() for v in row.values()):
                continue
            jobs.append(_Job(source={"kind": "template", "template": name, "values": row},
                             options={"copies": 1, "confirmed": False}))
        return jobs, summaries

    @staticmethod
    def _jobs_png(path: Path) -> tuple[list[_Job], dict[str, dict]]:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        source = {"kind": "image", "png": b64, "name": path.name, "fit": True}
        return [_Job(source=source, options={"copies": 1, "confirmed": False})], {}

    # ---------- Entprellung, Druck ----------

    @staticmethod
    def _merge_jobs(jobs: list[_Job]) -> list[_MergedJob]:
        order: list[_MergedJob] = []
        index: dict[str, int] = {}
        for job in jobs:
            extra = {k: v for k, v in job.options.items() if k != "copies"}
            dedup_key = json.dumps([job.source, extra], sort_keys=True)
            if dedup_key in index:
                existing = order[index[dedup_key]]
                existing.copies += job.copies
                existing.count += 1
            else:
                index[dedup_key] = len(order)
                order.append(_MergedJob(source=job.source, options=extra, copies=job.copies, count=1))
        return order

    def _print_all(self, merged: list[_MergedJob], summaries: dict[str, dict],
                   cfg: dict) -> tuple[bool, int, str]:
        total = len(merged)
        done = 0
        for job in merged:
            options = {**job.options, "copies": job.copies}
            outcome = self._print_one(job.source, options)
            status = outcome.get("status", "fehler")
            if status in ("ok", "wartet"):
                done += 1
                continue
            message = self._failure_message(job, outcome, status, summaries, cfg)
            if total > 1:
                message = _t("{message} ({done} von {total} gedruckt)", message=message, done=done, total=total)
            return False, done, message
        return True, done, "gedruckt"

    def _print_one(self, source: dict, options: dict) -> dict:
        outcome = self._call_print(source, options)
        if outcome.get("status") == "abgelehnt" and list(outcome.get("reasons") or []) == [_t(DOUBLE_PRESS_REASON)]:
            self._sleep(self._retry_delay_s)
            outcome = self._call_print(source, options)
        return outcome

    def _call_print(self, source: dict, options: dict) -> dict:
        try:
            return self.facade.print(source, options, origin="hotfolder")
        except Exception as exc:  # noqa: BLE001: Ausnahmen der Fassade zählen als Fehler
            return {"status": "fehler", "reasons": [], "error": {"message": str(exc)}}

    def _failure_message(self, job: _MergedJob, outcome: dict, status: str, summaries: dict[str, dict],
                         cfg: dict) -> str:
        reasons = list(outcome.get("reasons") or [])
        reason_text = "; ".join(reasons)
        if status == "bestätigung_nötig":
            base = (_t("Rückfrage nötig ({reason_text}). Passt das Band trotzdem, in einer JSON-Datei \"confirmed\": true setzen.", reason_text=reason_text))
        elif status == "abgelehnt":
            base = _t("Abgelehnt: {reason_text} (Hotfolder: {limits_text})", reason_text=reason_text, limits_text=sourcelimits.limits_text(cfg, 'hotfolder'))
        elif status == "unbekannt":
            # Zeitüberschreitung beim Warten auf den Druckdienst (HttpPrinter): der Auftrag kann
            # gedruckt sein, darum keine Meldung "Druck fehlgeschlagen".
            base = (outcome.get("error") or {}).get("message") or _t("Status unbekannt, bitte Verlauf prüfen")
        else:
            err = outcome.get("error") or {}
            text = reason_text or err.get("message") or status
            base = _t("Druck fehlgeschlagen ({status}): {text}", status=status, text=text)
        if job.source.get("kind") == "template":
            masked = self._masked_values(job.source.get("template"), job.source.get("values") or {},
                                         summaries)
            base = _t("{base} Werte: {masked}", base=base, masked=masked)
        return base

    @staticmethod
    def _masked_values(template_name: str | None, values: dict, summaries: dict[str, dict]) -> dict:
        summary = summaries.get(template_name) if template_name else None
        if summary is None:
            return {k: REDACTED for k in values}
        secret_ids = {f["id"] for f in summary.get("input_fields", []) if f.get("secret")}
        masked_keys = secret_ids | {f"{fid}_model" for fid in secret_ids}
        return {k: (REDACTED if k in masked_keys else v) for k, v in values.items()}


def create(facade, cfg: dict) -> Hotfolder | None:
    """Addon aus der Konfiguration (`hotfolder.*`) oder `None`, wenn `hotfolder.enabled` falsch ist."""
    if not config.setting(cfg, "hotfolder.enabled"):
        return None
    raw_dir = config.setting(cfg, "hotfolder.dir")
    root = Path(raw_dir) if raw_dir else (paths.app_dir() / "hotfolder")
    return Hotfolder(facade, root, poll_s=config.setting(cfg, "hotfolder.poll_s"),
                     settle_s=config.setting(cfg, "hotfolder.settle_s"),
                     max_bytes=config.setting(cfg, "hotfolder.max_bytes"))
