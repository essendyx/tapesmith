"""Windows-Integration: Explorer-Kontextmenü, URI-Schema, Autostart.

Alles nur unter HKCU (kein Adminrecht nötig), idempotent, über ein injizierbares
Registry-Backend. Tests nutzen ausschließlich `FakeRegistry`; `WinRegBackend` schützt sich
selbst gegen Schreibzugriffe während `pytest` (Sicherheitsnetz „Echte Nutzerdaten sind
tabu“). Kontextmenü/URI öffnen die Web-Oberfläche im Standardbrowser
nur vorausgefüllt (`pythonw -m tapesmith.webui.browser --open/--uri`): gedruckt wird erst
nach Bestätigung durch den Menschen (`IntegrationAction` ist nur ein Vorschlag)."""

import os
import re
import urllib.parse as urlparse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tapesmith.launch import app_argv, command_line, registry_command
from tapesmith.i18n import N_, _t

HKCU_CLASSES = r"Software\Classes"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Tapesmith"
MARKER = "TapesmithManaged"
# URI-Schemata: `tapesmith://` und als Alias das alte `p12label://` (App-Name bis 0.2.x), damit
# vorhandene Links, NFC-Tags und Automationen weiter funktionieren.
URI_SCHEMES = ("tapesmith", "p12label")
PARTS = ("context", "uri", "autostart")


# ---------- Registry-Backends ----------

class RegistryBackend(Protocol):
    """Alle Pfade relativ zu HKEY_CURRENT_USER."""

    def get(self, path: str, name: str = "") -> str | None: ...

    def set(self, path: str, name: str, value: str) -> None: ...

    def delete_value(self, path: str, name: str) -> None: ...

    def delete_tree(self, path: str) -> None: ...

    def exists(self, path: str) -> bool: ...


