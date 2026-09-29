"""Plugin-Befehl 'p12 raw': Rohbefehl senden und Antwort dekodieren (mit Schutzliste).

Rohbefehle laufen bewusst nicht durch die Druck-Pipeline (kein Verlauf), wie 'p12 probe'/'verify'.
Jeder Befehl wird vor dem Öffnen der Sitzung gegen die Schutzliste geprüft: gesperrte Befehle werden
nie gesendet, Rückfrage-Befehle nur mit --unsafe und ausdrücklicher Bestätigung ('JA').
"""

import argparse
import json

from tapesmith.protocol.rawcmd import classify_raw, parse_hex
from tapesmith.protocol.status import decode
from tapesmith.i18n import N_, _t

COMMAND = "raw"
HELP = N_("Rohbefehl senden und Antwort dekodieren (Entwicklerwerkzeug, mit Schutzliste)")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("commands", nargs="*", help=_t("Hex-Rohbefehle, z. B. 1F1108"))
    parser.add_argument("--listen", type=float, metavar=_t("SEK"),
                        help=_t("danach SEK Sekunden auf Spontanmeldungen lauschen"))
    parser.add_argument("--timeout", type=float, metavar=_t("SEK"), help=_t("Antwort-Zeitlimit (Default aus Profil)"))
    parser.add_argument("--unsafe", action="store_true", help=_t("Rückfrage-Befehle nach Bestätigung senden"))
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))
    parser.add_argument("-i", "--interactive", action="store_true", help=_t("interaktive Konsole"))


def _check(ctx, data: bytes, unsafe: bool) -> str:
    """Prüft `data` gegen die Schutzliste und gibt bei erlaubtem/bestätigtem Senden den Pegel
    zurück; wirft sonst ValueError (gesperrt, oder rückfrage ohne --unsafe/Bestätigung)."""
    verdict = classify_raw(data)
    if verdict.level == "gesperrt":
        raise ValueError(_t("{hex}: gesperrt ({reason})", hex=data.hex(), reason=verdict.reason))
    if verdict.level == "rückfrage":
        if not unsafe:
            raise ValueError(_t("{hex}: Rückfrage nötig ({reason}), nur mit --unsafe senden", hex=data.hex(), reason=verdict.reason))
        if not ctx.stdin_is_tty():
            raise ValueError(_t("{hex}: Rückfrage nötig ({reason}), nur interaktiv mit --unsafe", hex=data.hex(), reason=verdict.reason))
        ctx.err(_t("Rückfrage: {hex}: {reason}", hex=data.hex(), reason=verdict.reason))
        print(_t("Wirklich senden? Eingabe 'JA': "), end="", file=ctx.stderr, flush=True)
        answer = ctx.stdin.readline().strip()
        if answer not in ("JA", "YES"):
            raise ValueError(_t("{hex}: nicht bestätigt (Eingabe 'JA' erwartet)", hex=data.hex()))
    return verdict.level


def _send_one(ctx, session, profile, data: bytes, level: str, timeout: float | None) -> dict:
    raw = session.exchange(data, timeout or profile.response_timeout_s)
    texts = [m.text for m in decode(raw, profile.status_map())]
    ctx.out(f"{data.hex()}: {raw.hex() if raw else '-'}  {', '.join(texts) if texts else 'keine Antwort'}")
    return {"command": data.hex(), "level": level, "response": raw.hex() if raw else None, "decoded": texts}


def _listen(ctx, session, seconds: float, profile) -> None:
    data = session.listen(seconds)
    for m in decode(data, profile.status_map()):
        ctx.out(f"(spontan) {m.text}")


def _run_interactive(args: argparse.Namespace, ctx, profile) -> int:
    with ctx.open_session(profile) as s:
        while True:
            print("p12> ", end="", file=ctx.stderr, flush=True)
            raw_line = ctx.stdin.readline()
            if raw_line == "":
                break
            line = raw_line.strip()
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            parts = line.split()
            if parts[0] == "listen":
                seconds = float(parts[1]) if len(parts) > 1 else 5.0
                _listen(ctx, s, seconds, profile)
                continue
            try:
                data = parse_hex(line)
                level = _check(ctx, data, args.unsafe)
            except ValueError as exc:
                ctx.err(str(exc))
                continue
            _send_one(ctx, s, profile, data, level, args.timeout)
    return 0


def run(args: argparse.Namespace, ctx) -> int:
    profile = ctx.load_profile()

    if args.interactive:
        return _run_interactive(args, ctx, profile)

    parsed: list[tuple[bytes, str]] = []
    for text in args.commands:
        data = parse_hex(text)
        level = _check(ctx, data, args.unsafe)
        parsed.append((data, level))

    if not parsed and not args.listen:
        raise ValueError(_t("kein Befehl angegeben (oder --listen)"))

    results = []
    with ctx.open_session(profile) as s:
        for data, level in parsed:
            results.append(_send_one(ctx, s, profile, data, level, args.timeout))
        if args.listen:
            _listen(ctx, s, args.listen, profile)

    if args.json:
        ctx.out(json.dumps(results, ensure_ascii=False))
    return 0
