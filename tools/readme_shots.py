"""Aufnahmen für die README (docs/readme): wenige, ausgesuchte Seiten auf Englisch, mit freundlichen
Alltagsinhalten statt Technik-Demo, danach mit Pillow gerahmt (runde Ecken, weicher Schatten,
dezenter Verlauf als Hintergrund).

Aufruf (mit dem gemeinsamen venv, Playwright und Chromium installiert):

    .venv\\Scripts\\python tools\\readme_shots.py [--out docs/readme] [--home C:\\Tapesmith-Readme]

Nutzt die Bausteine von `tools/screenshots.py` (Demo-Home mit Marker, Druckdienst und Web-Oberfläche
im eigenen Prozess, Datei-Transport, neutrale Netzwerkkennung). Es wird nie gedruckt, nie ein echtes
Gerät geöffnet und nie der echte Datenordner benutzt.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools import demo_data  # noqa: E402
from tools import screenshots as shots  # noqa: E402

DEFAULT_HOME = "C:\\Tapesmith-Readme"
VIEWPORT = (1280, 800)
SCALE = 2
MODULES = ("inventar",)
FAVORITES = ("eigentum", "kabelwickel", "geoeffnet-am")

DOCUMENT_NAME = "Attic box"
QUICK_TEXT = "Garage · Box 3"
TEMPLATE_VALUES = '{"inhalt":"Coffee beans","symbol":"Coffee"}'

# Freundliche, frei erfundene Inhalte (Englisch), neueste zuletzt.
HISTORY_PLAIN = (
    (("Christmas decorations", "Attic · Box 15"), 26),
    (("Laptop charger", "65 W USB-C"), 19),
    (("Garage · Box 3", "Bike tools"), 12),
    (("Property of Alex",), 8),
    (("Cumin", "Best before 03/2027"), 1),
)
HISTORY_TEMPLATES = (
    ("vorratsdose", {"inhalt": "Flour", "symbol": "Flour"}, 30),
    ("vorratsdose", {"inhalt": "Basmati rice", "symbol": "Rice"}, 22),
    ("gefriergut", {"inhalt": "Lasagne", "kategorie": "Ready meal"}, 15),
    ("aufbewahrungsbox", {"nummer": "BOX 3", "ort": "Garage shelf"}, 10),
    ("vorratsdose", {"inhalt": "Earl Grey", "symbol": "Tea"}, 4),
)
LOG_LINES = (
    (-7200, "INFO", "tapesmith.daemon", "Print service started (port 8712)"),
    (-7190, "INFO", "tapesmith.transport", "Connected to P12 via COM3"),
    (-7185, "INFO", "tapesmith.status", "Battery 85 %, cover closed, tape inserted"),
    (-6600, "INFO", "tapesmith.jobs", "Job 41 printed: 1 label, 38 mm"),
    (-6000, "INFO", "tapesmith.connection", "Printer idle, connection released"),
    (-4500, "INFO", "tapesmith.transport", "Connected to P12 via COM3"),
    (-4490, "INFO", "tapesmith.jobs", "Job 42 printed: 3 labels, 126 mm"),
    (-4200, "INFO", "tapesmith.jobs", "Job 43 printed: 1 label, 52 mm"),
    (-3600, "INFO", "tapesmith.connection", "Printer idle, connection released"),
    (-2700, "WARNING", "tapesmith.transport", "No answer from the printer after 5 s, retrying"),
    (-2685, "INFO", "tapesmith.transport", "Connected to P12 via COM3"),
    (-2680, "INFO", "tapesmith.jobs", "Job 44 printed: 1 label, 70 mm"),
    (-2400, "INFO", "tapesmith.queue", "Queue empty"),
    (-1800, "INFO", "tapesmith.update", "No update available (current 0.4.4)"),
    (-1200, "ERROR", "tapesmith.jobs", "Job 45 not printed: cover open"),
    (-1150, "INFO", "tapesmith.jobs", "Job 45 printed after retry: 2 labels, 80 mm"),
    (-600, "INFO", "tapesmith.rolls", "Tape roll: about 2.6 m left"),
    (-60, "INFO", "tapesmith.connection", "Printer idle, connection released"),
)


@dataclass(frozen=True)
class ReadmeShot:
    name: str
    route: str
    theme: str = "hell"
    interact: str | None = None


SHOTS = (
    ReadmeShot("quick-print", f"/schnelldruck?text={quote(QUICK_TEXT)}"),
    ReadmeShot("quick-print-dark", f"/schnelldruck?text={quote(QUICK_TEXT)}", theme="dunkel"),
    ReadmeShot("templates", f"/vorlagen?vorlage=vorratsdose&werte={quote(TEMPLATE_VALUES)}",
               interact="filter_kitchen"),
    ReadmeShot("editor", f"/editor?dokument={quote(DOCUMENT_NAME)}", interact="select_one"),
    ReadmeShot("gallery", "/galerie"),
    ReadmeShot("history", "/verlauf"),
    ReadmeShot("log", "/protokoll"),
)

def _filter_kitchen(page, info: dict) -> None:
    """Vorlagenliste auf die Küchen-Vorlagen eingrenzen, damit die gewählte Vorlage sichtbar ist."""
    page.get_by_placeholder("Name, tag, description").fill("kitchen")
    page.wait_for_timeout(400)


INTERACTIONS = {"filter_kitchen": _filter_kitchen}

# Hinweise (Toasts) und Tooltips sollen auf den Bildern nie erscheinen.
HIDE_CSS = """
.fui-Toast, .fui-Toaster, [data-toaster-id], .fui-Tooltip, [role='tooltip'] { display: none !important; }
*, *::before, *::after { caret-color: transparent !important; }
"""


# ---------------------------------------------------------------------------
# Demo-Daten
# ---------------------------------------------------------------------------

def _seed(home: Path, now: datetime) -> None:
    from tapesmith import config as config_mod, paths
    from tapesmith.device.profile import load_profile
    from tapesmith.document.model import IconObject, LabelDocument, QrObject, TextObject
    from tapesmith.history import HistoryStore
    from tapesmith.i18n import use_language
    from tapesmith.tape.profiles import current_tape
    from tapesmith.webapi.documents import save_document

    config_mod.save_config({
        "transport": f"file:{home / 'job.bin'}",
        "tape": {"current": demo_data.TAPE_ID},
        "gui": {"favorites": list(FAVORITES)},
        "modules": {"enabled": list(MODULES)},
        "app": {"language": "en"},
    })
    demo_data._LANG[0] = "en"  # noqa: SLF001 (Demo-Helfer)
    profile = load_profile()
    tape = current_tape(config_mod.load_config())

    entries = []
    with use_language("en"):
        for name, values, days in HISTORY_TEMPLATES:
            entries.append((timedelta(days=days), demo_data._from_template(  # noqa: SLF001
                name, values, profile, tape, now=now)))
        for lines, days in HISTORY_PLAIN:
            entries.append((timedelta(days=days, hours=2), demo_data._plain(profile, lines)))  # noqa: SLF001
        entries.append((timedelta(days=6), demo_data._wifi_qr("Guest WiFi", "sunny-garden-42", profile)))  # noqa: SLF001
    entries.sort(key=lambda item: item[0], reverse=True)
    store = HistoryStore(clock=demo_data._Clock(now))  # noqa: SLF001
    try:
        for age, rendered in entries:
            store._clock.value = now - age  # noqa: SLF001
            store.record(rendered.meta, landscape=rendered.result.landscape, head=rendered.result.head,
                         length_mm=rendered.result.length_mm, tape_mm=rendered.result.tape_mm,
                         status="ok", error="")
    finally:
        store.close()

    demo_data._seed_inventory(now=now)  # noqa: SLF001
    demo_data._seed_rolls(now=now)  # noqa: SLF001
    save_document(DOCUMENT_NAME, LabelDocument(objects=(
        IconObject(id="icon1", x=8, y=12, w=64, h=64, icon="tabler:box"),
        TextObject(id=demo_data.SELECTED_OBJECT_ID, x=84, y=6, w=300, h=76,
                   text="Christmas decorations\nAttic · Box 15", font="sans", size=20, align="left",
                   valign="middle"),
        QrObject(id="qr1", x=396, y=4, w=80, h=80, data="https://example.com/box/15", error="m"),
    )))
    lines = [f"{(now + timedelta(seconds=dt)).strftime('%Y-%m-%d %H:%M:%S')},000 {level} {name}: {msg}"
             for dt, level, name, msg in LOG_LINES]
    (paths.log_dir() / "daemon.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Rahmen (Pillow)
# ---------------------------------------------------------------------------

BACKGROUNDS = {
    "hell": ((233, 239, 248), (247, 249, 252)),
    "dunkel": ((24, 32, 46), (12, 16, 23)),
}


def frame(raw: Path, out: Path, theme: str, *, width: int = 1600) -> None:
    """Rundet die Ecken ab, legt einen weichen Schatten darunter und setzt das Bild mit Rand auf
    einen dezenten Verlauf. Ergebnis als optimiertes PNG mit `width` Pixel Breite."""
    from PIL import Image, ImageDraw, ImageFilter

    shot = Image.open(raw).convert("RGBA")
    w, h = shot.size
    radius = int(w * 0.012)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    shot.putalpha(mask)

    pad = int(w * 0.045)
    canvas_w, canvas_h = w + 2 * pad, h + 2 * pad
    top, bottom = BACKGROUNDS[theme]
    gradient = Image.new("RGBA", (1, canvas_h))
    for y in range(canvas_h):
        t = y / max(1, canvas_h - 1)
        gradient.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    canvas = gradient.resize((canvas_w, canvas_h))

    shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    offset = int(pad * 0.25)
    alpha = 90 if theme == "hell" else 160
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad + offset, pad + w, pad + h + offset), radius=radius, fill=(15, 23, 42, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad * 0.35))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.alpha_composite(shot, (pad, pad))
    # dünne Kante, damit helle Seiten sich vom hellen Hintergrund lösen
    edge = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle((pad, pad, pad + w - 1, pad + h - 1), radius=radius,
                                           outline=(15, 23, 42, 40 if theme == "hell" else 90), width=2)
    canvas = Image.alpha_composite(canvas, edge)

    final = canvas.convert("RGB").resize((width, int(canvas_h * width / canvas_w)), Image.LANCZOS)
    final.save(out, optimize=True)
    if out.stat().st_size > MAX_BYTES:
        # Zu groß: Palette mit Octree (erhält auch kleine Farbflächen wie den grünen Statuspunkt)
        final.quantize(colors=256, method=Image.Quantize.FASTOCTREE, kmeans=2).save(out, optimize=True)


MAX_BYTES = 600_000


# ---------------------------------------------------------------------------
# Aufnahme
# ---------------------------------------------------------------------------

def _capture(playwright_mod, port: int, token: str, raw_dir: Path) -> list[str]:
    problems: list[str] = []
    browser = playwright_mod.chromium.launch()
    try:
        for shot in SHOTS:
            os.environ["TAPESMITH_SYSTEM_LANG"] = "en"
            shots.reset_drafts(Path(os.environ["TAPESMITH_HOME"]))
            context = browser.new_context(
                viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
                color_scheme="dark" if shot.theme == "dunkel" else "light",
                reduced_motion="reduce", locale="en-US", timezone_id="Europe/Berlin",
                device_scale_factor=SCALE)
            page = context.new_page()
            page.route(shots.INTERCEPT_PATTERN, shots._serve_demo_services)  # noqa: SLF001
            errors: list[str] = []
            page.on("pageerror", lambda exc, _e=errors: _e.append(str(exc)))
            try:
                page.goto(shots.page_url(port, token, shot.route), wait_until="load")
                shots._wait_ready(page)  # noqa: SLF001
                page.add_style_tag(content=HIDE_CSS)
                if shot.interact:
                    INTERACTIONS.get(shot.interact, shots.INTERACTIONS.get(shot.interact))(page, {"lang": "en"})
                    shots._wait_ready(page)  # noqa: SLF001
                page.evaluate("() => { const el = document.activeElement; if (el && el !== document.body) el.blur(); }")
                shots._clear_stray_overlay_backgrounds(page)  # noqa: SLF001
                page.mouse.move(VIEWPORT[0] - 2, VIEWPORT[1] - 2)
                page.wait_for_timeout(600)
                page.screenshot(path=str(raw_dir / f"{shot.name}.png"))
            except Exception as exc:  # noqa: BLE001 (eine Seite darf den Lauf nicht stoppen)
                errors.append(f"aufnahme fehlgeschlagen: {exc}")
            finally:
                context.close()
            problems.extend(f"{shot.name}: {e}" for e in errors)
    finally:
        browser.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/readme")
    parser.add_argument("--home", default=DEFAULT_HOME)
    parser.add_argument("--keep-raw", action="store_true", help="Rohaufnahmen behalten (im Ordner raw)")
    args = parser.parse_args(argv)

    home = shots.prepare_demo_home(Path(args.home))
    os.environ["TAPESMITH_HOME"] = str(home)
    os.environ["TAPESMITH_WEB_PORT"] = "0"
    os.environ["TAPESMITH_NO_DAEMON"] = "1"
    os.environ["TAPESMITH_SYSTEM_LANG"] = "en"
    os.environ.setdefault("TAPESMITH_LOCK_NAME", f"Local\\Tapesmith.Readme.{os.getpid()}")
    shots._neutral_network_identity()  # noqa: SLF001
    _seed(home, datetime.now())

    import playwright.sync_api as sync_api

    from tapesmith.daemon.service import PrintService
    from tapesmith.ipc import pipe
    from tapesmith.webapi.server import WebServer

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    service = PrintService()
    server = WebServer(service, port=0, home_key=pipe.home_key())
    try:
        server.start()
        assert server.ctx is not None
        server.ctx.accent_reader = lambda: "#0f6cbd"
        try:
            service.status()  # Statuszeile „connected“ (Datei-Transport antwortet sofort)
        except Exception:  # noqa: BLE001
            pass
        with sync_api.sync_playwright() as playwright_mod:
            problems = _capture(playwright_mod, server.port, server.token, raw_dir)
    finally:
        server.stop()
        service.close()
        shutil.rmtree(home, ignore_errors=True)

    for shot in SHOTS:
        raw = raw_dir / f"{shot.name}.png"
        if raw.is_file():
            frame(raw, out / f"{shot.name}.png", shot.theme)
    if not args.keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{sum((out / f'{s.name}.png').is_file() for s in SHOTS)} von {len(SHOTS)} Bildern in {out}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