class FakeRegistry:
    """Dict-basiertes Registry-Backend für Tests (auch für GUI-Tests)."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}

    def get(self, path: str, name: str = "") -> str | None:
        return self.data.get(path, {}).get(name)

    def set(self, path: str, name: str, value: str) -> None:
        self.data.setdefault(path, {})[name] = value

    def delete_value(self, path: str, name: str) -> None:
        self.data.get(path, {}).pop(name, None)

    def delete_tree(self, path: str) -> None:
        prefix = path + "\\"
        for key in [k for k in self.data if k == path or k.startswith(prefix)]:
            del self.data[key]

    def exists(self, path: str) -> bool:
        return path in self.data


class WinRegBackend:
    """Echtes HKEY_CURRENT_USER über `winreg`. Schreibmethoden verweigern sich während
    `pytest` bzw. mit `TAPESMITH_NO_REGISTRY=1` (Sicherheitsnetz); `get` bleibt erlaubt,
    damit `tapesmith integrate status` immer funktioniert."""

    def _guard(self) -> None:
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("TAPESMITH_NO_REGISTRY") == "1":
            raise RuntimeError("Registry-Schreibzugriff in Tests verboten")

    def get(self, path: str, name: str = "") -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except OSError:
            return None

    def set(self, path: str, name: str, value: str) -> None:
        import winreg

        self._guard()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, path: str, name: str) -> None:
        import winreg

        self._guard()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            pass

    def delete_tree(self, path: str) -> None:
        self._guard()
        self._delete_tree(path)

    def _delete_tree(self, path: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
                children = []
                for i in range(winreg.QueryInfoKey(key)[0]):
                    children.append(winreg.EnumKey(key, i))
                for child in children:
                    self._delete_tree(path + "\\" + child)
        except OSError:
            return
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    def exists(self, path: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
                return True
        except OSError:
            return False


# ---------- Plan ----------

@dataclass(frozen=True)
class RegEntry:
    path: str
    name: str
    value: str


@dataclass(frozen=True)
class ContextVerb:
    key: str
    title: str
    targets: tuple[str, ...]
    action: str
    applies_to: str | None = None


CONTEXT_VERBS: tuple[ContextVerb, ...] = (
    ContextVerb("Tapesmith.Serie", N_("Als Serie drucken (Tapesmith)"),
                (r"SystemFileAssociations\.csv", r"SystemFileAssociations\.xlsx",
                 r"SystemFileAssociations\.xlsm"), "batch"),
    ContextVerb("Tapesmith.Bild", N_("Als Bild-Label (Tapesmith)"),
                tuple(rf"SystemFileAssociations\{e}" for e in (".png", ".jpg", ".jpeg", ".bmp", ".gif")),
                "image"),
    ContextVerb("Tapesmith.Zeilen", N_("Ein Label pro Zeile (Tapesmith)"), (r"SystemFileAssociations\.txt",),
                "lines"),
    ContextVerb("Tapesmith.Vorlage", N_("Vorlage öffnen (Tapesmith)"), (r"SystemFileAssociations\.json",),
                "template", applies_to='System.FileName:"*.tapesmith.json"'),
    ContextVerb("Tapesmith.OrdnerName", N_("Name als Label (Tapesmith)"), ("Directory",), "folder-name"),
    ContextVerb("Tapesmith.OrdnerQr", N_("QR mit UNC-Pfad (Tapesmith)"), ("Directory",), "folder-qr"),
)


def plan_entries(parts: Iterable[str], *, command: Callable[..., str] = registry_command,
                 icon: str | None = None, autostart_argv: Sequence[str] | None = None) -> list[RegEntry]:
    """Baut die vollständige Liste der Registry-Einträge für die gewünschten `parts`
    („soll“-Zustand). `command` erzeugt die Befehlszeilen (injizierbar für Tests, die einen
    anderen Programmpfad prüfen wollen); `icon` Default ist das GUI-Executable selbst.

    `autostart_argv`: Befehlszeile für den `Run`-Wert, Standard `app_argv("tray")` wie
    bisher. Der Installer (`tapesmith.install.installer`) übergibt hier `<Wurzel>\\current\\
    Scripts\\pythonw.exe -m tapesmith.gui.tray`."""
    icon_value = icon if icon is not None else app_argv("gui")[0]
    entries: list[RegEntry] = []
    for part in parts:
        if part == "context":
            for verb in CONTEXT_VERBS:
                for target in verb.targets:
                    base = f"{HKCU_CLASSES}\\{target}\\shell\\{verb.key}"
                    entries.append(RegEntry(base, "MUIVerb", _t(verb.title)))
                    entries.append(RegEntry(base, "Icon", icon_value))
                    entries.append(RegEntry(base, MARKER, "1"))
                    if verb.applies_to is not None:
                        entries.append(RegEntry(base, "AppliesTo", verb.applies_to))
                    entries.append(RegEntry(f"{base}\\command", "",
                                            command("gui", "--open", verb.action, "--path")))
        elif part == "uri":
            for scheme in URI_SCHEMES:
                base = f"{HKCU_CLASSES}\\{scheme}"
                entries.append(RegEntry(base, "", "URL:Tapesmith"))
                entries.append(RegEntry(base, "URL Protocol", ""))
                entries.append(RegEntry(base, MARKER, "1"))
                entries.append(RegEntry(f"{base}\\DefaultIcon", "", icon_value))
                entries.append(RegEntry(f"{base}\\shell\\open\\command", "", command("gui", "--uri")))
        elif part == "autostart":
            argv = autostart_argv if autostart_argv is not None else app_argv("tray")
            entries.append(RegEntry(RUN_KEY, RUN_VALUE, command_line(argv)))
        else:
            raise ValueError(_t("Unbekannter Teil '{part}', erlaubt: {items}", part=part, items=', '.join(PARTS)))
    return entries


def _format_line(prefix: str, entry: RegEntry) -> str:
    suffix = f"\\{entry.name}" if entry.name else ""
    return f"{prefix}: HKCU\\{entry.path}{suffix} = {entry.value}"


def install(backend: RegistryBackend, parts: Iterable[str] = ("context", "uri"), *, dry_run: bool = False,
           command: Callable[..., str] = registry_command, icon: str | None = None,
           autostart_argv: Sequence[str] | None = None) -> list[str]:
    """Setzt nur abweichende Werte (idempotent: ein zweiter Aufruf liefert `[]`)."""
    lines = []
    for entry in plan_entries(parts, command=command, icon=icon, autostart_argv=autostart_argv):
        if backend.get(entry.path, entry.name) == entry.value:
            continue
        if not dry_run:
            backend.set(entry.path, entry.name, entry.value)
        lines.append(_format_line("gesetzt", entry))
    return lines


def uninstall(backend: RegistryBackend, parts: Iterable[str] = PARTS, *, dry_run: bool = False) -> list[str]:
    """Entfernt nur selbst angelegte Schlüssel (per `MARKER`) bzw. den eigenen `Run`-Wert."""
    lines = []
    for part in parts:
        if part == "context":
            for verb in CONTEXT_VERBS:
                for target in verb.targets:
                    path = f"{HKCU_CLASSES}\\{target}\\shell\\{verb.key}"
                    if backend.get(path, MARKER) == "1":
                        if not dry_run:
                            backend.delete_tree(path)
                        lines.append(_t("entfernt: HKCU\\{path}", path=path))
        elif part == "uri":
            for scheme in URI_SCHEMES:
                path = f"{HKCU_CLASSES}\\{scheme}"
                if backend.get(path, MARKER) == "1":
                    if not dry_run:
                        backend.delete_tree(path)
                    lines.append(_t("entfernt: HKCU\\{path}", path=path))
        elif part == "autostart":
            current = backend.get(RUN_KEY, RUN_VALUE)
            if current and ("tapesmith" in current or "Tapesmith" in current):
                if not dry_run:
                    backend.delete_value(RUN_KEY, RUN_VALUE)
                lines.append(_t("entfernt: HKCU\\{run_key}\\{run_value}", run_key=RUN_KEY, run_value=RUN_VALUE))
        else:
            raise ValueError(_t("Unbekannter Teil '{part}', erlaubt: {items}", part=part, items=', '.join(PARTS)))
    return lines


def status(backend: RegistryBackend, *, command: Callable[..., str] = registry_command,
          icon: str | None = None, autostart_argv: Sequence[str] | None = None) -> dict[str, str]:
    """Je Teil „installiert“ | „teilweise“ | „veraltet“ (Befehl/Icon weichen vom aktuell
    berechneten Soll-Zustand ab, z. B. anderer Programmpfad) | „nicht installiert“."""
    result: dict[str, str] = {}
    for part in PARTS:
        entries = plan_entries((part,), command=command, icon=icon, autostart_argv=autostart_argv)
        current = [backend.get(e.path, e.name) for e in entries]
        missing = sum(1 for c in current if c is None)
        if missing == len(entries):
            result[part] = _t("nicht installiert")
        elif missing > 0:
            result[part] = "teilweise"
        elif any(c != e.value for c, e in zip(current, entries)):
            result[part] = "veraltet"
        else:
            result[part] = "installiert"
    return result


# ---------- Aktionen aus URI und Kontextmenü ----------

FILE_ACTIONS = ("batch", "image", "lines", "template", "folder-name", "folder-qr")
URI_ACTIONS = ("print", "template", "text", "qr")
MAX_URI_VALUES = 20
MAX_VALUE_LEN = 300

_TEMPLATE_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_LOCAL_NOTE = N_("Lokaler Pfad: QR funktioniert nur auf diesem PC")


@dataclass(frozen=True)
class IntegrationAction:
    kind: str
    template: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    lines: tuple[str, ...] = ()
    qr: str | None = None
    path: Path | None = None
    source: str = ""
    note: str = ""


def _check_value_len(key: str, value: str) -> None:
    if len(value) > MAX_VALUE_LEN:
        raise ValueError(_t("Wert für '{key}' zu lang (max. {max_value_len} Zeichen)", key=key, max_value_len=MAX_VALUE_LEN))


def parse_uri(uri: str) -> IntegrationAction:
    """Parst `tapesmith://<aktion>?...` bzw. `tapesmith:<aktion>?...` (Alias: `p12label://`).
    Es wird nichts automatisch gedruckt, die Aktion ist nur ein Vorschlag für die GUI."""
    parsed = urlparse.urlsplit(uri)
    if parsed.scheme.lower() not in URI_SCHEMES:
        raise ValueError(_t("Unbekanntes Schema '{scheme}', erwartet 'tapesmith'", scheme=parsed.scheme))
    action = (parsed.netloc or parsed.path).strip("/").lower()
    if action not in URI_ACTIONS:
        raise ValueError(_t("Unbekannte Aktion '{action}', erlaubt: {items}", action=action, items=', '.join(URI_ACTIONS)))

    query = urlparse.parse_qs(parsed.query, keep_blank_values=True)

    if action in ("print", "template"):
        template_vals = query.get("template")
        if not template_vals:
            raise ValueError(_t("Parameter 'template' fehlt"))
        template_name = template_vals[-1]
        if not _TEMPLATE_NAME.fullmatch(template_name):
            raise ValueError(_t("Ungültiger Vorlagenname '{template_name}'", template_name=template_name))
        values: dict[str, str] = {}
        for key, vals in query.items():
            if key == "template":
                continue
            value = vals[-1]
            _check_value_len(key, value)
            values[key] = value
        if len(values) > MAX_URI_VALUES:
            raise ValueError(_t("Zu viele Parameter (max. {max_uri_values})", max_uri_values=MAX_URI_VALUES))
        return IntegrationAction(kind="template", template=template_name, values=values, source="uri")

    if action == "text":
        lines = query.get("l")
        if not lines:
            raise ValueError(_t("Parameter 'l' fehlt"))
        if len(lines) > 3:
            raise ValueError(_t("Höchstens 3 Textzeilen erlaubt"))
        for line in lines:
            _check_value_len("l", line)
        return IntegrationAction(kind="text", lines=tuple(lines), source="uri")

    # action == "qr"
    data_vals = query.get("data")
    if not data_vals:
        raise ValueError(_t("Parameter 'data' fehlt"))
    data = data_vals[-1]
    _check_value_len("data", data)
    texts = query.get("text", [])
    if len(texts) > 2:
        raise ValueError(_t("Höchstens 2 Textzeilen erlaubt"))
    for text in texts:
        _check_value_len("text", text)
    return IntegrationAction(kind="qr", qr=data, lines=tuple(texts), source="uri")


def read_lines_file(path: Path, max_lines: int = 100) -> tuple[str, ...]:
    """Liest eine Textdatei zeilenweise: UTF-8 (mit BOM), sonst CP1252; leere Zeilen weg."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return tuple(lines[:max_lines])


