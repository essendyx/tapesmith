"""`p12 hotfolder`: Status des überwachten Ordners und ein Durchlauf ohne den Druckdienst-Prozess
selbst zu sein.

`run-once` druckt über den laufenden Druckdienst p12d: eine Fassade gibt es in der CLI nicht,
deshalb nutzt es den kleinen HTTP-Adapter `HttpPrinter` mit den Fassaden-Methoden, die
`tapesmith.automation.hotfolder.Hotfolder` benutzt (`print`, `template_summaries`, `config`).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import httpx

from tapesmith import config, paths
from tapesmith.automation.hotfolder import Hotfolder
from tapesmith.cli_cmds.base import CliContext
from tapesmith.i18n import N_, LANGUAGES, _t, translate

COMMAND = "hotfolder"
HELP = N_("Hotfolder-Ordner prüfen und einmal verarbeiten (p12 hotfolder status | run-once)")

# Ein Druck über p12d wartet, bis der Drucker fertig ist; allein das Öffnen des COM-Ports dauert am
# echten P12 10 bis 20 s. httpx' Standard (5 s) würde fast jeden Druck als Fehler melden, obwohl er
# gedruckt wurde. Verbindungsaufbau bleibt kurz, damit ein nicht laufender Dienst schnell auffällt.
HTTP_TIMEOUT = httpx.Timeout(120.0, connect=5.0)

STATUS_UNKNOWN = "unbekannt"
# Anfang von UNKNOWN_MESSAGE und `automation.hotfolder` (Status unklar), in jeder Sprache gleich.
UNKNOWN_PREFIX = N_("Status unbekannt")
UNKNOWN_MESSAGE = (N_("Status unbekannt, bitte Verlauf prüfen (keine Antwort des Druckdiensts innerhalb von {s:.0f} s). Die Datei nicht erneut ablegen, bevor der Verlauf zeigt, dass nicht gedruckt wurde."))


class HttpPrinter:
    """Adapter über die REST-API für `p12 hotfolder run-once` (alle Fassaden-Methoden, die
    `Hotfolder` benutzt). Sitzung (Port, Token) über `webui.browser.connect_session`; Quelle im
    Verlauf `hotfolder` (Kopfzeile `X-P12-Source: hotfolder`, dieselbe Kopiengrenze wie das
    Addon `tapesmith.automation.hotfolder`)."""

    def __init__(self, *, session_loader=None, client_factory=httpx.Client,
                 config_loader=config.load_config):
        self._session_loader = session_loader if session_loader is not None else self._default_session
        self._client_factory = client_factory
        self._config_loader = config_loader
        self._client_obj = None

    def _default_session(self) -> dict:
        from tapesmith.webui.browser import connect_session

        return connect_session(config.load_config())

    def _client(self):
        if self._client_obj is None:
            session = self._session_loader()
            base_url = f"http://127.0.0.1:{session['port']}"
            headers = {"X-P12-Token": str(session["token"]), "X-P12-Source": "hotfolder"}
            self._client_obj = self._client_factory(base_url=base_url, headers=headers,
                                                    timeout=HTTP_TIMEOUT)
        return self._client_obj

    def close(self) -> None:
        if self._client_obj is not None:
            self._client_obj.close()
            self._client_obj = None

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        response = self._client().request(method, path, json=json_body)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            message = _t("Anfrage fehlgeschlagen")
            if isinstance(data, dict):
                message = (data.get("error") or {}).get("message", message)
            raise RuntimeError(message)
        if not isinstance(data, dict):
            raise RuntimeError(_t("Anfrage fehlgeschlagen: keine gültige Antwort"))
        return data

    def print(self, source: dict, options: dict | None = None, *, origin: str) -> dict:
        # origin ist für die HTTP-Route immer "api" (Kopfzeile X-P12-Source); der Parameter bleibt
        # aus Symmetrie mit den anderen Fassaden-Methoden erhalten.
        del origin
        try:
            return self._request("POST", "/api/v1/labels/print",
                                 json_body={"source": source, "options": options})
        except httpx.TimeoutException:
            # Der Auftrag kann längst gedruckt sein: kein Druckfehler, sondern ein unklarer Stand.
            message = _t(UNKNOWN_MESSAGE).format(s=HTTP_TIMEOUT.read or 0)
            return {"status": STATUS_UNKNOWN, "reasons": [], "error": {"message": message}}

    def template_summaries(self, names: Sequence[str] | None = None) -> list[dict]:
        data = self._request("GET", "/api/v1/templates")
        by_name = {t["name"]: t for t in data.get("templates", [])}
        if names is None:
            return list(by_name.values())
        return [by_name[n] for n in names if n in by_name]

    def config(self) -> dict:
        return self._config_loader()


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="hotfolder_cmd", required=True)
    sub.add_parser("status", help=_t("Ordner, an/aus, Anzahl Dateien in Eingang, done, error"))
    run_once = sub.add_parser("run-once", help=_t("ein Durchlauf, Dateien gelten sofort als fertig"))
    run_once.add_argument("--dir", type=Path, metavar=_t("PFAD"), help=_t("Ordner statt hotfolder.dir"))


def _default_root(cfg: dict) -> Path:
    raw = config.setting(cfg, "hotfolder.dir")
    return Path(raw) if raw else (paths.app_dir() / "hotfolder")


def _count_files(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file())


def _run_status(ctx: CliContext, cfg: dict) -> int:
    root = _default_root(cfg)
    state = "an" if config.setting(cfg, "hotfolder.enabled") else "aus"
    eingang = _count_files(root)
    done = _count_files(root / "done")
    error = _count_files(root / "error")
    ctx.out(_t("Hotfolder: {root} ({state}), Eingang {eingang}, done {done}, error {error}", root=root, state=state, eingang=eingang, done=done, error=error))
    return 0


def _run_once(ctx: CliContext, cfg: dict, folder: Path | None) -> int:
    root = folder if folder is not None else _default_root(cfg)
    printer = HttpPrinter()
    try:
        hotfolder = Hotfolder(printer, root, settle_s=0.0)
        results = hotfolder.scan_once()
    except Exception as exc:  # noqa: BLE001
        ctx.err(_t("Fehler: {exc}", exc=exc))
        return 1
    finally:
        close = getattr(printer, "close", None)
        if callable(close):
            close()
    if not results:
        ctx.out(_t("Keine Dateien im Eingang."))
        return 0
    all_ok = True
    for result in results:
        if result.ok:
            state = "ok"
        elif any(result.message.startswith(translate(UNKNOWN_PREFIX, lang)) for lang in LANGUAGES):
            state = "unklar"
        else:
            state = _t("Fehler")
        line = _t("{file}: {state} ({jobs} Aufträge)", file=result.file, state=state, jobs=result.jobs)
        if not result.ok:
            line += f": {result.message}"
            all_ok = False
        ctx.out(line)
    return 0 if all_ok else 1


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()
    if args.hotfolder_cmd == "status":
        return _run_status(ctx, cfg)
    if args.hotfolder_cmd == "run-once":
        return _run_once(ctx, cfg, args.dir)
    return 1  # pragma: no cover: argparse erzwingt bekannte Unterbefehle
