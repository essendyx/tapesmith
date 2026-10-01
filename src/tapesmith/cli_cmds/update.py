"""`tapesmith update`: Update-Status, Prüfen, Installieren und Rückstellung (Deutsch).

Exit-Codes: 0 ok, 1 Fehler, 5 Update-Quelle nicht erreichbar. Installation und Rückstellung starten
`pythonw -m tapesmith.update.apply …` losgelöst; das geht nur in der installierten App."""

from __future__ import annotations

import argparse
import json

from tapesmith.errors import EXIT_ERROR, EXIT_OK, EXIT_UNREACHABLE
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import N_, _t

COMMAND = "update"
HELP = N_("Updates prüfen und installieren (installierte App)")

YES_ANSWERS = ("j", "ja", "y", "yes")

def _default_service(load_config):
    from tapesmith.update.service import UpdateService

    return UpdateService(load_config)


SERVICE_FACTORY = _default_service

STATE_TEXT = {"idle": "bereit", "checking": N_("prüft"), "downloading": N_("lädt"), "ready": N_("Update bereit"),
              "installing": "installiert", "failed": N_("Fehler")}


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="update_cmd", required=True)
    st = sub.add_parser("status", help=_t("Update-Zustand anzeigen"))
    st.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))
    sub.add_parser("check", help=_t("jetzt nach Updates suchen"))
    ls = sub.add_parser("list", help=_t("alle installierbaren Versionen anzeigen"))
    ls.add_argument("--prerelease", action="store_true", help=_t("auch Vorabversionen"))
    ls.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))
    ins = sub.add_parser("install", help=_t("verfügbares Update bzw. eine bestimmte Version installieren (App startet neu)"))
    ins.add_argument("version", nargs="?", default=None,
                     help=_t("bestimmte Version, auch eine ältere (vorher wird gesichert)"))
    ins.add_argument("--yes", action="store_true", help=_t("ohne Rückfrage"))
    rb = sub.add_parser("rollback", help=_t("auf die vorige Version zurückstellen"))
    rb.add_argument("--yes", action="store_true", help=_t("ohne Rückfrage"))


def _exit_for(exc: UpdateError) -> int:
    return EXIT_UNREACHABLE if exc.code == "update.source_unreachable" else EXIT_ERROR


def _report(ctx, exc: UpdateError) -> int:
    ctx.err(_t("Fehler ({code}): {exc}", code=exc.code, exc=exc))
    if exc.hint:
        ctx.err(_t("Hinweis: {hint}", hint=exc.hint))
    return _exit_for(exc)


def _confirm(ctx, question: str) -> bool:
    ctx.stdout.write(f"{question} {_t('[j/N]')} ")
    ctx.stdout.flush()
    answer = ctx.stdin.readline().strip().lower()
    return answer in YES_ANSWERS


def _print_status(ctx, status) -> None:
    ctx.out(_t("Version: {current}", current=status.current) + (_t(" (installiert)") if status.installed else _t(" (Entwicklung bzw. nicht installiert)")))
    if status.installed:
        ctx.out(_t("Ordner: {root}", root=status.root))
        if status.previous:
            ctx.out(_t("Vorige Version: {previous}", previous=status.previous))
    ctx.out(_t("Quelle: {source} (Kanal {channel})", source=status.source, channel=status.channel))
    ctx.out(_t("Suche: {value}, automatisch installieren: {value2}", value=_t('an') if status.enabled else _t('aus'), value2=_t('an') if status.auto_install else _t('aus')))
    ctx.out(_t("Letzte Prüfung: {value}", value=status.last_check or _t('noch nie')))
    if status.available:
        ctx.out(_t("Verfügbar: {version}", version=status.available['version']))
    ctx.out(_t("Zustand: {t}", t=_t(STATE_TEXT.get(status.state, status.state))))
    if status.error:
        ctx.out(_t("Fehler: {get} ({get2})", get=status.error.get('message'), get2=status.error.get('code')))