def _wnet_resolver(drive: str) -> str | None:
    import ctypes

    ERROR_NOT_CONNECTED = 2250
    buf = ctypes.create_unicode_buffer(260)
    length = ctypes.c_ulong(260)
    result = ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(length))
    if result != 0:
        return None
    return buf.value


def to_unc(path: Path, *, resolver: Callable[[str], str | None] | None = None) -> tuple[str, bool]:
    """`"Z:\\Doku\\Ordner"` + `resolver("Z:") == r"\\\\nas\\share"` -> `(r"\\\\nas\\share\\Doku\\Ordner", True)`.
    Ein bereits vorhandener UNC-Pfad bleibt unverändert (`True`); ein lokales Laufwerk ohne
    Zuordnung bleibt lokal (`False`)."""
    p = Path(path)
    text = str(p)
    if text.startswith("\\\\"):
        return (text, True)
    drive = p.drive
    if drive:
        remote = (resolver or _wnet_resolver)(drive)
        if remote:
            return (remote + text[len(drive):], True)
    return (text, False)


def file_action(action: str, path: Path, *, resolver: Callable[[str], str | None] | None = None
                ) -> IntegrationAction:
    """Baut die `IntegrationAction` für einen Explorer-Kontextmenü-Klick auf `path`."""
    if action not in FILE_ACTIONS:
        raise ValueError(_t("Unbekannte Aktion '{action}', erlaubt: {items}", action=action, items=', '.join(FILE_ACTIONS)))
    p = Path(path)

    if action in ("batch", "image", "template"):
        if not p.is_file():
            raise ValueError(_t("Datei nicht gefunden: {p}", p=p))
        if action == "template":
            from tapesmith.templates.store import SUFFIX, is_template_file

            if not is_template_file(p.name):
                raise ValueError(_t("Keine Vorlagendatei ('{suffix}' erwartet): {name}", suffix=SUFFIX, name=p.name))
        return IntegrationAction(kind=action, path=p, source="kontextmenü")

    if action == "lines":
        if not p.is_file():
            raise ValueError(_t("Datei nicht gefunden: {p}", p=p))
        return IntegrationAction(kind="lines", lines=read_lines_file(p), path=p, source="kontextmenü")

    if action == "folder-name":
        return IntegrationAction(kind="lines", lines=(p.name,), path=p, source="kontextmenü")

    # action == "folder-qr"
    unc, is_unc = to_unc(p, resolver=resolver)
    note = "" if is_unc else _t(_LOCAL_NOTE)
    return IntegrationAction(kind="qr", qr=unc, lines=(p.name,), path=p, source="kontextmenü", note=note)
