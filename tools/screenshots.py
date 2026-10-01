"""Screenshots aller Seiten der Web-Oberfläche (Playwright) und Rauchtest.

Aufruf (aus dem Worktree, mit dem gemeinsamen venv):

    .venv\\Scripts\\python tools\\screenshots.py [--out docs/screenshots]
        [--only schnelldruck,editor] [--themes hell,dunkel] [--sizes desktop,handy,zoom200]
        [--langs de,en] [--keep-home] [--home C:\\Tapesmith-Demo]

Startet den Druckdienst (`PrintService`) und die Web-Oberfläche (`WebServer`) im eigenen Prozess
mit einem frischen Demo-Home (`TAPESMITH_HOME`, Standard `C:\\Tapesmith-Demo`), füllt es über `tools.demo_data.seed_demo` mit
Demo-Daten (Datei-Transport, nie ein echtes Gerät, nie echte Nutzerdaten) und nimmt mit einem
headless Chromium jede Seite in Hell/Dunkel und Desktop/Handy-Breite auf. Gleichzeitig sammelt es
für jede Seite Konsolenfehler und fehlgeschlagene `/api/`-Aufrufe (Rauchtest): Exit 1, wenn welche
auftraten (die Aufnahmen werden trotzdem gespeichert).

Zusätzlich Englisch (alle Hauptseiten und die Modulseiten, Desktop, hell und dunkel, Dateiname mit
`-en`, Sprache über `navigator.languages` des Browser-Kontexts) und die Größe `zoom200` (720 × 450 mit
doppelter Pixeldichte, also 1440 × 900 bei 200 % Zoom; nur hell, Deutsch, Hauptseiten). Nach jeder
Aufnahme läuft axe-core (`web/node_modules/axe-core/axe.min.js`) im echten Chromium mit den Regeln
WCAG 2 A, AA und 2.1 AA inklusive Farbkontrast; jede Verletzung ist ein Rauchtest-Befund. Ebenso
ein waagrechter Überlauf (Inhalt breiter als der Inhaltsbereich `#inhalt` bzw. die Seite breiter als
das Fenster), denn `main` schneidet ihn ab und die Seite soll bis 200 % nie waagrecht scrollen.

Externe Dienste (Proxmox, Home Assistant, Paperless, Obsidian, SSH-Scan, ZFS) beantwortet der
Browser selbst mit den Demo-Daten aus `tools.demo_services` (Playwright `page.route`), damit die
Modulseiten realistisch volle Listen zeigen; es wird nie ein echter Dienst angefragt.

Reine, seiteneffektfreie Bausteine (von `tests/test_screenshots_tool.py` geprüft, ohne Browser):
`shot_plan`, `shot_filename`, `page_url`, `is_expected_error`, `write_index`, `axe_issues`,
`overflow_issue`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.demo_services import INTERCEPT_PATTERN, demo_response  # noqa: E402
from tools.demo_data import (  # noqa: E402
    DOCUMENT_NAME,
    SECOND_DOCUMENT_NAME,
    SELECTED_OBJECT_ID,
    reset_drafts,
    seed_demo,
    seed_orphaned_drafts,
)

THEMES: tuple[str, ...] = ("hell", "dunkel")
SIZES: tuple[str, ...] = ("desktop", "handy", "zoom200")
LANGS: tuple[str, ...] = ("de", "en")
BROWSER_LOCALES: dict[str, str] = {"de": "de-DE", "en": "en-US"}
DEFAULT_VIEWPORTS: dict[str, tuple[int, int]] = {"desktop": (1440, 900), "handy": (390, 844),
                                                 "zoom200": (720, 450)}
# 200 %: halbe CSS-Breite bei doppelter Pixeldichte, also dieselben Gerätepixel wie Desktop.
DEVICE_SCALE: dict[str, int] = {"desktop": 1, "handy": 2, "zoom200": 2}
AXE_SCRIPT = ROOT / "web" / "node_modules" / "axe-core" / "axe.min.js"
AXE_TAGS: tuple[str, ...] = ("wcag2a", "wcag2aa", "wcag21aa")
DEMO_TEXT_LINES = "pmx10 SSD-1\nSN 274913"
DEMO_QR_URL = "https://wiki.example.com/pmx10"
DEMO_TEMPLATE_VALUES = {"host": "pmx10", "slot": "SSD-1", "sn": "112233274913"}
DEMO_RASTER_VALUES = {"belegung": "server01\nserver02\nNAS\n\nAP-OG"}
READY_TIMEOUT_S = 10.0
# Demo-Datenordner mit neutralem Pfad: Pfadanzeigen (Log, App-Verzeichnis) zeigen so keinen
# Benutzernamen. Die Markerdatei schützt fremde Ordner gleichen Namens vor dem Löschen.
DEMO_HOME = "C:\\Tapesmith-Demo"
DEMO_MARKER = ".tapesmith-demo"


def prepare_demo_home(home: Path) -> Path:
    """Legt `home` leer an. Ein vorhandener Ordner wird nur geleert, wenn er die Markerdatei
    enthält (also von einem früheren Lauf stammt); sonst `RuntimeError`."""
    home = Path(home)
    if home.exists():
        if any(home.iterdir()) and not (home / DEMO_MARKER).is_file():
            raise RuntimeError(f"{home} existiert und ist kein Demo-Ordner (Marker {DEMO_MARKER} fehlt)")
        shutil.rmtree(home)
    home.mkdir(parents=True)
    (home / DEMO_MARKER).write_text("Demo-Daten von tools/screenshots.py\n", encoding="utf-8")
    return home
# Sichtbarer Inhalt irgendeiner Seite (auch /kompakt, das keinen AppShell-Rahmen hat): `#root`
# ist die React-Mount-Wurzel (siehe web/src/main.tsx). Ohne diese Wartemarke lieferte
# `_wait_ready` bereits nach "networkidle" + "keine Spinner mehr" zurück, obwohl Chromium
# headless in diesem Moment noch keinen sichtbaren Compositor-Frame gezeichnet hatte: der
# Screenshot zeigte dann nur die Hintergrundfarbe, obwohl das DOM längst korrekt war.
READY_SELECTOR = "#root :visible"


@dataclass(frozen=True)
class RouteSpec:
    key: str                       # ASCII-Seitenschlüssel (Dateiname)
    path: str                      # Pfad + Query
    title: str                     # Überschrift in index.md (darf Umlaute haben)
    sizes: tuple[str, ...] = SIZES
    viewport: dict[str, tuple[int, int]] = field(default_factory=dict)
    interact: str | None = None     # Schlüssel in INTERACTIONS (nach dem Laden ausgeführt)
    token_key: str | None = None    # Schlüssel in `info` für ein eigenes Token (sonst Sitzungs-Token)
    drafts: str | None = None       # "verwaist": vor der Aufnahme verwaiste Demo-Entwürfe anlegen
    full_page: bool = True          # False: nur der Viewport (modale Dialoge liegen über dem Viewport)
    modules: tuple[str, ...] | None = None  # eingeschaltete Module für diese Aufnahme (None: alle der Demo)
    english: bool = False           # Extra-Route zusätzlich auf Englisch (Desktop) aufnehmen


@dataclass(frozen=True)
class Shot:
    page: str
    theme: str
    size: str
    route: str
    viewport: tuple[int, int]
    full_page: bool
    is_mobile: bool
    device_scale_factor: int
    interact: str | None = None
    token_key: str | None = None
    lang: str = "de"
    drafts: str | None = None
    modules: tuple[str, ...] | None = None


def _q(text: str) -> str:
    return quote(text, safe="")


# Modulseiten: Desktop und Handy (Deutsch), dazu Englisch auf dem Desktop.
MODULE_SIZES: tuple[str, ...] = ("desktop", "handy")

MAIN_ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec("schnelldruck", f"/schnelldruck?text={_q(DEMO_TEXT_LINES)}", "Schnelldruck"),
    RouteSpec("editor", "/editor?dokument={document}", "Editor", interact="select_one"),
    RouteSpec("galerie", "/galerie", "Galerie"),
    RouteSpec("vorlagen",
             f"/vorlagen?vorlage=datentraeger&werte={_q(json.dumps(DEMO_TEMPLATE_VALUES))}", "Vorlagen"),
    RouteSpec("qr", f"/qr?inhalt={_q(DEMO_QR_URL)}", "QR-Code"),
    RouteSpec("verlauf", "/verlauf", "Verlauf"),
    RouteSpec("warteschlange", "/warteschlange", "Warteschlange"),
    RouteSpec("inventar", "/inventar", "Inventar"),
    RouteSpec("datentraeger", "/datentraeger?tab=ssh", "Datenträger", interact="ssh_scan"),
    RouteSpec("statistik", "/statistik", "Statistik"),
    RouteSpec("einstellungen", "/einstellungen", "Einstellungen"),
    RouteSpec("protokoll", "/protokoll", "Protokoll"),
    # Seite Zugriff (Demo-Tokens aus `seed_access_demo`) und Handy-Seite mit Familien-Token
    RouteSpec("zugriff", "/zugriff", "Zugriff"),
    RouteSpec("familie", "/familie", "Familie (Handy-Seite)", token_key="family_token"),
    # Homelab-Übersicht (Homelab-Werkzeuge) als Hauptseite
    RouteSpec("homelab", "/homelab", "Homelab"),
)

EXTRA_ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec("kompakt", "/kompakt", "Kompakt (Schnelldruck-Fenster)",
             sizes=("desktop",), viewport={"desktop": (560, 260)}),
    RouteSpec("kommandopalette", "/schnelldruck", "Kommandopalette",
             sizes=("desktop",), interact="command_palette"),
    RouteSpec("status-detail", "/schnelldruck", "Status-Detail",
             sizes=("desktop",), interact="status_detail"),
    # Raster-Vorlage mit gemischt langen Feldern: zeigt die einheitliche Schriftgröße.
    RouteSpec("vorlagen-raster",
             f"/vorlagen?vorlage=raster-patchpanel&werte={_q(json.dumps(DEMO_RASTER_VALUES))}",
             "Vorlagen: Raster-Patchpanel", sizes=("desktop",)),
    # Leere Vorlage: Vorschau mit Beispielinhalt statt Fehlermeldung
    RouteSpec("vorlagen-leer", "/vorlagen?vorlage=eigentum", "Vorlagen: leeres Formular", sizes=("desktop", "handy")),
    RouteSpec("serie-import", "/vorlagen?vorlage=datentraeger", "Serie/Import",
             sizes=("desktop",), interact="batch_dialog"),
    RouteSpec("ruecksprache-drucken", "/schnelldruck", "Rückfrage: Wirklich drucken?",
             sizes=("desktop",), interact="confirm_dialog"),
    # Homelab-Unterseite, Tastenkürzel, Editor-Tabs, Wiederherstellung und Updates
    RouteSpec("homelab-proxmox", "/homelab/proxmox", "Homelab: Proxmox", sizes=MODULE_SIZES, english=True,
              interact="proxmox_load"),
    RouteSpec("tastenkuerzel", "/galerie", "Tastenkürzel-Übersicht (Taste ?)",
             sizes=("desktop",), interact="shortcuts", full_page=False),
    RouteSpec("editor-tabs", "/editor?dokument={document}", "Editor mit zwei Tabs",
             sizes=("desktop",), interact="second_tab"),
    RouteSpec("wiederherstellen", "/editor?wiederherstellen=1", "Entwürfe wiederherstellen",
             sizes=("desktop",), drafts="verwaist", full_page=False),
    RouteSpec("einstellungen-updates", "/einstellungen?abschnitt=updates", "Einstellungen: Updates",
             sizes=("desktop",)),
    # Module: Schalter, Einstellungskarten, Abschnitt „Erweitert“ und die Oberfläche ohne Module
    RouteSpec("einstellungen-module", "/einstellungen?abschnitt=module", "Einstellungen: Module",
             sizes=("desktop",)),
    RouteSpec("einstellungen-paperless", "/einstellungen?abschnitt=modul-paperless", "Einstellungen: Paperless mit Token-Feld",
             sizes=("desktop",)),
    RouteSpec("einstellungen-proxmox", "/einstellungen?abschnitt=modul-proxmox", "Einstellungen: Proxmox-Hosts mit Tokens",
             sizes=("desktop",)),
    RouteSpec("einstellungen-tokens", "/einstellungen?abschnitt=tokens", "Einstellungen: Tokens und Passwörter",
             sizes=("desktop",)),
    RouteSpec("einstellungen-erweitert", "/einstellungen?abschnitt=erweitert", "Einstellungen: Erweitert",
             sizes=("desktop",)),
    RouteSpec("ohne-module", f"/schnelldruck?text={_q(DEMO_TEXT_LINES)}", "Ohne Module: Seitenleiste mit der Kernapp",
             sizes=("desktop",), modules=()),
    RouteSpec("einstellungen-ohne-module", "/einstellungen?abschnitt=module", "Ohne Module: Einstellungen",
             sizes=("desktop",), modules=()),
    RouteSpec("homelab-ohne-module", "/homelab", "Ohne Module: Homelab-Übersicht", sizes=("desktop",), modules=()),
    RouteSpec("modul-ausgeschaltet", "/inventar", "Ohne Module: Seite eines ausgeschalteten Moduls",
             sizes=("desktop",), modules=()),
    RouteSpec("datentraeger-plattentausch", "/datentraeger?tab=plattentausch", "Datenträger: Plattentausch",
              sizes=MODULE_SIZES, english=True, interact="zfs_scan"),
    RouteSpec("homelab-paperless", "/homelab/paperless", "Homelab: Paperless", sizes=MODULE_SIZES, english=True),
    RouteSpec("homelab-batterien", "/homelab/batterien", "Homelab: Home Assistant", sizes=MODULE_SIZES, english=True),
    RouteSpec("homelab-vault", "/homelab/vault", "Homelab: Obsidian-Vault", sizes=MODULE_SIZES, english=True,
              interact="vault_note"),
    RouteSpec("homelab-assets", "/homelab/assets", "Homelab: Assets", sizes=MODULE_SIZES, english=True),
    RouteSpec("homelab-kabel", "/homelab/kabel?tab=register", "Homelab: Kabel", sizes=MODULE_SIZES, english=True),
    RouteSpec("homelab-kleinanzeigen", "/homelab/kleinanzeigen", "Homelab: Kleinanzeigen", sizes=MODULE_SIZES,
              english=True),
    RouteSpec("homelab-sn-scan", "/homelab/sn-scan", "Homelab: Seriennummer-Scan", sizes=MODULE_SIZES, english=True),
)

ALL_ROUTES: tuple[RouteSpec, ...] = MAIN_ROUTES + EXTRA_ROUTES
TITLE_BY_KEY: dict[str, str] = {route.key: route.title for route in ALL_ROUTES}
MAIN_KEYS: frozenset[str] = frozenset(route.key for route in MAIN_ROUTES)

# Der Editor legt keinen `documents/_entwurf` mehr an (Entwürfe-API): jede 404 ist ein Befund.
EXPECTED_404_PATHS: tuple[str, ...] = ()


def _wanted(route: RouteSpec, lang: str, theme: str, size: str) -> bool:
    """Welche Kombinationen aufgenommen werden (siehe Moduldoku)."""
    main = route.key in MAIN_KEYS
    if size == "zoom200":
        return main and theme == "hell" and lang == "de"
    if lang != "de":
        return (main or route.english) and size == "desktop"
    return size in route.sizes


def shot_plan(routes: Sequence[RouteSpec], themes: Sequence[str], sizes: Sequence[str],
              langs: Sequence[str] = ("de",)) -> list[Shot]:
    """Alle (Route × Sprache × Thema × Größe)-Kombinationen, die `_wanted` zulässt."""
    plan: list[Shot] = []
    for route in routes:
        for lang in langs:
            for theme in themes:
                for size in sizes:
                    if not _wanted(route, lang, theme, size):
                        continue
                    viewport = route.viewport.get(size, DEFAULT_VIEWPORTS[size])
                    plan.append(Shot(
                        page=route.key, theme=theme, size=size, route=route.path,
                        viewport=viewport, full_page=(size != "handy" and route.full_page),
                        is_mobile=(size == "handy"),
                        device_scale_factor=DEVICE_SCALE[size], interact=route.interact,
                        token_key=route.token_key, lang=lang, drafts=route.drafts, modules=route.modules,
                    ))
    return plan


def shot_filename(shot: Shot) -> str:
    suffix = "" if shot.lang == "de" else f"-{shot.lang}"
    return f"{shot.page}-{shot.theme}-{shot.size}{suffix}.png"


def page_url(port: int, token: str, route: str) -> str:
    return f"http://127.0.0.1:{port}{route}#t={token}"


def shot_url(shot: Shot, port: int, session_token: str, info: dict) -> str:
    """URL einer Aufnahme: eigenes Token aus `info[shot.token_key]`, sonst das Sitzungs-Token."""
    token = info.get(shot.token_key) if shot.token_key else None
    route = shot.route.replace("{document}", _q(str(info.get("document", DOCUMENT_NAME))))
    return page_url(port, token or session_token, route)


DEMO_TOKENS_EN: tuple[tuple[str, str], ...] = (
    ("Office laptop", "admin"),
    ("Scripts", "drucken"),
    ("Kitchen phone", "familie"),
)
DEMO_TOKENS: tuple[tuple[str, str], ...] = (
    ("Laptop Büro", "admin"),
    ("Skripte", "drucken"),
    ("Handy Küche", "familie"),
)


def seed_access_demo(store: Any, lang: str = "de") -> dict:
    """Demo-Tokens je Rolle für die Seite Zugriff; liefert das Familien-Token für `/familie`.

    `store` ist ein `apitokens.TokenStore` im Temp-Home (nie das echte App-Verzeichnis).
    """
    info: dict = {}
    for name, role in (DEMO_TOKENS_EN if lang == "en" else DEMO_TOKENS):
        _token, secret = store.create(name, role)
        if role == "familie":
            info["family_token"] = secret
    return info


def is_expected_error(url: str, status: int) -> bool:
    """`True`, wenn diese Kombination aus API-Pfad und Status kein echter Rauchtest-Fehler ist."""
    path = urlsplit(url).path
    return status == 404 and path in EXPECTED_404_PATHS


OVERFLOW_TOLERANCE_PX = 1


def overflow_issue(shot: Shot, metrics: dict) -> "SmokeIssue | None":
    """Befund, wenn der Inhaltsbereich oder die Seite waagrecht überläuft (`metrics` aus MEASURE)."""
    main_sw, main_cw = int(metrics.get("main_sw", 0)), int(metrics.get("main_cw", 0))
    doc_sw, vw = int(metrics.get("doc_sw", 0)), int(metrics.get("vw", 0))
    over_main = main_cw > 0 and main_sw > main_cw + OVERFLOW_TOLERANCE_PX
    over_doc = vw > 0 and doc_sw > vw + OVERFLOW_TOLERANCE_PX
    if not (over_main or over_doc):
        return None
    detail = (f"waagrechter Überlauf [{shot.theme}/{shot.size}/{shot.lang}]: Inhalt {main_sw}/{main_cw} px, "
              f"Seite {doc_sw}/{vw} px")
    wide = [str(w) for w in metrics.get("wide") or []][:3]
    if wide:
        detail += f" ({', '.join(wide)})"
    return SmokeIssue(page=shot.page, kind="ueberlauf", detail=detail)


def axe_issues(shot: Shot, violations: Sequence[dict]) -> list["SmokeIssue"]:
    """axe-Verletzungen einer Aufnahme als Rauchtest-Befunde (je betroffenes Element einer)."""
    issues: list[SmokeIssue] = []
    where = f"{shot.theme}/{shot.size}/{shot.lang}"
    for violation in violations:
        rule = str(violation.get("id", "?"))
        help_text = str(violation.get("help", ""))
        for node in violation.get("nodes") or [{}]:
            target = " ".join(str(t) for t in (node.get("target") or ["?"]))
            summary = " ".join(str(node.get("failureSummary") or "").split())
            detail = f"{rule} [{where}] {target}: {help_text}"
            if summary:
                detail += f" ({summary})"
            issues.append(SmokeIssue(page=shot.page, kind="axe", detail=detail))
    return issues


def existing_shots(out_dir: Path, shots: Sequence[Shot]) -> list[Shot]:
    """Nur die Aufnahmen aus `shots`, deren Datei tatsächlich unter `out_dir` liegt.

    `main()` rief `write_index` früher immer mit dem GEPLANTEN Shot-Set auf, auch wenn eine
    Aufnahme scheiterte (z. B. weil ein Dialog nicht rechtzeitig erschien) und nie gespeichert
    wurde: `index.md` verlinkte dann ein PNG, das nicht existiert.
    """
    out_dir = Path(out_dir)
    return [shot for shot in shots if (out_dir / shot_filename(shot)).is_file()]


def index_shots(out_dir: Path) -> list[Shot]:
    """Alle Aufnahmen des vollständigen Plans, deren Datei in `out_dir` liegt (Reihenfolge des Plans).

    Grundlage für `index.md`: ein Teillauf (`--only`, `--themes`, `--sizes`, `--langs`) darf die
    Bilder der übrigen Seiten nicht aus dem Index werfen.
    """
    return existing_shots(out_dir, shot_plan(ALL_ROUTES, THEMES, SIZES, LANGS))


INDEX_SECTIONS: tuple[tuple[str, str], ...] = (
    ("de", "Deutsch (hell und dunkel, Desktop 1440 × 900 und Handy 390 × 844)"),
    ("en", "Englisch (Hauptseiten und Modulseiten, Desktop, hell und dunkel)"),
    ("zoom200", "200 % (720 × 450 bei doppelter Pixeldichte, hell, Deutsch)"),
)


def _section(shot: Shot) -> str:
    return "zoom200" if shot.size == "zoom200" else shot.lang


def write_index(out_dir: Path, shots: Sequence[Shot]) -> None:
    """`docs/screenshots/index.md`: je Abschnitt (Deutsch, Englisch, 200 %) je Seite die Bilder."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, dict[str, list[Shot]]] = {}
    for shot in shots:
        grouped.setdefault(_section(shot), {}).setdefault(shot.page, []).append(shot)

    lines = [
        "# Screenshots: Tapesmith Web-Oberfläche",
        "",
        "Aufgenommen von `tools/screenshots.py` gegen Demo-Daten (Datei-Transport, kein echtes "
        "Gerät, keine echten Nutzerdaten). Jede Aufnahme ist im echten Chromium mit axe-core "
        "geprüft (WCAG 2 A, AA und 2.1 AA, inklusive Farbkontrast).",
        "",
    ]
    for section, heading in INDEX_SECTIONS:
        pages = grouped.get(section)
        if not pages:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for key, page_shots in pages.items():
            title = TITLE_BY_KEY.get(key, key)
            lines.append(f"### {title}")
            lines.append("")
            for shot in page_shots:
                extra = "" if shot.lang == "de" else f", {shot.lang}"
                lines.append(f"![{title} ({shot.theme}, {shot.size}{extra})]({shot_filename(shot)})")
            lines.append("")
    (out_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Ab hier: der Browser-Lauf selbst (kein pytest, kein Import ohne Playwright nötig).
# ---------------------------------------------------------------------------

def _wait_ready(page: Any, timeout_s: float = READY_TIMEOUT_S) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_s * 1000)
    except Exception:  # noqa: BLE001 (lieber ein spätes Bild als ein abgebrochener Lauf)
        pass
    deadline = time.monotonic() + timeout_s
    selector = "[role='progressbar'], [class*='skeleton' i]"
    while time.monotonic() < deadline:
        try:
            count = page.eval_on_selector_all(selector, "els => els.length")
        except Exception:  # noqa: BLE001
            return
        if not count:
            break
        time.sleep(0.1)
    # networkidle und "keine Spinner mehr" sagen nichts darüber aus, ob die Seite auch tatsächlich
    # etwas gemalt hat: ein konkretes sichtbares Element abwarten, statt nur Abwesenheit von
    # Ladeanzeigen (siehe READY_SELECTOR). Absichtlich NICHT geschluckt: bleibt die Seite leer,
    # ist das ein echter Rauchtest-Fehler und soll die Aufnahme dieser Seite scheitern lassen,
    # statt ein einfarbiges Bild stillschweigend zu speichern.
    remaining_s = max(0.5, deadline - time.monotonic())
    page.wait_for_selector(READY_SELECTOR, timeout=remaining_s * 1000)


