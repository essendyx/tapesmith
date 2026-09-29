"""Module: eingebaute Funktionsbereiche, die sich einzeln einschalten lassen (Standard aus).

Die Kernapp (Schnelldruck, Editor, Galerie, Vorlagen, QR-Code, Verlauf, Warteschlange, Statistik,
Zugriff, Einstellungen) ist immer da. Alles Weitere ist ein Modul, beschrieben in `REGISTRY`: Seiten,
Menüeintrag, API-Pfade, CLI-Befehle, eigene Vorlagen, Einstellungskarten und benötigte Dienste. Die
Texte (Name, Erklärsatz, Beispiel, Voraussetzung) stehen in den Sprachkatalogen
`tapesmith/locales/<sprache>/modules.json`.

Eingeschaltet sind die Module aus `modules.enabled` in config.json (Liste von Kennungen). Fehlt der
Abschnitt ganz (ältere Konfiguration, etwa nach der Übernahme aus "P12 Label"), gelten die Module als
eingeschaltet, zu denen Daten oder Einstellungen vorhanden sind (`detect_used_modules`); der
Druckdienst schreibt diese Liste beim Start einmal fest (`persist_detected_if_missing`).

Die Web-Oberfläche liest dieselbe Beschreibung aus `web/src/modules/registry.json`, erzeugt mit
`python -m tapesmith.modules --write-web` (ein Test prüft, dass die Datei aktuell ist).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tapesmith import i18n
from tapesmith.i18n import _t

API_PREFIX = "/api/v1"


@dataclass(frozen=True)
class ModuleSpec:
    """Ein Modul. `kind`: `werkzeug` (eigene Seite in der Seitenleiste) oder `integration` (Kachel
    in der Homelab-Übersicht). `nav`: `sidebar:<routen-schlüssel>` bzw. `homelab:<unterseite>`.
    `api`: Pfadpräfixe ohne `/api/v1` (ein Pfad gehört zu jedem Modul, dessen Präfix passt).
    `settings`: Einstellungskarten (`config:<abschnitt>` in config.json, `homelab:<abschnitt>` in
    homelab.json). `integrations`: benötigte Dienste (Kennungen wie in `/homelab/check`). `setup`: die
    Seite braucht einen eingerichteten Dienst (sonst zeigt sie den Weg zu den Einstellungen)."""

    id: str
    kind: str
    pages: tuple[str, ...]
    nav: str
    api: tuple[str, ...]
    cli: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    settings: tuple[str, ...] = ()
    integrations: tuple[str, ...] = ()
    icon: str = ""
    setup: bool = False


REGISTRY: tuple[ModuleSpec, ...] = (
    ModuleSpec("inventar", "werkzeug", ("/inventar",), "sidebar:inventar", ("/inventory",),
               cli=("inv",), templates=("aufbewahrungsbox",), icon="box"),
    ModuleSpec("datentraeger", "werkzeug", ("/datentraeger",), "sidebar:datentraeger",
               ("/drives", "/ssh", "/homelab/zfs"),
               cli=("drives", "disks", "platte"),
               templates=("datentraeger", "datentraeger-qr", "platte-defekt"), categories=("Datenträger",),
               settings=("config:ssh",), icon="hard-drive"),
    ModuleSpec("proxmox", "integration", ("/homelab/proxmox",), "homelab:proxmox", ("/homelab/proxmox",),
               cli=("proxmox",), templates=("vm-lxc", "vm-lxc-qr"), settings=("homelab:proxmox",),
               integrations=("proxmox",), icon="server", setup=True),
    ModuleSpec("paperless", "integration", ("/homelab/paperless",), "homelab:paperless",
               ("/homelab/paperless",), cli=("asn", "garantie"), templates=("asn", "garantie", "garantie-qr"),
               settings=("homelab:paperless",), integrations=("paperless",), icon="document", setup=True),
    ModuleSpec("homeassistant", "integration", ("/homelab/batterien",), "homelab:batterien", ("/homelab/ha",),
               cli=("batterie",), templates=("batterie",), settings=("homelab:homeassistant",),
               integrations=("homeassistant",), icon="battery", setup=True),
    ModuleSpec("vault", "integration", ("/homelab/vault",), "homelab:vault",
               ("/homelab/vault", "/homelab/assets/{asset_id}/vault-note"),
               cli=("vault", "asset-notiz"), settings=("homelab:obsidian",), integrations=("obsidian",),
               icon="notebook", setup=True),
    ModuleSpec("assets", "integration", ("/homelab/assets",), "homelab:assets", ("/homelab/assets",),
               cli=("asset", "kurz"), templates=("asset-tag", "asset-kurz"),
               settings=("homelab:assets", "homelab:shortlink"), integrations=("shortlink",), icon="tag"),
    ModuleSpec("kabel", "integration", ("/homelab/kabel",), "homelab:kabel", ("/homelab/kabel",),
               cli=("kabel",), settings=("homelab:kabel",), icon="plug"),
    ModuleSpec("kleinanzeigen", "integration", ("/homelab/kleinanzeigen",), "homelab:kleinanzeigen",
               ("/homelab/ka",), cli=("ka",), templates=("ka-artikel",), settings=("homelab:kleinanzeigen",),
               icon="cart"),
    ModuleSpec("snscan", "integration", ("/homelab/sn-scan",), "homelab:sn-scan", ("/homelab/codescan",),
               cli=("sn-scan",), icon="scan"),
)

MODULE_IDS: tuple[str, ...] = tuple(spec.id for spec in REGISTRY)
_BY_ID: dict[str, ModuleSpec] = {spec.id: spec for spec in REGISTRY}


class UnknownModule(KeyError):
    """Kennung gehört zu keinem Modul."""

    def __str__(self) -> str:
        known = ", ".join(MODULE_IDS)
        return _t("Unbekanntes Modul '{value}'. Bekannt: {known}", value=self.args[0], known=known)


class ModuleDisabled(Exception):
    """Aufruf einer Funktion eines ausgeschalteten Moduls (Fehlercode `module.disabled`, HTTP 409)."""

    code = "module.disabled"
    http_status = 409

    def __init__(self, module_id: str, lang: str | None = None):
        lang = lang or i18n.language()
        self.module_id = module_id
        self.name = texts(module_id, lang)["name"] if module_id in _BY_ID else module_id
        super().__init__(i18n.tr("modules.disabled", lang, name=self.name, id=module_id))
        self.hint = i18n.tr("errors.module.disabled.hint", lang)


def spec(module_id: str) -> ModuleSpec:
    try:
        return _BY_ID[module_id]
    except KeyError:
        raise UnknownModule(module_id) from None


def texts(module_id: str, lang: str | None = None) -> dict[str, str]:
    """Name, Erklärsatz, Beispiel und (falls vorhanden) Voraussetzung eines Moduls (Sprache: `lang`,
    sonst die der Anfrage)."""
    spec(module_id)
    lang = lang or i18n.language()
    out = {key: i18n.tr(f"modules.{module_id}.{key}", lang) for key in ("name", "description", "example")}
    requires = i18n.tr(f"modules.{module_id}.requires", lang)
    if requires != f"modules.{module_id}.requires":
        out["requires"] = requires
    return out


# ---------- eingeschaltete Module ----------

def _explicit(cfg: Mapping) -> list[str] | None:
    section = cfg.get("modules") if isinstance(cfg, Mapping) else None
    if not isinstance(section, Mapping):
        return None
    value = section.get("enabled", [])
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _ordered(ids: Iterable[str]) -> tuple[str, ...]:
    wanted = set(ids)
    return tuple(module_id for module_id in MODULE_IDS if module_id in wanted)


def implicit_enabled() -> tuple[str, ...]:
    """Module, die ohne gespeicherte Liste gelten: die mit vorhandenen Daten im Datenordner."""
    from tapesmith import paths

    return detect_used_modules(paths.app_dir())


def enabled_ids(cfg: Mapping) -> tuple[str, ...]:
    """Eingeschaltete Module in Register-Reihenfolge; unbekannte Kennungen fallen weg."""
    explicit = _explicit(cfg)
    if explicit is None:
        return _ordered(implicit_enabled())
    return _ordered(explicit)


def is_enabled(cfg: Mapping, module_id: str) -> bool:
    return module_id in enabled_ids(cfg)


def require(cfg: Mapping, module_id: str) -> None:
    """`ModuleDisabled`, wenn `module_id` ausgeschaltet ist."""
    if not is_enabled(cfg, module_id):
        raise ModuleDisabled(module_id)


def set_enabled(module_id: str, enabled: bool) -> tuple[str, ...]:
    """Schaltet ein Modul ein oder aus und speichert die vollständige Liste in config.json."""
    from tapesmith import config

    spec(module_id)
    current = set(enabled_ids(config.load_config()))
    if enabled:
        current.add(module_id)
    else:
        current.discard(module_id)
    ordered = _ordered(current)
    config.set_setting("modules.enabled", list(ordered))
    return ordered


def persist_detected_if_missing() -> tuple[str, ...] | None:
    """Fehlt `modules` in config.json, die erkannte Liste einmal festschreiben (Druckdienst-Start).
    Rückgabe: die geschriebene Liste oder None (nichts zu tun, keine config.json)."""
    from tapesmith import config, paths

    path = paths.config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "modules" in data:
        return None
    detected = _ordered(implicit_enabled())
    config.save_config({"modules": {"enabled": list(detected)}})
    return detected


# ---------- Zuordnung von Routen, Befehlen, Vorlagen ----------

def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def modules_for_api(path: str) -> tuple[str, ...]:
    """Module, zu denen ein API-Pfad (mit `/api/v1`, gern als Routenmuster mit `{param}`) gehört.
    Leer: Kernfunktion."""
    if not _matches(path, API_PREFIX):
        return ()
    rest = path[len(API_PREFIX):]
    return tuple(spec.id for spec in REGISTRY if any(_matches(rest, prefix) for prefix in spec.api))


def module_for_cli(command: str) -> str | None:
    for item in REGISTRY:
        if command in item.cli:
            return item.id
    return None


def module_of_template(name: str) -> str | None:
    for item in REGISTRY:
        if name in item.templates:
            return item.id
    return None


def hidden_templates(cfg: Mapping) -> frozenset[str]:
    """Namen der Vorlagen ausgeschalteter Module (in Galerie, Vorlagenliste und Tray ausgeblendet)."""
    enabled = set(enabled_ids(cfg))
    return frozenset(name for item in REGISTRY if item.id not in enabled for name in item.templates)


# ---------- Erkennung benutzter Module (Übernahme, ältere Konfiguration) ----------

def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(_t("{name}: kein JSON-Objekt", name=path.name))
    return data


def _rows(db: Path, tables: Iterable[str]) -> int:
    """Summe der Zeilen in `tables` (fehlende Tabellen zählen 0). Nur lesend geöffnet."""
    if not db.is_file():
        return 0
    uri = f"{db.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        total = 0
        for table in tables:
            try:
                total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            except sqlite3.OperationalError:
                continue
        return total
    finally:
        conn.close()


def _printed_templates(db: Path) -> set[str]:
    if not db.is_file():
        return set()
    uri = f"{db.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        try:
            rows = conn.execute("SELECT DISTINCT template FROM jobs WHERE template IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(row[0]) for row in rows}
    finally:
        conn.close()


def _section(data: dict, name: str) -> dict:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _detect(home: Path) -> set[str]:
    home = Path(home)
    cfg = _read_json(home / "config.json")
    homelab = _read_json(home / "homelab.json")
    data = home / "homelab"
    found: set[str] = set()

    printed = _printed_templates(home / "history.sqlite3")
    for item in REGISTRY:
        if printed & set(item.templates):
            found.add(item.id)

    if _rows(home / "inventory.sqlite3", ("boxes", "items", "loans")):
        found.add("inventar")
    ssh = _section(cfg, "ssh")
    scans = data / "scans"
    if ssh.get("hosts") or (scans.is_dir() and any(scans.glob("*.json"))):
        found.add("datentraeger")
    if _section(homelab, "proxmox").get("hosts"):
        found.add("proxmox")
    if _section(homelab, "paperless").get("url"):
        found.add("paperless")
    if _section(homelab, "homeassistant").get("url"):
        found.add("homeassistant")
    obsidian = _section(homelab, "obsidian")
    if obsidian.get("mcp_url") or obsidian.get("vault_dir"):
        found.add("vault")
    if _rows(data / "assets.sqlite3", ("assets",)) or _section(homelab, "shortlink").get("base_url"):
        found.add("assets")
    if _read_json(data / "kabel.json"):
        found.add("kabel")
    if _rows(data / "kleinanzeigen.sqlite3", ("artikel",)):
        found.add("kleinanzeigen")
    # Der Seriennummer-Scan hinterlässt keine eigenen Daten: er gehört zu den Homelab-Werkzeugen, mit
    # denen er gemeinsam genutzt wird (Datenträger, Assets, Proxmox).
    if found & {"datentraeger", "assets", "proxmox"}:
        found.add("snscan")
    return found


def detect_used_modules(home: Path) -> tuple[str, ...]:
    """Module, zu denen im Datenordner `home` Daten oder Einstellungen liegen. Im Zweifel (eine
    Datei ist nicht lesbar) alle Module, damit bei einer Übernahme nichts verloren geht."""
    try:
        return _ordered(_detect(home))
    except (OSError, ValueError, sqlite3.Error):
        return MODULE_IDS


# ---------- Beschreibung für die Web-Oberfläche ----------

def _nav_json(nav: str) -> dict:
    area, _, key = nav.partition(":")
    return {"area": area, "key": key}


def entry_json(item: ModuleSpec) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "icon": item.icon,
        "pages": list(item.pages),
        "nav": _nav_json(item.nav),
        "api": list(item.api),
        "cli": list(item.cli),
        "templates": list(item.templates),
        "categories": list(item.categories),
        "settings": list(item.settings),
        "integrations": list(item.integrations),
        "setup": item.setup,
        "texts": {lang: texts(item.id, lang) for lang in i18n.LANGUAGES},
    }


def registry_json() -> dict:
    """Die vollständige Modulbeschreibung (Grundlage für `/api/v1/modules` und die Web-Oberfläche)."""
    return {"modules": [entry_json(item) for item in REGISTRY]}


def registry_json_text() -> str:
    return json.dumps(registry_json(), ensure_ascii=False, indent=2) + "\n"


def web_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "web" / "src" / "modules" / "registry.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tapesmith.modules",
                                     description=_t("Modulbeschreibung für die Web-Oberfläche ausgeben"))
    parser.add_argument("--write-web", action="store_true", help=_t("web/src/modules/registry.json schreiben"))
    args = parser.parse_args(argv)
    text = registry_json_text()
    if args.write_web:
        target = web_registry_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"geschrieben: {target}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
