"""API-Token-Speicher: nur Hash auf der Platte, Klartext genau einmal beim Anlegen.

Die Datei (`access/tokens.json`) wird bei geänderter mtime neu gelesen, damit eine Änderung per
CLI sofort im laufenden Druckdienst wirkt (mehrere `TokenStore`-Instanzen auf derselben Datei).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith import fileutil, paths
from tapesmith.i18n import N_, _t

ROLES = ("admin", "drucken", "familie")
ROLE_LABELS = {"admin": N_("Verwaltung"), "drucken": N_("Drucken"), "familie": N_("Familie")}

_NAME_RE = re.compile(r"^[\w .-]{1,40}$")
_SECRET_FORM_RE = re.compile(r"^p12_([0-9a-f]{8})_[A-Za-z0-9_-]{20,}$")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenInfo:
    id: str
    name: str
    role: str
    created: str
    last_used: str | None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "role_label": _t(ROLE_LABELS[self.role]),
            "created": self.created,
            "last_used": self.last_used,
            "hint": f"p12_{self.id}_…",
        }


def _entry_to_info(entry: dict) -> TokenInfo:
    return TokenInfo(entry["id"], entry["name"], entry["role"], entry["created"],
                     entry.get("last_used"))


class TokenStore:
    def __init__(self, path: Path | None = None, *, now=datetime.now,
                 touch_interval_s: float = 600.0) -> None:
        self.path = Path(path) if path is not None else paths.app_dir() / "access" / "tokens.json"
        self._now = now
        self._touch_interval_s = touch_interval_s
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._tokens: list[dict] = []

    # ---------- Laden/Speichern ----------

    def _load_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = None
            self._tokens = []
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(_t("Token-Datei {path} ist beschädigt: {exc}", path=self.path, exc=exc)) from exc
        self._tokens = list(data.get("tokens", []))
        self._mtime = mtime

    def _save(self) -> None:
        data = {"version": 1, "tokens": self._tokens}
        fileutil.atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False))
        self._mtime = self.path.stat().st_mtime

    def _find_entry(self, id_or_name: str) -> dict | None:
        for entry in self._tokens:
            if entry["id"] == id_or_name:
                return entry
        matches = [e for e in self._tokens if e["name"].casefold() == id_or_name.casefold()]
        if len(matches) > 1:
            raise ValueError(_t("Mehrere Tokens mit dem Namen '{id_or_name}'", id_or_name=id_or_name))
        return matches[0] if matches else None

    # ---------- öffentliche API ----------

    def create(self, name: str, role: str) -> tuple[TokenInfo, str]:
        if role not in ROLES:
            raise ValueError(_t("Rolle '{role}' unbekannt: erlaubt {items}", role=role, items=', '.join(ROLES)))
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(
                _t("Token-Name {name!r} ungültig: 1..40 Zeichen (Buchstaben, Ziffern, Leerzeichen, ._-)", name=name))
        with self._lock:
            self._load_if_changed()
            for entry in self._tokens:
                if entry["name"].casefold() == name.casefold():
                    raise ValueError(_t("Token-Name '{name}' ist schon vergeben", name=name))
            token_id = secrets.token_hex(4)
            plaintext = f"p12_{token_id}_{secrets.token_urlsafe(32)}"
            created = self._now().isoformat()
            entry = {
                "id": token_id,
                "name": name,
                "role": role,
                "hash": "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
                "created": created,
                "last_used": None,
            }
            self._tokens.append(entry)
            self._save()
            return _entry_to_info(entry), plaintext

    def list(self) -> list[TokenInfo]:
        with self._lock:
            self._load_if_changed()
            entries = sorted(self._tokens, key=lambda e: e["created"])
            return [_entry_to_info(e) for e in entries]

    def find(self, id_or_name: str) -> TokenInfo | None:
        with self._lock:
            self._load_if_changed()
            entry = self._find_entry(id_or_name)
            return _entry_to_info(entry) if entry is not None else None

    def revoke(self, id_or_name: str) -> TokenInfo:
        with self._lock:
            self._load_if_changed()
            entry = self._find_entry(id_or_name)
            if entry is None:
                raise KeyError(id_or_name)
            self._tokens.remove(entry)
            self._save()
            return _entry_to_info(entry)

    def verify(self, secret: str) -> TokenInfo | None:
        if not isinstance(secret, str) or not secret:
            return None
        match = _SECRET_FORM_RE.match(secret)
        if not match:
            return None
        token_id = match.group(1)
        with self._lock:
            try:
                self._load_if_changed()
            except ValueError as exc:
                log.warning("Token-Datei nicht lesbar, Dienst läuft weiter: %s", exc)
                return None
            entry = None
            for candidate in self._tokens:
                if candidate["id"] == token_id:
                    entry = candidate
                    break
            if entry is None:
                return None
            candidate_hash = "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(candidate_hash, entry["hash"]):
                return None
            self._touch(entry)
            return _entry_to_info(entry)

    def _touch(self, entry: dict) -> None:
        """Schreibt `last_used` höchstens alle `touch_interval_s`; Schreibfehler werden ignoriert."""
        now = self._now()
        last_used = entry.get("last_used")
        if last_used:
            try:
                elapsed = (now - datetime.fromisoformat(last_used)).total_seconds()
            except ValueError:
                elapsed = self._touch_interval_s
            if elapsed < self._touch_interval_s:
                return
        entry["last_used"] = now.isoformat()
        try:
            self._save()
        except OSError:
            pass