STRAY_OVERLAY_MIN_ZINDEX = 100_000
# Fluent UI v9 legt für jedes Tooltip/Menü/Dialog/Toast einen eigenen "Portal-Mount"-Container
# direkt unter <body> an (position:absolute, z-index:1000000, volle Viewportgröße). Der ist NUR
# als unsichtbarer Anker gedacht (das eigentliche Popup-Element darin bringt seinen eigenen
# Hintergrund mit), er erbt aber offenbar das `className` der äußersten <FluentProvider>
# (web/src/theme/ThemeProvider.tsx: backgroundColor auf tokens.colorNeutralBackground2) und wird
# dadurch selbst blickdicht. Da JEDE Seite über Sidebar/TopBar mehrere Tooltips im Baum hat,
# stapeln sich so mehrere blickdichte, viewportgroße Ebenen über der eigentlichen App, noch bevor
# überhaupt ein Tooltip/Menü geöffnet wurde: Screenshots zeigten nur noch diese Ebenen (=
# Hintergrundfarbe), obwohl `#root` darunter vollständig und korrekt gerendert war (mit
# `page.evaluate` nachgeprüft: Entfernt man NUR diese Container, zeigt der exakt gleiche Lauf
# hunderte statt einer Farbe). Die Ursache ist in web/src/theme/ThemeProvider.tsx behoben; das
# Werkzeug entfernt zusätzlich als Absicherung die (sonst blickdichte) Hintergrundfarbe dieser
# Container. Der Knoten selbst bleibt stehen, damit ein gerade geöffneter Dialog/Menü darin
# weiter sichtbar ist.


