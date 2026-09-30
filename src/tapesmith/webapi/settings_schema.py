"""Einstellungsschema der Web-Oberfläche: Abschnitte, Felder, Feldprüfung, Anwenden.

`SECTIONS` beschreibt die Einstellungsseite vollständig (Beschriftung, Typ, Grenzen, Auswahl,
Einheit, Hilfetext, `restart`, `experimental`, `nullable`) und ordnet jedes Feld ein
(`visibility`): `sichtbar` (auf der Seite), `erweitert` (eingeklappter Abschnitt "Erweitert" am
Seitenende) oder `config` (nur in config.json, dokumentiert im Handbuch; bleibt über
`PATCH /settings` setzbar). Abschnitte mit `module` erscheinen nur, wenn das Modul eingeschaltet ist.

`settings_json` liest daraus den wirksamen Wert (`config.setting`, für `guard.*` die Defaults aus
`guard.GuardPolicy`) und baut die Antwort für `GET /settings` (ohne `config`-Felder).
`apply_changes` prüft eine `PATCH /settings`-Anfrage vollständig, bevor irgendetwas gespeichert
wird: unbekannter Schlüssel oder ungültiger Wert speichert nichts.

`gui.editor_grid_mm` ist ein abgeleitetes Feld: angezeigt in mm, gespeichert wie bisher als
`gui.editor_grid_dots` (8 Druckpunkte je mm).
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from typing import Any

from tapesmith import config, modules, paths
from tapesmith import guard as guard_mod
from tapesmith.hotkeyspec import LayoutProbe, WinLayoutProbe, altgr_conflict, format_hotkey, parse_hotkey
from tapesmith.i18n import N_, _t

Choice = tuple[Any, str]

VISIBLE, ADVANCED, CONFIG = "sichtbar", "erweitert", "config"
VISIBILITIES = (VISIBLE, ADVANCED, CONFIG)

# Einheiten im Eingabefeld (Anzeigetext übersetzt die Oberfläche).
UNITS = ("s", "min", "h", "mm", "kopien", "sicherungen", "prozent", "stellen")

# Druckauflösung des P12 (203 dpi): 8 Druckpunkte je mm. Grundlage der Rasterweite in mm.
DOTS_PER_MM = 8
GRID_MM_KEY = "gui.editor_grid_mm"
GRID_DOTS_KEY = "gui.editor_grid_dots"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[Choice, ...] | None = None
    help: str = ""
    restart: bool = False
    experimental: bool = False
    nullable: bool = False
    visibility: str = VISIBLE
    unit: str | None = None


@dataclass(frozen=True)
class SectionSpec:
    id: str
    title: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)
    module: str | None = None


# Auswahllisten (PROBE_CHOICES, CUT_PAUSE_CHOICES) wie in der früheren Qt-Einstellungsseite,
# hier Qt-frei angelegt.
PROBE_CHOICES: tuple[Choice, ...] = (
    ("auto", N_("automatisch")), ("ble", N_("BLE-Advertisement")), ("connect", N_("Verbindungsversuch")),
    ("off", N_("aus")),
)
CUT_PAUSE_CHOICES: tuple[Choice, ...] = (
    (None, N_("keine")), (0, N_("bis „Weiter“")), (5, N_("5 s")), (10, N_("10 s")), (30, N_("30 s")),
)
LANGUAGE_CHOICES: tuple[Choice, ...] = (
    ("auto", N_("wie Windows")), ("de", N_("Deutsch")), ("en", N_("English")),
)
THEME_CHOICES: tuple[Choice, ...] = (("system", N_("wie Windows")), ("hell", N_("Hell")), ("dunkel", N_("Dunkel")))
UPDATE_CHANNEL_CHOICES: tuple[Choice, ...] = (("stable", N_("Stabil")), ("beta", N_("Beta")))


SECTIONS: tuple[SectionSpec, ...] = (
    # Status, Suchen und testen, Testlabel stehen in einer eigenen Karte der Oberfläche.
    SectionSpec("verbindung", N_("Drucker"), (
        FieldSpec("transport", N_("Transport"), "choice", visibility=ADVANCED,
                 help=N_("Wie Tapesmith den Drucker anspricht: auto (empfohlen), COM-Port, ble oder usb")),
        FieldSpec("mac", N_("MAC-Adresse"), "string", nullable=True, visibility=ADVANCED,
                 help=N_("Bluetooth-Adresse des Druckers; leer = der einzige gekoppelte Drucker")),
        FieldSpec("connect_timeout_s", N_("Verbindungs-Zeitlimit"), "float", min=0.5, max=60, visibility=CONFIG,
                 unit="s"),
        FieldSpec("idle_timeout_s", N_("Trennen nach Ruhe"), "int", min=0, max=3600, visibility=CONFIG, unit="s",
                 help=N_("0 = sofort nach dem Druck trennen")),
    )),
    SectionSpec("drucken", N_("Drucken"), (
        FieldSpec("gui.ctrl_enter_only", N_("Nur Strg+Enter druckt"), "bool",
                 help=N_("Enter setzt dann eine neue Zeile, gedruckt wird mit Strg+Enter")),
        FieldSpec("cut_pause_s", N_("Schneidpause"), "choice", choices=CUT_PAUSE_CHOICES, nullable=True,
                 help=N_("Pause zwischen mehreren Etiketten, damit du jedes abschneiden kannst")),
        FieldSpec("guard.confirm_label_mm", N_("Rückfrage ab Labellänge"), "float", min=1, unit="mm",
                 help=N_("Längere Etiketten fragen vor dem Druck nach")),
        FieldSpec("guard.confirm_copies", N_("Rückfrage ab Kopienzahl"), "int", min=1, unit="kopien",
                 help=N_("Ab so vielen Kopien fragt Tapesmith vor dem Druck nach")),
        FieldSpec("guard.max_label_mm", N_("Obergrenze Labellänge"), "float", min=1, unit="mm", visibility=ADVANCED,
                 help=N_("Längere Etiketten druckt Tapesmith nicht")),
        FieldSpec("guard.max_request_mm", N_("Obergrenze Auftragslänge"), "float", min=1, unit="mm",
                 visibility=ADVANCED, help=N_("Höchstlänge eines Auftrags, alle Kopien zusammen")),
        FieldSpec("guard.max_copies", N_("Obergrenze Kopienzahl"), "int", min=1, unit="kopien", visibility=ADVANCED,
                 help=N_("Mehr Kopien in einem Auftrag sind nicht möglich")),
    )),
    SectionSpec("warteschlange", N_("Warteschlange"), (
        FieldSpec("queue.enabled", N_("Warteschlange aktiv"), "bool",
                 help=N_("Ist der Drucker nicht erreichbar, wartet der Auftrag, statt abzubrechen")),
        FieldSpec("queue.auto_retry", N_("Automatischer Nachdruck"), "bool",
                 help=N_("Wartende Aufträge drucken von selbst, sobald der Drucker wieder da ist")),
        FieldSpec("queue.probe", N_("Erreichbarkeitsprüfung"), "choice", choices=PROBE_CHOICES, visibility=CONFIG),
        FieldSpec("queue.backoff_start_s", N_("Wartezeit zu Beginn"), "int", min=1, max=3600, visibility=CONFIG,
                 unit="s"),
        FieldSpec("queue.backoff_max_s", N_("Wartezeit maximal"), "int", min=1, max=86400, visibility=CONFIG,
                 unit="s"),
        FieldSpec("queue.cli_default", N_("CLI reiht standardmäßig ein"), "bool", visibility=CONFIG),
        FieldSpec("status.poll_s", N_("Statusabfrage-Intervall"), "int", min=0, max=3600, visibility=CONFIG, unit="s"),
    )),
    SectionSpec("editor", N_("Editor"), (
        FieldSpec("gui.editor_snap", N_("Einrasten"), "bool",
                 help=N_("Objekte rasten beim Verschieben am Raster und an anderen Objekten ein")),
        FieldSpec(GRID_MM_KEY, N_("Rasterweite"), "float", min=0.125, max=8, step=0.125, unit="mm",
                 help=N_("Abstand der Rasterpunkte im Editor")),
        FieldSpec(GRID_DOTS_KEY, N_("Rasterweite in Druckpunkten"), "int", min=1, max=64, visibility=CONFIG),
        FieldSpec("gui.screen_px_per_mm", N_("Bildschirmpunkte je mm"), "float", min=1, max=20, nullable=True,
                 visibility=CONFIG, help=N_("über „Bildschirm kalibrieren“ setzen")),
    )),
    # Die Tray-App übernimmt diese Werte ohne Neustart (sie prüft die Konfigurationsdatei laufend).
    # Autostart der Tray-App: Karte „Windows-Integration“ bzw. Häkchen im Tray-Menü.
    SectionSpec("tray", N_("Tray und Tastenkürzel"), (
        FieldSpec("hotkey.enabled", N_("Tastenkürzel aktiv"), "bool",
                 help=N_("Die Kürzel gelten in ganz Windows, solange die Tray-App läuft")),
        FieldSpec("hotkey.quick", N_("Schnelldruck"), "hotkey",
                 help=N_("öffnet den Schnelldruck im Browser")),
        FieldSpec("hotkey.clipboard", N_("Zwischenablage"), "hotkey",
                 help=N_("öffnet den Schnelldruck mit dem Text der Zwischenablage")),
        FieldSpec("tray.notify", N_("Meldungen anzeigen"), "bool",
                 help=N_("Windows-Benachrichtigung nach jedem Druck aus dem Tray")),
        FieldSpec("tray.favorites", N_("Favoriten"), "json",
                 help=N_("Vorlagen, die im Tray-Menü unter Favoriten stehen")),
    )),
    SectionSpec("oberflaeche", N_("Oberfläche"), (
        FieldSpec("app.language", N_("Sprache"), "choice", choices=LANGUAGE_CHOICES),
        FieldSpec("app.theme", N_("Farbschema"), "choice", choices=THEME_CHOICES),
    )),
    SectionSpec("updates", N_("Updates"), (
        FieldSpec("update.enabled", N_("Nach Updates suchen"), "bool",
                 help=N_("Tapesmith sucht regelmäßig nach einer neuen Version")),
        FieldSpec("update.auto_install", N_("Automatisch installieren"), "bool",
                 help=N_("Updates werden installiert, wenn Tapesmith gerade nicht druckt")),
        FieldSpec("update.channel", N_("Kanal"), "choice", choices=UPDATE_CHANNEL_CHOICES,
                 help=N_("Beta bringt neue Funktionen früher, kann aber Fehler enthalten")),
        FieldSpec("update.source", N_("Update-Quelle"), "string", visibility=CONFIG,
                 help=N_("github:owner/repo, file:Ordner oder https-Adresse")),
        FieldSpec("update.check_interval_h", N_("Prüfabstand"), "int", min=1, max=720, visibility=CONFIG, unit="h"),
        FieldSpec("update.idle_min", N_("Leerlauf vor dem Update"), "int", min=1, max=1440, visibility=CONFIG,
                 unit="min"),
        FieldSpec("update.keep_versions", N_("Ältere Versionen behalten"), "int", min=1, max=5, visibility=CONFIG),
    )),
    SectionSpec("sicherung", N_("Sicherung"), (
        FieldSpec("backup.auto_daily", N_("Tägliche Sicherung"), "bool",
                 help=N_("Einmal am Tag Verlauf, Vorlagen und Einstellungen sichern")),
        FieldSpec("backup.keep", N_("Sicherungen aufheben"), "int", min=1, max=100, unit="sicherungen",
                 help=N_("Ältere Sicherungen löscht Tapesmith")),
        FieldSpec("backup.dir", N_("Sicherungsordner"), "path", nullable=True, visibility=ADVANCED,
                 help=N_("Leer = Ordner backups im Datenordner")),
    )),
    SectionSpec("vorlagen", N_("Vorlagen"), (
        FieldSpec("templates_dir", N_("Vorlagenordner"), "path", nullable=True, visibility=ADVANCED,
                 help=N_("Ordner für eigene Vorlagen; leer = Ordner templates im Datenordner")),
    )),
    SectionSpec("archiv", N_("Archiv"), (
        FieldSpec("archive.dir", N_("Archivordner"), "path", nullable=True, visibility=ADVANCED,
                 help=N_("Legt jeden Druck als Bild und JSON ab; leer = kein Archiv")),
        FieldSpec("archive.git_commit", N_("Archiv per Git versionieren"), "bool", visibility=ADVANCED,
                 help=N_("Jeden neuen Eintrag im Archivordner als Git-Commit festhalten")),
        FieldSpec("numbering.dir", N_("Zählerordner"), "path", nullable=True, visibility=CONFIG),
    )),
    SectionSpec("druckdienst", N_("Druckdienst"), (
        FieldSpec("daemon.idle_exit_s", N_("Dienst beenden nach Ruhe"), "int", min=0, max=86400, visibility=CONFIG,
                 unit="s"),
        FieldSpec("web.port", N_("Web-Port"), "int", min=1024, max=65535, restart=True, visibility=ADVANCED,
                 help=N_("Port der Oberfläche im Browser")),
    )),
    SectionSpec("ble", N_("Bluetooth LE (experimentell)"), (
        FieldSpec("ble.address", N_("BLE-Adresse"), "string", nullable=True, experimental=True, visibility=ADVANCED,
                 help=N_("Nur für die experimentelle Verbindung über Bluetooth LE")),
        FieldSpec("ble.scan_timeout_s", N_("BLE-Suchzeit"), "float", min=1, max=60, experimental=True, unit="s",
                 visibility=ADVANCED, help=N_("So lange sucht Tapesmith nach dem Drucker")),
    )),
    # Einstellungskarte des Moduls Datenträger (SSH-Scanner und Plattentausch).
    SectionSpec("ssh", N_("SSH-Hosts"), (
        FieldSpec("ssh.hosts", N_("SSH-Hosts"), "json"),
        FieldSpec("ssh.timeout_s", N_("SSH-Zeitlimit"), "float", min=1, max=120, unit="s",
                 help=N_("So lange wartet der Scanner auf eine Antwort des Hosts")),
        FieldSpec("ssh.strict_host_key", N_("Host-Schlüssel streng prüfen"), "bool",
                 help=N_("Nur Hosts mit bekanntem Schlüssel (known_hosts); empfohlen")),
    ), module="datentraeger"),
)


def _field_map() -> dict[str, FieldSpec]:
    return {spec.key: spec for section in SECTIONS for spec in section.fields}


def _fmt_num(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _check_range(spec: FieldSpec, value: float) -> None:
    lo, hi = spec.min, spec.max
    if lo is not None and hi is not None:
        if not (lo <= value <= hi):
            raise ValueError(_t("{label} muss zwischen {min} und {max} liegen", label=_t(spec.label), min=_fmt_num(lo), max=_fmt_num(hi)))
    elif lo is not None and value < lo:
        raise ValueError(_t("{label} muss mindestens {min} sein", label=_t(spec.label), min=_fmt_num(lo)))
    elif hi is not None and value > hi:
        raise ValueError(_t("{label} muss höchstens {max} sein", label=_t(spec.label), max=_fmt_num(hi)))


def _check_ssh_hosts_shape(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValueError(_t("{label} muss eine Liste sein", label=label))
    for item in value:
        if not isinstance(item, dict) or not item.get("name") or not item.get("host"):
            raise ValueError(_t("{label}: jeder Eintrag braucht mindestens 'name' und 'host'", label=label))


def check_field(spec: FieldSpec, value: Any) -> Any:
    """Prüft `value` gegen `spec` und gibt den (ggf. normalisierten) Wert zurück.

    Wirft `ValueError` mit einer deutschen Meldung bei ungültigem Wert. `None` ist nur bei
    `spec.nullable` erlaubt. Grenzen (`min`/`max`) gelten nur für `int`/`float`."""
    if value is None:
        if spec.nullable:
            return None
        raise ValueError(_t("{label} darf nicht leer sein", label=_t(spec.label)))

    if spec.type == "bool":
        if not isinstance(value, bool):
            raise ValueError(_t("{label} muss true oder false sein", label=_t(spec.label)))
        return value

    if spec.type == "int":
        if isinstance(value, bool):
            raise ValueError(_t("{label} muss eine ganze Zahl sein", label=_t(spec.label)))
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(_t("{label} muss eine ganze Zahl sein", label=_t(spec.label)))
            value = int(value)
        elif not isinstance(value, int):
            raise ValueError(_t("{label} muss eine ganze Zahl sein", label=_t(spec.label)))
        _check_range(spec, value)
        return value

    if spec.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(_t("{label} muss eine Zahl sein", label=_t(spec.label)))
        value = float(value)
        _check_range(spec, value)
        return value

    if spec.type == "choice":
        if spec.choices is not None:
            allowed = [choice_value for choice_value, _ in spec.choices]
            if isinstance(value, str) and value not in allowed:
                # Auswahllisten im Browser liefern Text ("5"): eindeutig passende Auswahl übernehmen.
                matches = [c for c in allowed if c is not None and not isinstance(c, str) and str(c) == value]
                if len(matches) == 1:
                    value = matches[0]
            if value not in allowed:
                text = ", ".join(repr(choice_value) for choice_value in allowed)
                raise ValueError(_t("{label} muss eines von {text} sein, ist {value!r}", label=_t(spec.label), text=text, value=value))
        return value

    if spec.type == "hotkey":
        return check_hotkey(_t(spec.label), value)

    if spec.type in ("string", "path"):
        if not isinstance(value, str):
            raise ValueError(_t("{label} muss ein Text sein", label=_t(spec.label)))
        return value

    if spec.type == "json":
        if spec.key == "ssh.hosts":
            _check_ssh_hosts_shape(value, _t(spec.label))
        return value

    raise ValueError(_t("Unbekannter Feldtyp {type!r} für {label}", type=spec.type, label=_t(spec.label)))


def layout_probe() -> LayoutProbe | None:
    """Tastaturlayout für die AltGr-Prüfung (nur Windows; Tests ersetzen diese Funktion)."""
    if sys.platform != "win32":
        return None
    try:
        return WinLayoutProbe()
    except OSError:
        return None


def check_hotkey(label: str, value: Any) -> str:
    """Tastenkürzel wie früher im Tray-Dialog prüfen: gültig (`parse_hotkey`), kein AltGr-Zeichen
    auf der aktuellen Tastatur (`altgr_conflict`), gespeichert in Normalform („Strg+Alt+L“)."""
    if not isinstance(value, str):
        raise ValueError(_t("{label} muss ein Text sein", label=label))
    try:
        spec = parse_hotkey(value)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from None
    probe = layout_probe()
    if probe is not None:
        conflict = altgr_conflict(spec, probe)
        if conflict is not None:
            raise ValueError(f"{label}: {conflict}")
    return format_hotkey(spec)


def _check_hotkey_pair(candidate: dict) -> None:
    """Schnelldruck und Zwischenablage brauchen verschiedene Kürzel."""
    try:
        quick = format_hotkey(parse_hotkey(str(config.setting(candidate, "hotkey.quick"))))
        clip = format_hotkey(parse_hotkey(str(config.setting(candidate, "hotkey.clipboard"))))
    except ValueError:
        return
    if quick == clip:
        raise ValueError(_t("Schnelldruck und Zwischenablage brauchen verschiedene Tastenkürzel"))


def _grid_mm(dots: Any) -> float:
    return float(dots) / DOTS_PER_MM


def _default_for(key: str) -> Any:
    if key == GRID_MM_KEY:
        return _grid_mm(config.GUI_DEFAULTS["editor_grid_dots"])
    if key.startswith("guard."):
        _, _, sub = key.partition(".")
        return getattr(guard_mod.GuardPolicy(), sub)
    if "." in key:
        section_name, _, sub = key.partition(".")
        if section_name == "gui":
            return config.GUI_DEFAULTS[sub]
        return config.SECTION_DEFAULTS[section_name][sub]
    return config.DEFAULTS[key]


def _effective_value(cfg: dict, key: str) -> Any:
    if key == GRID_MM_KEY:
        return _grid_mm(config.setting(cfg, GRID_DOTS_KEY))
    if key.startswith("guard."):
        _, _, sub = key.partition(".")
        default = getattr(guard_mod.GuardPolicy(), sub)
        return cfg.get("guard", {}).get(sub, default)
    return config.setting(cfg, key)


def _field_json(cfg: dict, spec: FieldSpec) -> dict[str, Any]:
    field_json: dict[str, Any] = {
        "key": spec.key, "label": _t(spec.label), "type": spec.type,
        "value": _effective_value(cfg, spec.key), "default": _default_for(spec.key), "nullable": spec.nullable,
        "visibility": spec.visibility,
    }
    for name in ("min", "max", "step", "unit"):
        value = getattr(spec, name)
        if value is not None:
            field_json[name] = value
    if spec.choices is not None:
        field_json["choices"] = [{"value": v, "label": _t(l)} for v, l in spec.choices]
    if spec.help:
        field_json["help"] = _t(spec.help)
    if spec.restart:
        field_json["restart"] = True
    if spec.experimental:
        field_json["experimental"] = True
    return field_json


def settings_json(cfg: dict) -> dict:
    """`SettingsJson`: die Abschnitte mit sichtbaren und erweiterten Feldern und ihrem wirksamen Wert.
    Felder nur für config.json fehlen, ebenso Abschnitte ausgeschalteter Module."""
    enabled = set(modules.enabled_ids(cfg))
    sections_out = []
    for section in SECTIONS:
        if section.module is not None and section.module not in enabled:
            continue
        fields_out = [_field_json(cfg, spec) for spec in section.fields if spec.visibility != CONFIG]
        if not fields_out:
            continue
        sections_out.append({"id": section.id, "title": _t(section.title), "module": section.module,
                             "fields": fields_out})
    return {"sections": sections_out, "config_path": str(paths.config_path())}


def apply_changes(changes: dict) -> list[str]:
    """Prüft und speichert `changes` ({"<schlüssel>": wert}) in dieser Reihenfolge: nur bekannte
    Schlüssel (sonst `config.UnknownSetting`), Schemaprüfung je Feld, `config.validate_config`
    einmal auf der Kopie, dann `config.save_config`. Bei jedem Fehler wird nichts gespeichert.
    Rückgabe: die geänderten Schlüssel in Anfrage-Reihenfolge."""
    order = list(changes.keys())
    if not order:
        return []

    field_map = _field_map()
    checked: dict[str, Any] = {}
    for key in order:
        spec = field_map.get(key)
        if spec is None:
            raise config.UnknownSetting(_t("Unbekannter Einstellungsschlüssel '{key}'", key=key))
        checked[key] = check_field(spec, changes[key])

    current = config.load_config()
    candidate = copy.deepcopy(current)
    sections_touched: dict[str, dict] = {}
    top_level_updates: dict[str, Any] = {}

    for key in order:
        value = checked[key]
        if key == GRID_MM_KEY:
            key = GRID_DOTS_KEY
            value = max(1, min(64, round(value * DOTS_PER_MM)))
        elif key == "transport":
            value = config.check_transport(value)
        elif key == "mac":
            if value is None:
                raise ValueError(_t("MAC-Adresse darf nicht geleert werden"))
            value = config.normalize_mac(value)

        if "." in key:
            section_name, _, field_key = key.partition(".")
            section = sections_touched.setdefault(
                section_name, dict(candidate.get(section_name) or {}))
            section[field_key] = value
            candidate[section_name] = section
        else:
            top_level_updates[key] = value
            candidate[key] = value

    if "update.enabled" in order:
        # Wer die automatische Update-Prüfung selbst ein- oder ausschaltet, hat entschieden: die
        # Oberfläche fragt danach nicht mehr (`update.asked`, siehe POST /update/consent).
        section = sections_touched.setdefault("update", dict(candidate.get("update") or {}))
        section["asked"] = True
        candidate["update"] = section

    config.validate_config(candidate)
    if any(key.startswith("hotkey.") for key in order):
        _check_hotkey_pair(candidate)

    updates: dict[str, Any] = dict(top_level_updates)
    updates.update(sections_touched)
    config.save_config(updates)
    return order
