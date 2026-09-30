"""Web-Oberfläche im Standardbrowser öffnen (`tapesmith app`, Tray „Öffnen“, Startmenü, Kontextmenü, URI).

Es gibt kein eigenes Fenster: die Oberfläche läuft ausschließlich im Standardbrowser des Users,
nativ bleibt nur das Tray-Symbol mit seinem Kontextmenü.
`open_app` startet den Druckdienst bei Bedarf (`connect_session`), baut die Adresse mit
Sitzungstoken im Fragment (`app_url`, `#t=...`; die Oberfläche übernimmt es beim Start in
`initToken` und entfernt es sofort aus der Adresszeile) und übergibt sie dem Standardbrowser.

Fehler werden nie still verschluckt: `open_app` wirft sie weiter (die Tray-App zeigt eine
Windows-Benachrichtigung), `main` schreibt sie nach stderr und in `<App-Verzeichnis>/logs/app.log`
und endet mit Exit-Code 1. Ein Meldungsfenster gibt es nicht.

Testmodus: Ist die Umgebungsvariable `TAPESMITH_BROWSER_LOG` auf eine Datei gesetzt, startet
`open_app` weder Druckdienst noch Browser, sondern hängt nur die Route (ohne Token) als Zeile an
diese Datei an. So lässt sich ein echter Tray-Build prüfen, ohne dass ein Browser aufgeht.

Dieses Modul importiert weder PySide6 noch eine Fensterbibliothek.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from typing import Any

from tapesmith import config, launch, paths
from tapesmith.config import setting
from tapesmith.ipc.launcher import ensure_daemon
from tapesmith.ipc.pipe import home_key
from tapesmith.webapi.session import read_session
from tapesmith.i18n import _t

DEFAULT_ROUTE = "/schnelldruck"

_POLL_S = 0.2
# Lief der Dienst schon (nicht eben gestartet), steht seine Sitzung längst: so lange warten wir höchstens.
_RUNNING_GRACE_S = 2.0
_HEALTH_TIMEOUT_S = 1.0
_MAX_ROUTE_LEN = 2048
QUICK_ROUTE = "/schnelldruck"
# Höchstens so viele Zeichen aus der Zwischenablage übernehmen (Schnelldruck ist für kurze Texte).
CLIP_TEXT_MAX = 500
BROWSER_LOG_ENV = "TAPESMITH_BROWSER_LOG"
APP_LOG_NAME = "app.log"


# ---------- Route ----------

def build_route(*, route: str | None = None, uri: str | None = None,
                open_action: str | None = None, path: str | None = None) -> str:
    """Baut den Startpfad der Oberfläche.

    Reihenfolge: `uri` gewinnt vor `open`/`path`, sonst `route` oder der Standard `/schnelldruck`."""
    if uri is not None:
        return "/aktion?" + urllib.parse.urlencode({"uri": uri})
    if open_action is not None and path is not None:
        return "/aktion?" + urllib.parse.urlencode({"open": open_action, "path": path})
    return route or DEFAULT_ROUTE


def quick_route(text: str | None = None, *, limit: int = CLIP_TEXT_MAX) -> tuple[str, bool]:
    """Schnelldruck-Route, optional mit vorbelegtem Text (`/schnelldruck?text=...`, URL-kodiert).

    Zeilenumbrüche werden vereinheitlicht (CRLF/CR zu LF), Ränder abgeschnitten, der Text auf
    `limit` Zeichen und die Route auf die erlaubte Länge (`safe_route`) begrenzt. Rückgabe:
    (Route, gekürzt?)."""
    if text is None:
        return QUICK_ROUTE, False
    clean = text.replace("\r\n", "\n").replace("\r", "\n")
    clean = "".join(ch for ch in clean if ch in "\n\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F))
    clean = clean.strip()
    if not clean:
        return QUICK_ROUTE, False
    truncated = False
    if len(clean) > limit:
        clean, truncated = clean[:limit], True
    while True:
        route = QUICK_ROUTE + "?" + urllib.parse.urlencode({"text": clean}, quote_via=urllib.parse.quote)
        if len(route) <= _MAX_ROUTE_LEN:
            return route, truncated
        clean, truncated = clean[:max(0, len(clean) - 16)], True


def safe_route(route: Any) -> str | None:
    """Route nur als reiner Pfad auf 127.0.0.1: beginnt mit `/`, kein `//` bzw. Backslash (fremder
    Host), kein `#` (das Token hängt `app_url` an), keine Steuerzeichen. Sonst `None`."""
    if not isinstance(route, str) or not route.startswith("/") or len(route) > _MAX_ROUTE_LEN:
        return None
    if route.startswith("//") or "\\" in route or "#" in route:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in route):
        return None
    return route


def app_url(port: int, token: str, route: str) -> str:
    return f"http://127.0.0.1:{port}{route}#t={token}"


# ---------- Verbindung ----------

def check_health(port: int, *, timeout_s: float = _HEALTH_TIMEOUT_S,
                 opener: Callable[..., Any] = urllib.request.urlopen) -> dict | None:
    """`GET /health` (ohne Token). `None` bei jedem Fehler (Port noch nicht offen, falsche
    Antwort, Zeitüberschreitung)."""
    try:
        with opener(f"http://127.0.0.1:{port}/health", timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001: jeder Fehler heißt, noch nicht bereit
        return None
    return data if isinstance(data, dict) else None


def connect_session(cfg: dict, *, ensure: Callable[..., Any] = ensure_daemon,
                    read: Callable[[], dict | None] = read_session,
                    health: Callable[..., dict | None] = check_health,
                    expected_home: str | None = None, timeout_s: float | None = None,
                    sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic,
                    spawn: Callable[..., int] = launch.spawn_detached,
                    grace_s: float = _RUNNING_GRACE_S) -> dict:
    """Startet den Druckdienst bei Bedarf und wartet, bis die Sitzungsdatei (`session.json`)
    zu **diesem** App-Verzeichnis passt (`home_key`): so erreicht ein Aufruf mit fremdem
    `TAPESMITH_HOME` (z. B. ein Testlauf) nie die Sitzung des Benutzers, selbst über denselben Port.

    `RuntimeError` mit deutschem Klartext, und zwar sofort statt nach dem Zeitablauf, wenn
    `daemon.enabled` aus ist oder ein schon laufender Dienst keine Sitzung hat (Web-Oberfläche
    dort gescheitert). Nur ein eben gestarteter Dienst bekommt die volle
    Wartezeit; antwortet er nicht rechtzeitig, nennt die Meldung den Log-Pfad."""
    if not setting(cfg, "daemon.enabled"):
        raise RuntimeError(_t("Die Oberfläche braucht den Druckdienst (daemon.enabled = true)"))
    expected_home = expected_home if expected_home is not None else home_key()
    limit = float(timeout_s) if timeout_s is not None else float(setting(cfg, "daemon.start_timeout_s")) + 5.0

    started: list[bool] = []

    def spawn_tracked(argv):
        started.append(True)
        return spawn(argv)

    client = ensure(cfg, client="gui", spawn=spawn_tracked)
    if not started:
        limit = min(limit, float(grace_s))
    try:
        client.close()
    except Exception:  # noqa: BLE001: nur die Verbindung zum Warten, kein Handling nötig
        pass

    deadline = clock() + limit
    while True:
        session = read()
        if session is not None:
            info = health(int(session.get("port", 0)))
            if info is not None and info.get("home_key") == expected_home:
                return session
        if clock() >= deadline:
            break
        sleep(_POLL_S)
    log_path = paths.log_dir() / "daemon.log"
    if not started and session is None:
        raise RuntimeError(_t("Der Druckdienst läuft ohne Web-Oberfläche (keine Sitzung gefunden). Dienst neu starten mit 'tapesmith daemon restart' (Log: {log_path})", log_path=log_path))
    raise RuntimeError(_t("Web-Oberfläche des Druckdienstes antwortet nicht (Log: {log_path})", log_path=log_path))


# ---------- Browser ----------

def default_opener(url: str) -> None:
    """Übergibt `url` dem Standardbrowser (unter Windows über die Shell, wie ein Doppelklick auf
    einen Link). `RuntimeError`, wenn kein Browser startet."""
    try:
        ok = webbrowser.open(url)
    except webbrowser.Error as exc:
        raise RuntimeError(_t("Standardbrowser lässt sich nicht öffnen ({exc})", exc=exc)) from exc
    if not ok:
        raise RuntimeError(_t("Standardbrowser lässt sich nicht öffnen (kein Browser registriert?)"))


def open_app(route: str | None = None, *, config_loader: Callable[[], dict] | None = None,
             connector: Callable[..., dict] | None = None,
             opener: Callable[[str], Any] | None = None) -> str:
    """Zentrale Stelle: Druckdienst bei Bedarf starten und die Oberfläche auf `route` im
    Standardbrowser öffnen. Gibt die geöffnete Adresse zurück (mit Token, nie loggen).

    `ValueError` bei ungültiger Route, `RuntimeError` (bzw. die Ausnahme des Dienststarts), wenn
    der Druckdienst oder der Browser nicht startet. Ohne Angabe gelten `config.load_config`,
    `connect_session` und `default_opener` (erst beim Aufruf nachgeschlagen).

    Testmodus `TAPESMITH_BROWSER_LOG` (nur ohne eigenen `connector`/`opener`): Route an die Datei
    anhängen und zurückgeben, weder Druckdienst noch Browser starten."""
    log_file = os.environ.get(BROWSER_LOG_ENV) if connector is None and opener is None else None
    config_loader = config_loader or config.load_config
    connector = connector or connect_session
    opener = opener or default_opener
    target = safe_route(route if route is not None else DEFAULT_ROUTE)
    if target is None:
        raise ValueError(_t("Ungültige Startseite {route!r}: erwartet ein Pfad wie /verlauf", route=route))
    if log_file:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(target + "\n")
        return target
    session = connector(config_loader())
    url = app_url(int(session["port"]), str(session["token"]), target)
    opener(url)
    return url


def log_error(text: str) -> None:
    """Fehler in `<App-Verzeichnis>/logs/app.log` anhängen (Starts ohne Konsole). Scheitert das
    Schreiben, bleibt es bei stderr und dem Exit-Code."""
    from datetime import datetime

    try:
        log = paths.log_dir() / APP_LOG_NAME
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(_t("{now:%Y-%m-%d %H:%M:%S} FEHLER {text}\n", now=datetime.now(), text=text))
    except OSError:
        pass


def build_parser(prog: str = "tapesmith app") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=_t("Web-Oberfläche im Standardbrowser öffnen"))
    add_arguments(parser)
    return parser


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--route", default=None, metavar=_t("PFAD"), help=_t("Startseite, z. B. /verlauf"))
    parser.add_argument("--uri", default=None, help=_t("tapesmith://-URI vorausgefüllt öffnen"))
    parser.add_argument("--open", dest="open_action", default=None, metavar=_t("AKTION"))
    parser.add_argument("--path", default=None)
    # Früher: Browser statt App-Fenster. Heute immer Browser, bleibt für alte Skripte gültig.
    parser.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)


def main(argv: list[str] | None = None, *, opener: Callable[[str], Any] | None = None,
         log: Callable[[str], None] | None = None) -> int:
    """`tapesmith app` bzw. `pythonw -m tapesmith.webui.browser ...`: öffnet die Oberfläche im Browser und beendet sich.
    Exit 0 ok, 1 Fehler (Meldung auf stderr und ins Log `logs/app.log`, nie als Fenster)."""
    args = build_parser().parse_args(argv)
    route = build_route(route=args.route, uri=args.uri, open_action=args.open_action, path=args.path)
    try:
        (opener or open_app)(route)
    except Exception as exc:  # noqa: BLE001: jeder Fehler wird gemeldet, nie verschluckt
        text = _t("Tapesmith lässt sich nicht öffnen: {exc}", exc=exc)
        if sys.stderr is not None:
            print(text, file=sys.stderr)
        (log or log_error)(text)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