def _clear_stray_overlay_backgrounds(page: Any) -> None:
    page.evaluate(
        """
        (minZ) => {
          Array.from(document.body.children).forEach((el) => {
            if (el.id === 'root') return;
            const cs = getComputedStyle(el);
            if (cs.position === 'absolute' && parseInt(cs.zIndex || '0', 10) >= minZ) {
              el.style.setProperty('background', 'transparent', 'important');
              el.style.setProperty('background-color', 'transparent', 'important');
            }
          });
        }
        """,
        STRAY_OVERLAY_MIN_ZINDEX,
    )


def _ensure_painted(page: Any, viewport: tuple[int, int]) -> None:
    """Erzwingt vor jeder Aufnahme (nicht nur bei `interact`-Routen) ein echtes Eingabeereignis.

    Zusätzliche, robuste Absicherung dafür, dass die Seite tatsächlich einen aktuellen Frame
    gemalt hat (unabhängig von `_clear_stray_overlay_backgrounds`, das den eigentlich gefundenen
    Ursprung des Problems behebt): ein garantiertes Maus-/Fokusereignis vor jeder Aufnahme, nicht
    nur bei Routen mit `interact`.
    """
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001 (ein fehlendes bring_to_front darf den Lauf nicht stoppen)
        pass
    width, height = viewport
    x, y = max(1, min(width - 1, 10)), max(1, min(height - 1, 10))
    try:
        page.mouse.move(x, y)
        page.mouse.move(x + 1, y + 1)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(100)