def run(args: argparse.Namespace, ctx) -> int:
    svc = SERVICE_FACTORY(ctx.load_config)
    try:
        if args.update_cmd == "status":
            status = svc.status()
            if args.json:
                ctx.out(json.dumps(status.to_json(), ensure_ascii=False, indent=2))
            else:
                _print_status(ctx, status)
            return EXIT_OK
        if args.update_cmd == "check":
            status = svc.check()
            if status.available:
                ctx.out(_t("Update verfügbar: {version} (aktuell {current})", version=status.available['version'], current=status.current))
                if status.available.get("notes"):
                    ctx.out(status.available["notes"])
            else:
                ctx.out(_t("Kein Update verfügbar (aktuell {current})", current=status.current))
            return EXIT_OK
        if args.update_cmd == "list":
            data = svc.versions(include_prerelease=args.prerelease, refresh=True)
            if args.json:
                ctx.out(json.dumps(data, ensure_ascii=False, indent=2))
                return EXIT_OK
            for entry in data["versions"]:
                marks = []
                if entry["current"]:
                    marks.append(_t("aktuell installiert"))
                elif entry["installed"]:
                    marks.append(_t("lokal vorhanden"))
                if entry["newer"]:
                    marks.append(_t("neu"))
                if entry["prerelease"]:
                    marks.append(_t("Vorabversion"))
                if entry["failed"]:
                    marks.append(_t("gescheitert"))
                date = (entry.get("published") or "")[:10]
                ctx.out(f"{entry['version']:<12} {date:<10} {', '.join(marks)}".rstrip())
            if data["error"]:
                ctx.err(_t("Quelle nicht erreichbar: {message}", message=data["error"]["message"]))
                return EXIT_UNREACHABLE
            return EXIT_OK
        if args.update_cmd == "install" and args.version:
            if not svc.installed():
                from tapesmith.update.service import NOT_INSTALLED_MESSAGE

                raise UpdateError("update.not_installed", _t(NOT_INSTALLED_MESSAGE))
            version = args.version
            if svc.is_downgrade(version):
                question = _t("Zurück auf {version}? Vorher wird eine Sicherung angelegt. Daten, die neuere Versionen geschrieben haben, versteht eine ältere eventuell nicht. Tapesmith startet dabei neu.", version=version)
            else:
                question = _t("Version {version} installieren? Tapesmith startet dabei neu.", version=version)
            if not args.yes and not _confirm(ctx, question):
                ctx.out(_t("Abgebrochen"))
                return EXIT_ERROR
            ctx.out(_t("Lade und prüfe {version} …", version=version))
            svc.prepare(version, explicit=True)
            svc.start_install(version, explicit=True)
            ctx.out(_t("Umstellung auf {version} gestartet: Tapesmith beendet sich kurz und startet neu", version=version))
            return EXIT_OK
        if args.update_cmd == "install":
            if not svc.installed():
                from tapesmith.update.service import NOT_INSTALLED_MESSAGE

                raise UpdateError("update.not_installed", _t(NOT_INSTALLED_MESSAGE))
            status = svc.check()
            if not status.available:
                ctx.out(_t("Kein Update verfügbar (aktuell {current})", current=status.current))
                return EXIT_OK
            version = str(status.available["version"])
            if not args.yes and not _confirm(ctx, _t("Update auf {version} installieren? Tapesmith startet dabei neu.", version=version)):
                ctx.out(_t("Abgebrochen"))
                return EXIT_ERROR
            ctx.out(_t("Lade und prüfe {version} …", version=version))
            svc.prepare(version)
            svc.start_install(version)
            ctx.out(_t("Update auf {version} gestartet: Tapesmith beendet sich kurz und startet neu", version=version))
            return EXIT_OK
        if args.update_cmd == "rollback":
            status = svc.status()
            if not status.installed:
                from tapesmith.update.service import NOT_INSTALLED_MESSAGE

                raise UpdateError("update.not_installed", _t(NOT_INSTALLED_MESSAGE))
            target = status.previous or _t("vorige Version")
            if not args.yes and not _confirm(ctx, _t("Auf {target} zurückstellen? Tapesmith startet dabei neu.", target=target)):
                ctx.out(_t("Abgebrochen"))
                return EXIT_ERROR
            svc.start_rollback()
            ctx.out(_t("Rückstellung auf {target} gestartet", target=target))
            return EXIT_OK
    except UpdateError as exc:
        return _report(ctx, exc)
    raise ValueError(_t("Unbekannter Unterbefehl '{update_cmd}'", update_cmd=args.update_cmd))
