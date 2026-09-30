"""Selbsttest für neue Versionsumgebungen (Updater, Installer) und die Entwicklung, ohne Qt.

Aufruf: `python -m tapesmith.selftest [--selftest-out DATEI]` bzw. `p12 gui --selftest`. Geprüft werden
Paketdaten, Schriften, Renderer, Vorlagen, ein Dokument mit allen Objektarten, Codes, Barcode-Decoder
(zxing-cpp optional: fehlt er, meldet der Schritt nur `WARNUNG`, der Selbsttest bleibt ok), Icons,
Band-Invertierung, Lint aller mitgelieferten Vorlagen, IPC mit Speicher-Kanälen, der
Druckdienst (Datei-Transport, eigene Pipe), Warteschlange und Zwischenablage-Erkennung. Dazu die
Web-Oberfläche: die FastAPI-App beantwortet `/health`, eine Vorschau und die Einstellungen
(direkt über ASGI, ohne Socket), die gebaute Oberfläche liegt vollständig im Paket, uvicorn ist importierbar, der Browserstart baut
die richtige Adresse (ohne echten Browser) und der Build enthält kein Fenster: weder das alte
App-Fenster (pywebview) noch Schnelldruck-Popup, Zwischenablage-Toast oder Tray-Dialog.
Außerdem Übersetzungskataloge de/en mit gleichen Schlüsseln, Update-Signatur (Ed25519 im Speicher,
`trusted_keys.json` lesbar) und Installationslayout (Junction in einem Temp-Ordner anlegen,
umstellen, entfernen).

Der Selbsttest öffnet keinen Port und kein Fenster, liest keine Registry, schreibt keine
Nutzerdaten (eigenes temporäres App-Verzeichnis) und druckt nie. Die Tray-App (nur Symbol und
Kontextmenü, alles andere als Browser-Tab) braucht Qt und hat eigene Tests.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from PIL import Image

from tapesmith import config as config_mod
from tapesmith import i18n, paths, webui
from tapesmith.clipboard import classify_clipboard
from tapesmith.daemon.queue import JobQueue
from tapesmith.daemon.server import DaemonServer
from tapesmith.daemon.service import PrintService
from tapesmith.device.profile import load_profile
from tapesmith.document.model import (
    Code128Object,
    DataMatrixObject,
    IconObject,
    ImageObject,
    LabelDocument,
    LineObject,
    QrObject,
    RectObject,
    TextObject,
    prepare_embedded_image,
)
from tapesmith.document.render import render_document, render_spec
from tapesmith.history import HistoryStore
from tapesmith.ipc.client import DaemonClient
from tapesmith.ipc.codec import decode_request, encode_request
from tapesmith.ipc.pipe import client_handshake, memory_channel_pair, pipe_name, server_handshake
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel, PrintRequest
from tapesmith.render.barcode import render_code128
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.render.datamatrix import render_datamatrix
from tapesmith.render import zxing
from tapesmith.render.icons import render_icon
from tapesmith.tape.profiles import find_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.templates.lint import lint_templates
from tapesmith.templates.store import builtin_templates, list_templates
from tapesmith.transport.base import FileTransport
from tapesmith.update import signing
from tapesmith.i18n import N_, _t

OK_LINE = "Selbsttest ok"
FAIL_LINE = N_("Selbsttest fehlgeschlagen")

SELFTEST_FONTS = ("sans", "sans-bold", "mono")
SELFTEST_TEMPLATES = ("datentraeger", "datentraeger-qr")
SELFTEST_QR = "HTTP://EXAMPLE.ORG/D7"
SELFTEST_CONFIG = {"mac": "001122334455", "idle_timeout_s": 0, "connect_timeout_s": 1, "guard": {},
                   "daemon": {"enabled": False}}
SELFTEST_CODE128 = "ASN01234"
SELFTEST_DATAMATRIX = "S4EWNX0R123456"
SELFTEST_ICON = "tabler:server"
SELFTEST_SERIAL = "S4EWNX0R123456"
SELFTEST_DARK_TAPE = "weiss-schwarz"
WEB_PORT = 8712      # nur für den Host-Header, es wird kein Port geöffnet
WEB_REQUESTS = (("GET", "/health", None),
                ("POST", "/api/v1/labels/render", {"source": {"kind": "text", "lines": ["Selbsttest"]}}),
                ("GET", "/api/v1/settings", None))

_ASSET_REF = re.compile(r"""(?:src|href)\s*=\s*["'](/assets/[^"'?#]+)""")
_ENV = ("TAPESMITH_HOME", "TAPESMITH_NO_DAEMON")


class StepWarning(Exception):
    """Schritt mit Einschränkung: wird als `WARNUNG name: …` gemeldet, der Selbsttest bleibt ok."""


def selftest_document(content_dots: int) -> LabelDocument:
    """Ein Dokument mit allen Objektarten."""
    h = content_dots
    image = prepare_embedded_image(Image.new("L", (24, 24), 0))
    return LabelDocument(objects=(
        TextObject(id="text", x=0, y=0, w=120, h=h // 2, text=_t("Selbsttest")),
        QrObject(id="qr", x=130, y=0, w=h, h=h, data=SELFTEST_QR),
        Code128Object(id="code", x=140 + h, y=0, w=240, h=h, data=SELFTEST_CODE128),
        DataMatrixObject(id="dm", x=390 + h, y=0, w=h, h=h, data=SELFTEST_DATAMATRIX),
        IconObject(id="icon", x=0, y=h // 2 + 2, w=40, h=40, icon=SELFTEST_ICON),
        LineObject(id="line", x=44, y=h // 2 + 4, w=80, h=2),
        RectObject(id="rect", x=44, y=h // 2 + 10, w=40, h=20),
        ImageObject(id="image", x=90, y=h // 2 + 10, w=24, h=24, png=image),
    ))


def asgi_request(app, method: str, path: str, *, token: str, body: dict | None = None,
                 port: int = WEB_PORT) -> tuple[int, bytes]:
    """Eine Anfrage direkt an die ASGI-App (ohne Socket, ohne httpx): (Status, Körper)."""
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = [(b"host", f"127.0.0.1:{port}".encode()), (b"x-p12-token", token.encode())]
    if body is not None:
        headers.append((b"content-type", b"application/json"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": headers, "client": ("127.0.0.1", 50000),
             "server": ("127.0.0.1", port)}
    sent = {"status": 0, "body": b""}
    received = {"done": False}

    async def receive() -> dict:
        if received["done"]:
            return {"type": "http.disconnect"}
        received["done"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
        elif message["type"] == "http.response.body":
            sent["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return sent["status"], sent["body"]


def check_static(static_dir: Path) -> str:
    """Gebaute Oberfläche vollständig? `index.html` muss existieren und jede dort referenzierte
    `/assets/`-Datei ebenfalls, sonst `RuntimeError` mit den fehlenden Namen."""
    index = static_dir / "index.html"
    if not index.is_file():
        raise RuntimeError(_t("index.html fehlt in {static_dir} (python tools/build_web.py ausführen)", static_dir=static_dir))
    refs = sorted(set(_ASSET_REF.findall(index.read_text(encoding="utf-8"))))
    if not refs:
        raise RuntimeError(_t("index.html verweist auf keine /assets/-Datei"))
    missing = [ref for ref in refs if not (static_dir / ref.lstrip("/")).is_file()]
    if missing:
        raise RuntimeError(_t("Dateien fehlen: {items}", items=', '.join(missing)))
    if len(refs) == 1:
        return _t("index.html und 1 Datei aus /assets/")
    return _t("index.html und {count} Dateien aus /assets/", count=len(refs))


_OLD_WINDOW_MODULES = ("webview", "clr", "clr_loader", "pythonnet", "tapesmith.gui.quick_popup",
                       "tapesmith.gui.clip_toast", "tapesmith.gui.tray_settings")


def check_browser_start(*, frozen: bool | None = None) -> str:
    """Browserstart ohne Browser: `webui.browser.open_app` mit Fake-Sitzung und Fake-Öffner muss
    die Adresse mit Token im Fragment bauen. In einem eingefrorenen Build darf das frühere App-Fenster
    (pywebview, pythonnet) nicht mehr enthalten sein."""
    from tapesmith.webui import browser

    opened: list[str] = []
    url = browser.open_app("/einstellungen?abschnitt=updates", config_loader=dict,
                           connector=lambda cfg: {"port": 8712, "token": "probe"}, opener=opened.append)
    expected = "http://127.0.0.1:8712/einstellungen?abschnitt=updates#t=probe"
    if url != expected or opened != [expected]:
        raise RuntimeError(_t("falsche Adresse {url!r}", url=url))
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        import importlib.util

        found = [name for name in _OLD_WINDOW_MODULES if importlib.util.find_spec(name) is not None]
        if found:
            raise RuntimeError(_t("altes App-Fenster im Build: {items}", items=', '.join(found)))
    return _t("Adresse mit Token ok, kein App-Fenster")


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    """Alle Blatt-Schlüssel eines verschachtelten Katalogs als `a.b.c`."""
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            keys |= _flat_keys(value, path)
        else:
            keys.add(path)
    return keys


def check_translations() -> str:
    """Kataloge `de` und `en` laden: beide nicht leer, gleiche Schlüssel; Meldungskatalog `en` lesbar."""
    i18n.reload_catalogs()
    de = _flat_keys(i18n.catalog("de"))
    en = _flat_keys(i18n.catalog("en"))
    if not de or not en:
        raise RuntimeError(_t("Übersetzungskatalog leer (de {count}, en {count2} Schlüssel)", count=len(de), count2=len(en)))
    only_de, only_en = sorted(de - en), sorted(en - de)
    if only_de or only_en:
        parts = []
        if only_de:
            parts.append(_t("nur in de: {items}", items=', '.join(only_de[:3])))
        if only_en:
            parts.append(_t("nur in en: {items}", items=', '.join(only_en[:3])))
        raise RuntimeError("; ".join(parts))
    messages = i18n.messages("en")
    if not messages:
        raise RuntimeError(_t("Meldungskatalog en leer oder nicht lesbar"))
    return _t("de/en, {count} Schlüssel, {messages} Meldungen", count=len(de), messages=len(messages))


def check_update_signature() -> str:
    """Schlüsselpaar im Speicher, Manifest signieren und prüfen, `trusted_keys.json` lesbar."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    entry = signing.public_entry(private.public_key())
    data = json.dumps({"schema": 1, "app": "tapesmith", "version": "0.0.0"}).encode("utf-8")
    signature = signing.sign(data, private)
    if signing.verify(data, signature, [(entry["id"], private.public_key())]) != entry["id"]:
        raise RuntimeError(_t("Signaturprüfung liefert den falschen Schlüssel"))
    try:
        signing.verify(data + b" ", signature, [(entry["id"], private.public_key())])
    except Exception:  # noqa: BLE001 (erwartet: veränderte Daten werden abgelehnt)
        pass
    else:
        raise RuntimeError(_t("veränderte Daten wurden als gültig erkannt"))
    path = Path(signing.TRUSTED_KEYS_PATH)
    if not path.is_file():
        raise RuntimeError(_t("trusted_keys.json fehlt im Paket ({path})", path=path))
    keys = signing.load_trusted_keys(path)
    return _t("Ed25519 ok, {count} hinterlegte Schlüssel", count=len(keys))


def check_install_layout(tmp: Path) -> str:
    """Junction in einem Temp-Ordner anlegen, umstellen und entfernen (kein Adminrecht nötig)."""
    from tapesmith.install import junction

    base = tmp / "installationsprobe"
    first, second = base / "versions" / "0.0.1", base / "versions" / "0.0.2"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (second / "marke.txt").write_text("0.0.2", encoding="utf-8")
    link = base / "current"
    try:
        junction.create_junction(link, first)
        if junction.read_junction(link) is None:
            raise RuntimeError(_t("Junction nicht angelegt"))
        junction.switch_junction(link, second)
        if not (link / "marke.txt").is_file():
            raise RuntimeError(_t("Junction zeigt nach dem Umstellen nicht auf die neue Version"))
        os.rmdir(link)
        if not (second / "marke.txt").is_file():
            raise RuntimeError(_t("Entfernen der Junction hat das Ziel gelöscht"))
    finally:
        if junction.read_junction(link) is not None:
            os.rmdir(link)
        shutil.rmtree(base, ignore_errors=True)
    return _t("Junction anlegen, umstellen, entfernen ok")


def _steps(tmp: Path) -> list[tuple[str, Callable[[], str]]]:
    state: dict = {}

    def profile():
        if "profile" not in state:
            state["profile"] = load_profile()
        return state["profile"]

    def selftest_request(title: str) -> PrintRequest:
        head = render_label(LabelSpec(lines=(title,)), profile()).head
        return PrintRequest(labels=(PrintLabel(head),),
                            meta=JobMeta(source="gui", kind="text", title=title))

    @contextlib.contextmanager
    def service(name: str):
        """Druckdienst mit Datei-Transport, Verlauf und Warteschlange im Temp-Ordner."""
        target = tmp / f"{name}.bin"
        cfg = {**config_mod.DEFAULTS, **SELFTEST_CONFIG, "transport": "file:" + str(target)}
        history = HistoryStore(tmp / f"{name}.db")
        queue = JobQueue(tmp / f"{name}-queue.db")
        svc = PrintService(
            config_loader=lambda: dict(cfg), profile_loader=profile,
            transport_factory=lambda c, p: (lambda: FileTransport(target)),
            lock_factory=contextlib.nullcontext, sleep=lambda s: None, history=history, queue=queue,
            rolls=RollStore(tmp / f"{name}-rollen.json", tape=lambda: "schwarz-weiss"),
            archive_factory=lambda c: None, watch_files=False)
        try:
            yield svc
        finally:
            svc.close()
            queue.close()
            history.close()

    def step_profile() -> str:
        p = profile()
        return _t("{model}, {head_dots} Punkte", model=p.model, head_dots=p.head_dots)

    def step_fonts() -> str:
        for font in SELFTEST_FONTS:
            render_label(LabelSpec(lines=(_t("Selbsttest"),), font=font), profile())
        return ", ".join(SELFTEST_FONTS)

    def step_templates() -> str:
        names = {t.name for t in list_templates()}
        missing = [n for n in SELFTEST_TEMPLATES if n not in names]
        if missing:
            raise RuntimeError(_t("Vorlagen fehlen: {items}", items=', '.join(missing)))
        return _t("{count} Vorlagen", count=len(names))

    def step_qr() -> str:
        result = render_label(LabelSpec(qr=SELFTEST_QR), profile())
        return f"{result.length_mm:.1f} mm"

    def step_document() -> str:
        doc = selftest_document(profile().content_dots)
        dr = render_document(doc, profile())
        if dr.errors:
            raise RuntimeError("; ".join(f"{i.object_id}: {i.message}" for i in dr.errors))
        return _t("{count} Objekte, {length_mm:.1f} mm", count=len(doc.objects), length_mm=dr.length_mm)

    def step_codes() -> str:
        code = render_code128(SELFTEST_CODE128, 3, 88)
        dm = render_datamatrix(SELFTEST_DATAMATRIX, 88)
        failed = [r.kind for r in (code, dm) if not r.decodes and _t(zxing.NOT_READ_WARNING) not in r.warnings]
        if failed:
            raise RuntimeError(_t("Selbsttest nicht lesbar: {items}", items=', '.join(failed)))
        return _t("Code128 {width} Punkte, DataMatrix Modul {module_dots}", width=code.image.width, module_dots=dm.module_dots)

    def step_decoder() -> str:
        if not zxing.available():
            raise StepWarning(zxing.status_text())
        return zxing.status_text()

    def step_icons() -> str:
        image = render_icon(SELFTEST_ICON, 40)
        if not any(color == 0 for _count, color in image.convert("1").getcolors() or ()):
            raise RuntimeError(_t("Icon leer"))
        return f"{SELFTEST_ICON} {image.width}×{image.height}"

    def step_invert() -> str:
        spec = LabelSpec(lines=("INV",), qr=SELFTEST_QR)
        dark = render_spec(spec, profile(), find_tape(SELFTEST_DARK_TAPE))
        light = render_spec(spec, profile(), find_tape("schwarz-weiss"))
        if dark.head.tobytes() == light.head.tobytes():
            raise RuntimeError(_t("QR auf dunklem Band nicht invertiert"))
        return _t("QR invertiert auf {selftest_dark_tape}", selftest_dark_tape=SELFTEST_DARK_TAPE)

    def step_lint() -> str:
        templates = builtin_templates()
        errors = [i for i in lint_templates(templates, profile()) if i.level == "error"]
        if errors:
            raise RuntimeError("; ".join(f"{i.template} ({i.data}): {i.message}" for i in errors[:3]))
        return _t("{count} Vorlagen ohne Fehler", count=len(templates))

    def step_ipc() -> str:
        client_ch, server_ch = memory_channel_pair()
        box: dict = {}

        def serve() -> None:
            try:
                box["hello"] = server_handshake(server_ch, timeout_s=5.0)
            except Exception as exc:  # noqa: BLE001 (wird unten gemeldet)
                box["error"] = exc

        thread = threading.Thread(target=serve, name="p12-selbsttest-ipc", daemon=True)
        thread.start()
        try:
            client_handshake(client_ch, "gui", timeout_s=5.0)
        finally:
            thread.join(5.0)
            client_ch.close()
            server_ch.close()
        if "error" in box:
            raise RuntimeError(_t("Handshake: {error}", error=box['error']))
        request = selftest_request("IPC")
        decoded = decode_request(encode_request(request))
        if decoded.labels[0].head.tobytes() != request.labels[0].head.tobytes():
            raise RuntimeError(_t("Label nach Kodierung verändert"))
        return _t("Handshake ok, Label unverändert")

    def step_daemon() -> str:
        with service("dienst") as svc:
            outcome = svc.submit(selftest_request(_t("Dienst")), job_key="selbsttest")
            if outcome.status != "ok":
                reasons = "; ".join(outcome.reasons)
                raise RuntimeError(f"Druckauftrag: {outcome.status} {reasons}".strip())
            server = DaemonServer(svc, name=pipe_name())
            server.start()
            client = None
            try:
                client = DaemonClient.connect(client="gui", name=server.name, timeout_s=5.0)
                pong = client.call("ping", timeout=5.0)
            finally:
                if client is not None:
                    client.close()
                server.stop()
            return _t("Auftrag ok, Pipe ok (Version {get})", get=pong.get('version', '?'))

    def step_queue() -> str:
        queue = JobQueue(tmp / "queue.db")
        try:
            job_id = queue.add({"selbsttest": True}, source="gui", title=_t("Selbsttest"), sensitive=False)
            if [job.id for job in queue.list()] != [job_id]:
                raise RuntimeError(_t("Auftrag nicht in der Warteschlange"))
            return _t("Auftrag #{job_id} eingereiht", job_id=job_id)
        finally:
            queue.close()

    def step_clipboard() -> str:
        suggestion = classify_clipboard(SELFTEST_SERIAL)
        if suggestion.template != "datentraeger":
            raise RuntimeError(_t("Seriennummer als {value} erkannt", value=suggestion.kind.value))
        return f"{SELFTEST_SERIAL} -> {suggestion.template}"

    def step_web_api() -> str:
        from tapesmith.webapi.app import create_app
        from tapesmith.webapi.context import ApiContext
        from tapesmith.webapi.events import EventBroker

        with service("web") as svc:
            ctx = ApiContext(service=svc, home_key="selbsttest", token=secrets.token_urlsafe(16),
                             broker=EventBroker(), static_dir=webui.static_dir(), port=WEB_PORT)
            try:
                app = create_app(ctx)
                results = {path: asgi_request(app, method, path, token=ctx.token, body=body)[0]
                           for method, path, body in WEB_REQUESTS}
            finally:
                ctx.close()
        failed = [f"{path} ({status})" for path, status in results.items() if status != 200]
        if failed:
            raise RuntimeError(_t("Routen antworten nicht: {items}", items=', '.join(failed)))
        return f"{', '.join(results)} ok"

    def step_static() -> str:
        return check_static(webui.static_dir())

    def step_uvicorn() -> str:
        import uvicorn  # noqa: F401
        import uvicorn.lifespan.off  # noqa: F401
        import uvicorn.loops.asyncio  # noqa: F401
        import uvicorn.protocols.http.h11_impl  # noqa: F401

        return _t("uvicorn importierbar")

    return [(N_("profil"), step_profile), (N_("schriften"), step_fonts), (N_("vorlagen"), step_templates),
            (N_("qr"), step_qr), (N_("Dokument"), step_document), (N_("Codes"), step_codes),
            (N_("Barcode-Decoder"), step_decoder), (N_("Icons"), step_icons), (N_("Invertierung"), step_invert), (N_("Vorlagen-Lint"), step_lint),
            (N_("IPC"), step_ipc), (N_("Dienst"), step_daemon), (N_("Warteschlange"), step_queue),
            (N_("Zwischenablage"), step_clipboard), (N_("Web-API"), step_web_api),
            (N_("Oberfläche"), step_static), (N_("Webserver"), step_uvicorn),
            (N_("Browserstart"), check_browser_start),
            (N_("Übersetzungen"), check_translations), (N_("Update-Signatur"), check_update_signature),
            (N_("Installationslayout"), lambda: check_install_layout(tmp))]


def run_selftest(out: TextIO) -> bool:
    """Alle Schritte ausführen, je Schritt `OK name: …`, `WARNUNG name: …` (zählt nicht als Fehler)
    bzw. `FEHLER name: …`, letzte Zeile „Selbsttest ok“ oder „Selbsttest fehlgeschlagen“.
    Umgebung wird wiederhergestellt."""
    ok = True
    saved = {name: os.environ.get(name) for name in _ENV}
    with tempfile.TemporaryDirectory(prefix="tapesmith-selftest-", ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        os.environ["TAPESMITH_HOME"] = str(tmp_path / "home")
        os.environ["TAPESMITH_NO_DAEMON"] = "1"     # nie einen Druckdienst starten oder nutzen
        try:
            for name, step in _steps(tmp_path):
                try:
                    detail = step()
                except StepWarning as warning:
                    print(_t("WARNUNG {name}: {warning}", name=_t(name), warning=warning), file=out)
                except Exception as exc:  # noqa: BLE001 (jeder Fehler wird gemeldet, nicht geworfen)
                    ok = False
                    print(_t("FEHLER {name}: {exc}", name=_t(name), exc=exc), file=out)
                else:
                    print(f"OK {_t(name)}: {detail}", file=out)
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    print(OK_LINE if ok else _t(FAIL_LINE), file=out)
    with contextlib.suppress(OSError, ValueError):
        out.flush()
    return ok


def main(argv: list[str] | None = None) -> int:
    """`--selftest` (optional, für Weiterreichungen) und `--selftest-out DATEI`. Exit 0/1.
    Ohne Konsole (Fenster-EXE, `sys.stdout` ist None) landet die Ausgabe im Log-Ordner."""
    parser = argparse.ArgumentParser(prog="tapesmith --selftest", description=_t("Selbsttest (druckt nie)"))
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--selftest-out", type=Path, metavar=_t("PFAD"), help=_t("Ausgabe in diese Datei schreiben"))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.selftest_out is not None:
        with open(args.selftest_out, "w", encoding="utf-8") as out:
            return 0 if run_selftest(out) else 1
    if sys.stdout is not None:
        return 0 if run_selftest(sys.stdout) else 1
    with open(paths.log_dir() / "selftest.txt", "w", encoding="utf-8") as out:
        return 0 if run_selftest(out) else 1


if __name__ == "__main__":
    sys.exit(main())