def _select_one(page: Any, info: dict) -> None:
    """Wählt genau ein Objekt (das Textobjekt des Demo-Dokuments) über die Ebenen-Liste.

    Der Editor soll "mit einem ausgewählten Objekt" erscheinen: Strg+A wählte alle 4 Objekte
    und zeigte das Mehrfachauswahl-Panel. Die Ebenen-Liste
    (`LayersPanel.tsx`, `aria-label` = `objectTitle`, z. B. "Text (text1)") trifft das Objekt
    unabhängig von Zoom und Leinwand-Geometrie. In schmalen Layouts liegen die Reiter in einer
    Schublade, die danach wieder geschlossen wird, damit die Leinwand mit Auswahl sichtbar ist.
    Die Zeile hat keinen Tastaturfokus und ein echter Mausklick wird vom Fluent-Portal abgefangen
    (siehe `_activate`), darum wird das Klick-Ereignis direkt auf der Zeile ausgelöst.
    """
    names = EDITOR_LABELS[info.get("lang", "de")]
    page.wait_for_timeout(200)
    drawer = not page.get_by_role("tab", name=names["layers"]).is_visible()
    if drawer:
        _activate(page, page.get_by_role("button", name=names["panels"]))
        page.wait_for_timeout(300)
    _activate(page, page.get_by_role("tab", name=names["layers"]))
    page.wait_for_timeout(150)
    page.get_by_role("option", name=re.compile(rf"\({re.escape(SELECTED_OBJECT_ID)}\)$")).dispatch_event("click")
    page.wait_for_timeout(150)
    _activate(page, page.get_by_role("tab", name=names["props"]))
    page.wait_for_timeout(200)
    if drawer:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)


