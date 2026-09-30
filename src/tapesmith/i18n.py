"""Übersetzungen für den Python-Teil, Qt-frei.

Zwei Arten von Katalogen:

1. Schlüssel-Kataloge unter `tapesmith/locales/<sprache>/<namespace>.json` (Tray, Fehlercodes,
   Module). Ein Schlüssel hat die Form `"<namespace>.<pfad>"`: `tr("tray.menu.quick")` liest aus
   `tray.json` den Pfad `menu.quick`. Fehlt ein Schlüssel in der Sprache, gilt Deutsch; fehlt er
   auch dort, der Schlüssel selbst.
2. Meldungs-Katalog für Texte im Quelltext (Server, CLI, Selbsttest, Warnungen): der deutsche Text
   selbst ist die Kennung (wie bei gettext). `_t("Vorlage {name} fehlt", name=n)` liefert auf
   Deutsch genau diesen Text, in anderen Sprachen die Übersetzung aus
   `tapesmith/locales/messages/<sprache>.json` (flaches Objekt deutscher Text -> Übersetzung).
   `N_("...")` markiert Texte in Konstanten, die erst später mit `_t(konstante)` übersetzt werden.
   `tests/test_i18n_messages.py` prüft, dass jede Kennung im Quelltext übersetzt ist.

Platzhalter `{name}` werden mit `str.format_map` ersetzt (auch `{wert:02x}`).

Sprache: `language()` ist die Sprache der laufenden Anfrage (`use_language`, von der Web-API je
Anfrage gesetzt) oder sonst `default_language()`: `TAPESMITH_LANG` (erzwingt), sonst
`app.language` (`de`/`en`), sonst die Windows-Anzeigesprache (`system_language`). Unterstützt sind
Deutsch und Englisch; jede andere Systemsprache ergibt Englisch.

Die Kataloge liegen als Paketdaten neben dem Code, so dass sie auch in einer per pip installierten
Umgebung unter `tapesmith/locales/...` gefunden werden.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import locale
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from importlib import resources

log = logging.getLogger(__name__)

LANGUAGES = ("de", "en")
# Quellsprache der Kataloge: fehlende Schlüssel fallen auf Deutsch zurück.
FALLBACK = "de"
# Sprache für jede andere oder unbekannte Systemsprache (die App wird international veröffentlicht).
DEFAULT = "en"
# Erzwingt die Sprache für CLI, Dienst und Tray (`de` oder `en`).
ENV_LANG = "TAPESMITH_LANG"
# Ersetzt die erkannte Systemsprache (Tests, Screenshots); nicht für den Alltag gedacht.
ENV_SYSTEM_LANG = "TAPESMITH_SYSTEM_LANG"

# Primäre Sprach-IDs von Windows (LANGID & 0x3FF).
_PRIMARY_LANG = {0x07: "de", 0x09: "en"}

_request_language: contextvars.ContextVar[str | None] = contextvars.ContextVar("tapesmith_language",
                                                                               default=None)


def _locales_root():
    return resources.files("tapesmith") / "locales"


@functools.lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    folder = _locales_root() / lang
    data: dict = {}
    try:
        entries = sorted(folder.iterdir(), key=lambda entry: entry.name)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return data
    for entry in entries:
        name = entry.name
        if not name.endswith(".json") or not entry.is_file():
            continue
        try:
            content = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Übersetzungskatalog %s/%s nicht lesbar: %s", lang, name, exc)
            continue
        if isinstance(content, dict):
            data[name[: -len(".json")]] = content
    return data


@functools.lru_cache(maxsize=None)
def _load_messages(lang: str) -> dict[str, str]:
    entry = _locales_root() / "messages" / f"{lang}.json"
    try:
        content = json.loads(entry.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError) as exc:
        log.warning("Meldungskatalog %s nicht lesbar: %s", lang, exc)
        return {}
    if not isinstance(content, dict):
        return {}
    return {k: v for k, v in content.items() if isinstance(k, str) and isinstance(v, str)}


def catalog(lang: str) -> dict:
    """Alle Namespaces einer Sprache als `{namespace: verschachteltes dict}` (gecacht)."""
    if lang not in LANGUAGES:
        return {}
    return _load(lang)


def messages(lang: str) -> dict[str, str]:
    """Meldungs-Katalog einer Sprache (deutscher Text -> Übersetzung); Deutsch ist leer."""
    if lang not in LANGUAGES or lang == FALLBACK:
        return {}
    return _load_messages(lang)


def reload_catalogs() -> None:
    """Leert den Katalog-Cache; der nächste Zugriff liest die JSON-Dateien neu."""
    _load.cache_clear()
    _load_messages.cache_clear()
    _default_cache.clear()


def _lookup(data: dict, key: str) -> str | None:
    node: object = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


class _KeepMissing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format(text: str, params: dict) -> str:
    try:
        return text.format_map(_KeepMissing(params))
    except (ValueError, IndexError, AttributeError, TypeError, KeyError):
        return text


def tr(key: str, lang: str | None = None, **params) -> str:
    """Übersetzung zu `key` in `lang` (None: `language()`, unbekannt: Deutsch)."""
    if lang is None:
        lang = language()
    elif lang not in LANGUAGES:
        lang = FALLBACK
    text = _lookup(catalog(lang), key)
    if text is None and lang != FALLBACK:
        text = _lookup(catalog(FALLBACK), key)
    if text is None:
        return key
    return _format(text, params)


def _t(msgid: str, /, **params) -> str:
    """Meldung `msgid` (deutscher Text) in der Sprache der Anfrage bzw. `default_language()`.

    Ohne Parameter bleibt der Text unformatiert (geschweifte Klammern bleiben stehen)."""
    return translate(msgid, language(), **params)


def translate(msgid: str, lang: str | None, /, **params) -> str:
    """Wie `_t`, aber in der Sprache `lang` (None: `language()`)."""
    if lang is None:
        lang = language()
    text = msgid
    if lang != FALLBACK:
        text = messages(lang).get(msgid, msgid)
    return _format(text, params) if params else text


def N_(msgid: str) -> str:
    """Markiert einen Text für den Meldungs-Katalog, ohne ihn schon zu übersetzen."""
    return msgid


def normalize(tag: object) -> str | None:
    """`de`/`en` aus einem Sprach-Tag wie `en-US`, `de_DE` oder `EN`; sonst None."""
    if not isinstance(tag, str):
        return None
    primary = tag.strip().replace("_", "-").split("-")[0].lower()
    return primary if primary in LANGUAGES else None


def parse_accept_language(header: str | None) -> str | None:
    """Beste unterstützte Sprache aus `Accept-Language` (nach q-Wert). Ein Kopf nur mit anderen
    Sprachen ergibt Englisch, ein leerer oder fehlender Kopf None."""
    if not header or not header.strip():
        return None
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            ranked.append((-quality, index, tag.strip()))
    ranked.sort()
    tags = [tag for _q, _i, tag in ranked if tag != "*"]
    for tag in tags:
        found = normalize(tag)
        if found:
            return found
    return DEFAULT if tags else None


def _windows_langid() -> int:
    import ctypes

    return int(ctypes.windll.kernel32.GetUserDefaultUILanguage())


def system_language(reader: Callable[[], int] | None = None) -> str:
    """Sprache der Windows-Oberfläche: `de` oder `en`, jede andere Sprache und jeder Fehler `en`.

    `TAPESMITH_SYSTEM_LANG` ersetzt die Erkennung (Tests, Screenshots). Windows:
    `GetUserDefaultUILanguage` über ctypes (`reader` ersetzbar für Tests), primäre Sprach-ID
    0x07 = de, 0x09 = en. Andere Systeme: `locale.getlocale()`."""
    forced = normalize(os.environ.get(ENV_SYSTEM_LANG))
    if forced and reader is None:
        return forced
    try:
        if reader is not None or sys.platform == "win32":
            langid = (reader or _windows_langid)()
            return _PRIMARY_LANG.get(int(langid) & 0x3FF, DEFAULT)
        return normalize(locale.getlocale()[0] or "") or DEFAULT
    except Exception:  # noqa: BLE001 (jede Störung heißt: unbekannt, also Englisch)
        return DEFAULT


def resolve_language(setting: str | None, *,
                     system: Callable[[], str | None] = system_language) -> str:
    """Wirksame Sprache: `de`/`en` wie eingestellt, sonst (`auto`, None, Unbekanntes) die
    Systemsprache über `system()`; kennt die keiner, Englisch."""
    if setting in LANGUAGES:
        return setting
    try:
        found = system()
    except Exception:  # noqa: BLE001
        found = None
    return found if found in LANGUAGES else DEFAULT


def env_language() -> str | None:
    """Sprache aus `TAPESMITH_LANG` (`de`/`en`, auch `en-US`), sonst None."""
    return normalize(os.environ.get(ENV_LANG))


def current_language(cfg: dict | None = None) -> str:
    """Sprache aus `TAPESMITH_LANG`, sonst `app.language` (bei `cfg=None` aus
    `config.load_config()`) bzw. der Systemsprache. Kaputte Konfiguration wie `auto`."""
    forced = env_language()
    if forced:
        return forced
    setting = None
    try:
        from tapesmith import config

        if cfg is None:
            cfg = config.load_config()
        setting = config.setting(cfg, "app.language")
    except Exception:  # noqa: BLE001 (kaputte Konfiguration: Systemsprache)
        setting = None
    return resolve_language(setting)


_default_cache: dict[tuple, str] = {}
_default_lock = threading.Lock()


def _config_stamp() -> tuple:
    try:
        from tapesmith import paths

        path = paths.config_path()
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_size
    except (OSError, RuntimeError, ValueError):
        return ("", 0, 0)


def default_language() -> str:
    """Sprache ohne Anfrage-Kontext (CLI, Druckaufträge, Ereignisse): wie `current_language()`,
    gecacht bis sich `config.json`, `TAPESMITH_LANG` oder `TAPESMITH_SYSTEM_LANG` ändert."""
    forced = env_language()
    if forced:
        return forced
    key = (os.environ.get(ENV_SYSTEM_LANG, ""), *_config_stamp())
    with _default_lock:
        cached = _default_cache.get(key)
    if cached is not None:
        return cached
    lang = current_language()
    with _default_lock:
        _default_cache.clear()
        _default_cache[key] = lang
    return lang


def language() -> str:
    """Sprache der laufenden Anfrage (`use_language`), sonst `default_language()`."""
    lang = _request_language.get()
    return lang if lang in LANGUAGES else default_language()


def request_language() -> str | None:
    """Die für die laufende Anfrage gesetzte Sprache oder None."""
    return _request_language.get()


@contextlib.contextmanager
def use_language(lang: str | None) -> Iterator[str]:
    """Setzt die Sprache für den umschlossenen Block (auch für Kopien des Kontexts, z. B.
    Threadpool-Aufrufe der Web-API). None oder Unbekanntes lässt `default_language()` gelten."""
    value = normalize(lang)
    token = _request_language.set(value)
    try:
        yield value or default_language()
    finally:
        _request_language.reset(token)


def set_language(lang: str | None) -> contextvars.Token:
    """Setzt die Sprache des aktuellen Kontexts (Gegenstück: `reset_language`)."""
    return _request_language.set(normalize(lang))


def reset_language(token: contextvars.Token) -> None:
    _request_language.reset(token)