# Beschriftungen des Editors je Sprache (web/src/locales/<lng>/editor.json).
EDITOR_LABELS: dict[str, dict[str, str]] = {
    "de": {"layers": "Ebenen", "props": "Eigenschaften", "panels": "Eigenschaften und Ebenen", "open": "Öffnen"},
    "en": {"layers": "Layers", "props": "Properties", "panels": "Properties and layers", "open": "Open"},
}


def _shortcuts(page: Any, info: dict) -> None:
    """Öffnet die Tastenkürzel-Übersicht mit `?` (außerhalb von Eingabefeldern)."""
    page.evaluate("() => { const el = document.activeElement; if (el && el !== document.body) el.blur(); }")
    page.keyboard.press("?")
    page.wait_for_selector("[role='dialog']", timeout=5000)
    page.wait_for_timeout(300)


def _second_tab(page: Any, info: dict) -> None:
    """Öffnet im Editor ein zweites gespeichertes Dokument (neuer Tab) über „Öffnen“."""
    names = EDITOR_LABELS[info.get("lang", "de")]
    _activate(page, page.get_by_role("button", name=names["open"]).first)
    second = str(info.get("second_document", SECOND_DOCUMENT_NAME))
    row = page.get_by_role("row", name=re.compile(re.escape(second)))
    row.wait_for(timeout=5000)
    row.dispatch_event("dblclick")
    page.wait_for_selector(f"[role='tab'][aria-label*='{second}']", timeout=5000)
    # Der Fokus kehrt nach dem Dialog auf „Öffnen“ zurück; ohne Fokus verschwindet dessen Tooltip.
    page.evaluate("() => { const el = document.activeElement; if (el && el !== document.body) el.blur(); }")
    page.wait_for_timeout(400)


def _command_palette(page: Any, info: dict) -> None:
    page.keyboard.press("Control+k")
    page.wait_for_selector("[role='dialog'], [cmdk-root], input[placeholder*='Befehl' i]", timeout=3000)
    page.keyboard.type("ssd")
    page.wait_for_timeout(200)


def _activate(page: Any, locator: Any) -> None:
    """Aktiviert einen Button über die Tastatur (Fokus + Enter): ein Klick kann von einem
    (unsichtbaren) Portal-Wurzelelement abgefangen werden, das Fluent für Dialoge/Tooltips
    schon beim ersten Rendern anlegt; Tastaturaktivierung umgeht dieses Abfangen."""
    locator.focus()
    page.keyboard.press("Enter")


def _status_detail(page: Any, info: dict) -> None:
    _activate(page, page.locator("[data-testid='status-chip']"))
    page.wait_for_timeout(200)


def _batch_dialog(page: Any, info: dict) -> None:
    _activate(page, page.get_by_role("button", name="Serie/Import…"))
    table_field = page.get_by_label("Tabelle einfügen")
    table_field.fill("host,slot,sn\npmx10,SSD-2,112233274914\npmx10,SSD-3,112233274915\n")
    page.wait_for_timeout(400)


def _open_more_options(page: Any) -> None:
    """Öffnet die eingeklappte Optionsfläche (Kopien, Kette, Schnittmarken).

    Diese Felder liegen in `Schnelldruck/index.tsx` unter dem Umschalter "Mehr Optionen"
    (`optionsOpen`, Standard `false`): geschlossen hat die Fläche `grid-template-rows: 0fr` und
    `opacity: 0`. `get_by_label("Kopien")` fand das Feld zwar im DOM, aber nie sichtbar/stabil,
    darum lief `_confirm_dialog` bisher zuverlässig in den Fill-Timeout, bevor der Rückfrage-Dialog
    je erschien (`ruecksprache-drucken` wurde so nie gespeichert).
    """
    button = page.get_by_role("button", name="Mehr Optionen")
    if button.get_attribute("aria-expanded") == "true":
        return
    _activate(page, button)
    page.wait_for_timeout(250)  # CSS-Übergang der Optionsfläche (durationSlow)


def _confirm_dialog(page: Any, info: dict) -> None:
    page.get_by_placeholder("Text eingeben, Enter druckt").fill("Serie-Test Rückfrage")
    _open_more_options(page)
    copies = page.get_by_label("Kopien")
    copies.fill("6")
    page.keyboard.press("Tab")
    _activate(page, page.get_by_role("button", name=re.compile(r"^Drucken")).first)
    page.wait_for_selector("text=Wirklich drucken?", timeout=10000)
    page.wait_for_timeout(200)


# Beschriftungen der Knöpfe, die eine Liste laden (web/src/locales/<lng>/*.json).
LOAD_LABELS: dict[str, dict[str, str]] = {
    "de": {"scan": "Scannen", "load": "Laden"},
    "en": {"scan": "Scan", "load": "Load"},
}


def _click_and_wait(page: Any, name: str, wait_selector: str) -> None:
    _activate(page, page.get_by_role("button", name=name, exact=True).first)
    page.wait_for_selector(wait_selector, timeout=10000)
    page.wait_for_timeout(300)


def _ssh_scan(page: Any, info: dict) -> None:
    """Datenträger, Reiter SSH: Host scannen (Antwort aus `tools.demo_services`)."""
    _click_and_wait(page, LOAD_LABELS[info.get("lang", "de")]["scan"], "table, ul[aria-label]")


def _zfs_scan(page: Any, info: dict) -> None:
    """Datenträger, Reiter Plattentausch: Host scannen, die defekte Platte auswählen."""
    _click_and_wait(page, LOAD_LABELS[info.get("lang", "de")]["scan"], "input[name='old-device']")
    page.locator("input[name='old-device']").first.check()
    page.wait_for_timeout(200)


def _proxmox_load(page: Any, info: dict) -> None:
    """Proxmox: Gäste laden."""
    _click_and_wait(page, LOAD_LABELS[info.get("lang", "de")]["load"], "table, ul[aria-label]")


def _vault_note(page: Any, info: dict) -> None:
    """Obsidian-Vault: die erste Notiz öffnen."""
    _activate(page, page.get_by_role("button", name="Hosts/pmx10.md"))
    page.wait_for_selector("table", timeout=10000)
    page.wait_for_timeout(300)


INTERACTIONS: dict[str, Callable[[Any, dict], None]] = {
    "select_one": _select_one,
    "command_palette": _command_palette,
    "status_detail": _status_detail,
    "batch_dialog": _batch_dialog,
    "confirm_dialog": _confirm_dialog,
    "shortcuts": _shortcuts,
    "second_tab": _second_tab,
    "ssh_scan": _ssh_scan,
    "zfs_scan": _zfs_scan,
    "proxmox_load": _proxmox_load,
    "vault_note": _vault_note,
}


def _serve_demo_services(route: Any) -> None:
    """Antwortet auf Anfragen an externe Dienste mit Demo-Daten (`tools.demo_services`)."""
    request = route.request
    parts = urlsplit(request.url)
    body = demo_response(request.method, parts.path, parts.query)
    if body is None:
        route.continue_()
        return
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


@dataclass
class SmokeIssue:
    page: str
    kind: str
    detail: str


# Fluent (Tabster) legt unsichtbare Fokus-Wächter `<i tabindex="0" aria-hidden="true" data-tabster-dummy>`
# an, die den Fokus in Dialogen, Listen und der Seitenleiste lenken. Neuere axe-core-Versionen melden sie
# als `aria-hidden-focus`; sie sind kein Inhalt der Seite und werden deshalb nicht mitgeprüft.
AXE_EXCLUDE = "[data-tabster-dummy]"

AXE_RUN = """
async ([tags, exclude]) => {
  const context = { include: [['html']], exclude: [[exclude]] };
  const result = await window.axe.run(context, { runOnly: { type: 'tag', values: tags } });
  return result.violations.map((v) => ({
    id: v.id,
    help: v.help,
    nodes: v.nodes.map((n) => ({ target: n.target, failureSummary: n.failureSummary })),
  }));
}
"""


MEASURE = """
() => {
  const main = document.getElementById('inhalt');
  const vw = window.innerWidth;
  const limit = main ? main.getBoundingClientRect().right : vw;
  const wide = [];
  for (const el of (main || document.body).querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > limit + 1) {
      const cls = typeof el.className === 'string' ? el.className.split(' ')[0] : '';
      wide.push(`${el.tagName.toLowerCase()}${cls ? '.' + cls : ''} bis ${Math.round(r.right)} px`);
      if (wide.length >= 3) break;
    }
  }
  return { main_sw: main ? main.scrollWidth : 0, main_cw: main ? main.clientWidth : 0,
           doc_sw: document.documentElement.scrollWidth, vw, wide };
}
"""


def _run_axe(page: Any) -> list[dict]:
    """axe-core in die Seite laden und mit den WCAG-Regeln (inklusive Kontrast) prüfen."""
    page.add_script_tag(path=str(AXE_SCRIPT))
    return page.evaluate(AXE_RUN, [list(AXE_TAGS), AXE_EXCLUDE])


def _prepare_drafts(home: Path, shot: Shot) -> None:
    """Vor jeder Aufnahme: Entwürfe leeren (Autosave früherer Aufnahmen darf keinen
    Wiederherstellungs-Hinweis auslösen), für `drafts="verwaist"` verwaiste Demo-Entwürfe anlegen."""
    reset_drafts(home)
    if shot.drafts == "verwaist":
        seed_orphaned_drafts(home)


def set_demo_modules(enabled: Sequence[str] | None) -> None:
    """Schaltet im Demo-Home die Module für eine Aufnahme (None: alle, wie `seed_demo`). Der Dienst
    liest config.json bei jeder Anfrage, die Änderung wirkt also sofort."""
    from tapesmith import config as config_mod
    from tapesmith import modules as modules_mod

    ids = modules_mod.MODULE_IDS if enabled is None else tuple(enabled)
    config_mod.save_config({"modules": {"enabled": list(ids)}})


def _capture(playwright_mod: Any, plan: Sequence[Shot], port: int, token: str, out_dir: Path,
            info: dict, home: Path | None = None, axe: bool = True) -> list[SmokeIssue]:
    issues: list[SmokeIssue] = []
    browser = playwright_mod.chromium.launch()
    try:
        for shot in plan:
            os.environ["TAPESMITH_SYSTEM_LANG"] = shot.lang
            if home is not None:
                _prepare_drafts(home, shot)
                set_demo_modules(shot.modules)
            width, height = shot.viewport
            context = browser.new_context(
                viewport={"width": width, "height": height},
                color_scheme="dark" if shot.theme == "dunkel" else "light",
                reduced_motion="reduce",
                locale=BROWSER_LOCALES.get(shot.lang, "de-DE"),
                timezone_id="Europe/Berlin",
                device_scale_factor=shot.device_scale_factor,
                is_mobile=shot.is_mobile,
                has_touch=shot.is_mobile,
            )
            page = context.new_page()
            page.route(INTERCEPT_PATTERN, _serve_demo_services)
            shot_errors: list[str] = []

            def on_console(msg, _shot=shot, _errs=shot_errors):
                if msg.type == "error":
                    _errs.append(f"console: {msg.text}")

            def on_pageerror(exc, _shot=shot, _errs=shot_errors):
                _errs.append(f"pageerror: {exc}")

            def on_response(response, _shot=shot, _errs=shot_errors):
                url = response.url
                if "/api/" not in urlsplit(url).path:
                    return
                status = response.status
                if status >= 400 and not is_expected_error(url, status):
                    _errs.append(f"api {status}: {url}")

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("response", on_response)

            violations: list[dict] = []
            metrics: dict = {}
            try:
                page.goto(shot_url(shot, port, token, info), wait_until="load")
                _wait_ready(page)
                if shot.interact:
                    INTERACTIONS[shot.interact](page, {**info, "lang": shot.lang})
                    _wait_ready(page)
                _clear_stray_overlay_backgrounds(page)
                _ensure_painted(page, shot.viewport)
                page.screenshot(path=str(out_dir / shot_filename(shot)), full_page=shot.full_page)
                metrics = page.evaluate(MEASURE)
                if axe:
                    violations = _run_axe(page)
            except Exception as exc:  # noqa: BLE001 (eine Seite darf den restlichen Lauf nicht stoppen)
                shot_errors.append(f"aufnahme fehlgeschlagen: {exc}")
            finally:
                context.close()

            kind = f"{shot.theme}/{shot.size}/{shot.lang}"
            for text in shot_errors:
                issues.append(SmokeIssue(page=shot.page, kind=kind, detail=text))
            issues.extend(axe_issues(shot, violations))
            overflow = overflow_issue(shot, metrics) if metrics else None
            if overflow is not None:
                issues.append(overflow)
    finally:
        browser.close()
    return issues


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/screenshots")
    parser.add_argument("--only", default=None, help="Kommagetrennte Seiten-Schlüssel (z. B. schnelldruck,editor)")
    parser.add_argument("--themes", default=None, help="Kommagetrennt, Standard: hell,dunkel")
    parser.add_argument("--sizes", default=None, help="Kommagetrennt, Standard: desktop,handy,zoom200")
    parser.add_argument("--langs", default=None, help="Kommagetrennt, Standard: de,en")
    parser.add_argument("--no-axe", action="store_true", help="axe-Prüfung auslassen (nur zur Fehlersuche)")
    parser.add_argument("--keep-home", action="store_true", help="Demo-Home nach dem Lauf behalten")
    parser.add_argument("--home", default=DEMO_HOME,
                        help="Demo-Datenordner (Standard C:\\Tapesmith-Demo): neutraler Pfad, damit kein "
                             "Benutzername in den Aufnahmen erscheint")
    return parser.parse_args(argv)


DEMO_HOSTNAME = "DEMO-PC"
DEMO_ADDRESSES = ("192.0.2.10",)


def _neutral_network_identity() -> None:
    """Rechnername und LAN-Adressen des aufnehmenden PCs dürfen nie in Screenshots erscheinen:
    für den Lauf feste Demo-Werte (Dokumentationsnetz 192.0.2.0/24) statt der echten."""
    import socket

    from tapesmith import netinfo

    socket.gethostname = lambda: DEMO_HOSTNAME
    netinfo.local_ipv4_addresses = lambda *a, **k: list(DEMO_ADDRESSES)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    themes = args.themes.split(",") if args.themes else list(THEMES)
    sizes = args.sizes.split(",") if args.sizes else list(SIZES)
    langs = args.langs.split(",") if args.langs else list(LANGS)
    unknown_dims = [x for x in themes if x not in THEMES] + [x for x in sizes if x not in SIZES] + \
        [x for x in langs if x not in LANGS]
    if unknown_dims:
        print(f"Unbekannte Werte: {', '.join(unknown_dims)}", file=sys.stderr)
        return 1
    if not args.no_axe and not AXE_SCRIPT.is_file():
        print(f"axe-core fehlt ({AXE_SCRIPT}): im Ordner web zuerst 'npm ci' ausführen.", file=sys.stderr)
        return 1
    routes = ALL_ROUTES
    if args.only:
        wanted = set(args.only.split(","))
        routes = tuple(r for r in ALL_ROUTES if r.key in wanted)
        unknown = wanted - {r.key for r in ALL_ROUTES}
        if unknown:
            print(f"Unbekannte Seiten in --only: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1

    plan = shot_plan(routes, themes, sizes, langs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        home = prepare_demo_home(Path(args.home))
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    os.environ["TAPESMITH_HOME"] = str(home)
    os.environ["TAPESMITH_WEB_PORT"] = "0"
    os.environ["TAPESMITH_NO_DAEMON"] = "1"
    os.environ.setdefault("TAPESMITH_LOCK_NAME", f"Local\\Tapesmith.Screens.{os.getpid()}")
    _neutral_network_identity()

    # Demo-Inhalte in der Sprache des Laufs: bei nur einer Sprache (z. B. `--langs en`) in dieser,
    # sonst Deutsch. Die Sprache des Dienstes folgt je Aufnahme der Sprache der Aufnahme
    # (`TAPESMITH_SYSTEM_LANG`, wie ein Windows in dieser Sprache).
    demo_lang = langs[0] if len(set(langs)) == 1 else "de"
    info = seed_demo(home, now=datetime.now(), lang=demo_lang)
    from tapesmith.apitokens import TokenStore
    info.update(seed_access_demo(TokenStore(home / "access" / "tokens.json"), lang=demo_lang))

    try:
        import playwright.sync_api as sync_api
    except ImportError:
        print("Playwright fehlt: .venv\\Scripts\\python -m pip install playwright "
             "&& .venv\\Scripts\\python -m playwright install chromium", file=sys.stderr)
        return 1

    from tapesmith.daemon.service import PrintService
    from tapesmith.ipc import pipe
    from tapesmith.webapi.server import WebServer

    service = PrintService()
    server = WebServer(service, port=0, home_key=pipe.home_key())
    issues: list[SmokeIssue] = []
    try:
        server.start()
        assert server.ctx is not None
        server.ctx.accent_reader = lambda: "#0078d4"
        # Karte „Updates“ wie in der installierten App, mit Versionsauswahl, ohne Netz
        from tools.demo_services import DemoUpdateService

        server.ctx.extras["update_service"] = DemoUpdateService()
        with sync_api.sync_playwright() as playwright_mod:
            issues = _capture(playwright_mod, plan, server.port, server.token, out_dir, info, home=home,
                              axe=not args.no_axe)
    finally:
        server.stop()
        service.close()
        if not args.keep_home:
            shutil.rmtree(home, ignore_errors=True)

    # NIE mit dem geplanten Shot-Set aufrufen: schlägt eine Aufnahme fehl (Timeout, Dialog nie
    # erschienen, ...), wird ihre Datei nie geschrieben, und `index.md` darf trotzdem nur auf
    # tatsächlich vorhandene Bilder verlinken. Der Index umfasst alle
    # vorhandenen Bilder, nicht nur die dieses (evtl. Teil-)Laufs.
    saved = existing_shots(out_dir, plan)
    write_index(out_dir, index_shots(out_dir))

    missing = [shot for shot in plan if shot not in saved]
    print(f"\n{len(saved)} von {len(plan)} geplanten Aufnahmen nach {out_dir} geschrieben.")
    if missing:
        print(f"Nicht gespeichert ({len(missing)}), fehlen daher in index.md:")
        for shot in missing:
            print(f"  * {shot_filename(shot)}")
    if issues:
        print(f"Rauchtest: {len(issues)} Auffälligkeit(en):")
        for issue in issues:
            print(f"  * {issue.page} ({issue.kind}): {issue.detail}")
    else:
        print("Rauchtest: keine Konsolenfehler, keine fehlgeschlagenen /api/-Aufrufe, keine axe-Befunde, "
              "kein waagrechter Überlauf.")
    return 1 if issues or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
