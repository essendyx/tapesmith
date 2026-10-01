"""`UpdateService`: Prüfen, Bereitstellen, Installation starten, Rückstellung und Leerlauf-Regel
für Web-API, CLI und Addon.

Nicht installiert (portabel oder Entwicklung): `status()` meldet `installed: false`, `check()`
zeigt trotzdem die verfügbare Version, `prepare`/`start_install`/`start_rollback` werfen
`update.not_installed`. Versionen aus `install.json` `failed` werden nie angeboten.

Versionsauswahl: `versions()` listet alle über Python installierbaren Versionen der Quelle (plus die
lokal vorhandenen). Eine ausdrücklich gewählte Version (`explicit=True`) darf auch älter sein
(Zurückgehen, vorher eine Sicherung) oder eine Vorabversion; automatisch geht es nie zurück."""

from __future__ import annotations

import logging
import shutil
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tapesmith import launch
from tapesmith.config import setting
from tapesmith.install import installer, layout
from tapesmith.install import venv as venv_mod
from tapesmith.update import state as state_mod
from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import KIND_PYTHON, Manifest, lock_text, parse_manifest
from tapesmith.update.signing import load_trusted_keys, verify
from tapesmith.update.sources import parse_source
from tapesmith.i18n import N_, _t

log = logging.getLogger("tapesmith.update")

IDLE_HEARTBEAT_S = 120.0
# Versionsliste zwischenspeichern: GitHub erlaubt ohne Anmeldung nur 60 Abrufe je Stunde
VERSIONS_CACHE_S = 600.0
_PREPARE_LOCK = threading.Lock()
NOT_INSTALLED_MESSAGE = (N_("Entwicklung oder nicht installiert: Updates nur in der installierten App. Installieren mit: py -m tapesmith install"))
APPLY_MODULE = "tapesmith.update.apply"


def _app_version() -> str:
    from tapesmith import __version__

    return __version__


def _default_heartbeat() -> float | None:
    from tapesmith.webapi.drafts import last_heartbeat

    return last_heartbeat()


def _default_backup(cfg: dict) -> object:
    from tapesmith import backup as backup_mod

    return backup_mod.create_backup(cfg=cfg)


class UpdateService:
    def __init__(self, cfg_loader: Callable[[], dict], *, source_factory=parse_source,
                 keys_loader=load_trusted_keys, root: Path | None = None,
                 spawn: Callable = launch.spawn_detached, run: Callable = venv_mod.run_hidden,
                 now: Callable[[], datetime] = datetime.now, transport=None,
                 executable: str | None = None, clock: Callable[[], float] = time.monotonic,
                 heartbeat: Callable[[], float | None] = _default_heartbeat,
                 app_version: Callable[[], str] = _app_version,
                 backup: Callable[[dict], object] | None = None):
        self.cfg_loader = cfg_loader
        self.source_factory = source_factory
        self.keys_loader = keys_loader
        self._root = Path(root) if root is not None else None
        self.spawn = spawn
        self.run = run
        self.now = now
        self.transport = transport
        self.executable = executable
        self.clock = clock
        self.heartbeat = heartbeat
        self.app_version = app_version
        self.backup = backup or _default_backup
        self._cache: tuple[str, Manifest, object] | None = None
        self._versions_cache: tuple[float, str, list] | None = None

    # ---------- Grundlagen ----------

    def root(self) -> Path | None:
        if self._root is not None:
            return self._root
        try:
            return layout.install_root()
        except RuntimeError:
            return None

    def _state(self) -> layout.InstallState | None:
        root = self.root()
        if root is None:
            return None
        try:
            return layout.read_state(root)
        except ValueError:
            return None

    def installed(self) -> bool:
        root = self.root()
        if root is None:
            return False
        try:
            if not layout.running_installed(self.executable or sys.executable, root):
                return False
        except Exception:  # noqa: BLE001
            return False
        st = self._state()
        return st is not None and bool(st.current)

    def _cfg(self) -> dict:
        try:
            return self.cfg_loader()
        except Exception:  # noqa: BLE001 (Status auch bei kaputter Konfiguration)
            return {}

    def _current(self) -> str:
        if self.installed():
            st = self._state()
            if st is not None and st.current:
                return st.current
        return self.app_version()

    def _saved(self) -> state_mod.UpdateStatus:
        return state_mod.load_status() or state_mod.UpdateStatus()

    def _write(self, **changes) -> state_mod.UpdateStatus:
        """Schreibt `state.json` mit frischen Installationsfeldern (die Tray-App liest `installed`)."""
        status = self.status()
        for key, value in changes.items():
            setattr(status, key, value)
        state_mod.save_status(status)
        return status

    def _fail(self, exc: UpdateError) -> None:
        self._write(state="failed", error={"code": exc.code, "message": str(exc)})

    # ---------- Status ----------

    def status(self, service=None) -> state_mod.UpdateStatus:
        cfg = self._cfg()
        saved = self._saved()
        installed = self.installed()
        st = self._state() if installed else None
        root = self.root() if installed else None
        current = self._current()
        available = saved.available
        if available and not self._offerable(str(available.get("version", "")), current, st):
            available = None
        can_rollback = bool(installed and st is not None and st.previous and st.previous not in st.failed
                            and root is not None and layout.version_dir(st.previous, root).is_dir())
        enabled = bool(setting(cfg, "update.enabled"))
        return state_mod.UpdateStatus(
            installed=installed, current=current, previous=st.previous if st else None,
            root=str(root) if root is not None else None,
            enabled=enabled, source=str(setting(cfg, "update.source")),
            channel=str(setting(cfg, "update.channel")), auto_install=bool(setting(cfg, "update.auto_install")),
            last_check=saved.last_check, available=available, state=saved.state, error=saved.error,
            can_rollback=can_rollback, idle_ok=self.idle_ok(service) if service is not None else False,
            consent_needed=bool(installed and not enabled and not setting(cfg, "update.asked")),
            installed_elsewhere=bool(not installed and self._install_present()))

    def _install_present(self) -> bool:
        root = self.root()
        try:
            return root is not None and layout.current_link(root).exists()
        except OSError:
            return False

    def _offerable(self, version: str, current: str, st: layout.InstallState | None) -> bool:
        try:
            newer = layout.parse_version(version) > layout.parse_version(current)
        except ValueError:
            return False
        return newer and (st is None or version not in st.failed)

    # ---------- Prüfen ----------

    def _source(self):
        cfg = self._cfg()
        return self.source_factory(str(setting(cfg, "update.source")), transport=self.transport,
                                   channel=str(setting(cfg, "update.channel")))

    def _fetch(self, version: str | None = None) -> tuple[Manifest | None, object]:
        """Manifest laden (neueste bzw. genau `version`) und Signatur prüfen. (None, Quelle): kein
        passendes Release in der Quelle."""
        source = self._source()
        fetched = source.fetch_manifest(version) if version is not None else source.fetch_manifest()
        if fetched is None:
            return None, source
        data, signature = fetched
        verify(data, signature, self.keys_loader())
        manifest = parse_manifest(data)
        return manifest, source

    # ---------- Versionsauswahl ----------

    def versions(self, *, include_prerelease: bool = False, refresh: bool = False) -> dict:
        """Alle über Python installierbaren Versionen der Quelle und die lokal vorhandenen, neueste
        zuerst: `{"versions": [...], "error": {...} | None}`. Je Eintrag `version`, `published`,
        `notes`, `prerelease`, `current`, `installed` (lokal bereit), `failed`, `newer`,
        `in_source`. Vorabversionen nur im Kanal beta oder mit `include_prerelease`. Die Liste der
        Quelle bleibt `VERSIONS_CACHE_S` zwischengespeichert; Signaturen prüft erst `prepare`."""
        cfg = self._cfg()
        channel = str(setting(cfg, "update.channel"))
        key = f"{setting(cfg, 'update.source')}|{channel}"
        error = None
        releases: list = []
        cached = self._versions_cache
        if not refresh and cached is not None and cached[1] == key and self.clock() - cached[0] < VERSIONS_CACHE_S:
            releases = cached[2]
        else:
            try:
                releases = list(self._source().list_releases())
                self._versions_cache = (self.clock(), key, releases)
            except UpdateError as exc:
                error = {"code": exc.code, "message": str(exc), "hint": exc.hint}
            except Exception as exc:  # noqa: BLE001 (lokale Versionen trotzdem zeigen)
                log.error("Versionsliste: unerwarteter Fehler: %s", exc)
                error = {"code": "update.source_unreachable",
                         "message": _t("Versionsliste nicht abrufbar ({name})", name=type(exc).__name__), "hint": ""}
        installed = self.installed()
        st = self._state() if installed else None
        current = self._current()
        show_pre = channel == "beta" or include_prerelease
        entries: dict[str, dict] = {}
        for release in releases:
            if release.prerelease and not show_pre and release.version != current:
                continue
            entries.setdefault(release.version, {"version": release.version, "published": release.published,
                                                 "notes": release.notes, "prerelease": release.prerelease,
                                                 "in_source": True})
        local = list(st.versions) if st is not None else []
        for version in [*local, current]:
            entries.setdefault(version, {"version": version, "published": None, "notes": "", "prerelease": False,
                                         "in_source": False})
        result = []
        for version, entry in entries.items():
            try:
                order = layout.parse_version(version)
                newer = order > layout.parse_version(current)
            except ValueError:
                continue
            entry.update(current=version == current,
                         installed=version == current or (installed and self._prepared(version)),
                         failed=bool(st is not None and version in st.failed), newer=newer)
            result.append((order, entry))
        result.sort(key=lambda item: item[0], reverse=True)
        return {"versions": [entry for _order, entry in result], "error": error, "current": current,
                "installed": installed, "channel": channel}

    def check(self, service=None) -> state_mod.UpdateStatus:
        self._write(state="checking", error=None)
        try:
            manifest, source = self._fetch()
        except Exception as exc:  # noqa: BLE001 (Zustand nie auf "checking" stehen lassen)
            err = exc if isinstance(exc, UpdateError) else UpdateError(
                "update.source_unreachable", _t("Update-Prüfung fehlgeschlagen ({name})", name=type(exc).__name__),
                hint=_t("Update-Quelle prüfen, später erneut versuchen."))
            if err is not exc:
                log.error("Update-Prüfung: unerwarteter Fehler: %s", exc)
            self._write(last_check=self.now().isoformat(timespec="seconds"))
            self._fail(err)
            if err is exc:
                raise
            raise err from exc
        cfg = self._cfg()
        channel = str(setting(cfg, "update.channel"))
        st = self._state() if self.installed() else None
        available = None
        if manifest is not None and manifest.kind != KIND_PYTHON:
            log.info("Update-Quelle bietet %s nur als portablen Build an, nicht über Python", manifest.version)
        elif manifest is not None and (channel == "beta" or manifest.channel == "stable") \
                and self._offerable(manifest.version, self._current(), st):
            available = {"version": manifest.version, "notes": manifest.notes, "published": manifest.published,
                         "size": 0, "packages": len(manifest.packages)}
            self._cache = (manifest.version, manifest, source)
        ready = bool(available and st is not None and self._prepared(available["version"]))
        self._write(state="ready" if ready else "idle", error=None, available=available,
                    last_check=self.now().isoformat(timespec="seconds"))
        return self.status(service)

    # ---------- Bereitstellen ----------

    def _require_installed(self) -> tuple[Path, layout.InstallState]:
        if not self.installed():
            raise UpdateError("update.not_installed", _t(NOT_INSTALLED_MESSAGE))
        root = self.root()
        st = self._state()
        assert root is not None and st is not None
        return root, st

    def _prepared(self, version: str) -> bool:
        root = self.root()
        st = self._state()
        if root is None or st is None:
            return False
        return version in st.versions and layout.is_complete_version(layout.version_dir(version, root))

    def _check_newer(self, version: str, st: layout.InstallState, explicit: bool = False) -> bool:
        """Ohne `explicit` nur neuere Versionen (kein Downgrade bzw. Replay einer älteren, gültig
        signierten Version). Mit `explicit` (Versionsauswahl) auch ältere, nie die aktive. Liefert,
        ob es ein Zurückgehen ist."""
        current = st.current or self.app_version()
        try:
            newer = layout.parse_version(version) > layout.parse_version(current)
            same = layout.parse_version(version) == layout.parse_version(current)
        except ValueError:
            raise UpdateError("update.apply_failed", _t("Versionsangabe {version} ungültig", version=version)) from None
        if same:
            raise UpdateError("update.apply_failed", _t("Version {version} ist bereits installiert", version=version))
        if not newer and not explicit:
            raise UpdateError("update.apply_failed", _t("Version {version} ist nicht neuer als die installierte Version {current}", version=version, current=current), hint=_t("Ältere Versionen nur ausdrücklich über die Versionsauswahl bzw. die Rückstellung."))
        return not newer

    def is_downgrade(self, version: str) -> bool:
        try:
            return layout.parse_version(version) < layout.parse_version(self._current())
        except ValueError:
            return False

    def prepare(self, version: str, *, explicit: bool = False) -> Path:
        """Laden, Prüfsumme, Entpacken, Selbsttest, Umbenennen. Zustand `downloading` → `ready`.
        `explicit` (Versionsauswahl): auch ältere Versionen und Vorabversionen.

        Prozessweit nur eine Bereitstellung zugleich (`_PREPARE_LOCK`): API-Knopf und Addon haben je
        einen eigenen Dienst und teilen sich sonst den Staging-Ordner."""
        with _PREPARE_LOCK:
            return self._prepare(version, explicit)

    def _base_python(self, root: Path, st: layout.InstallState) -> tuple[Path, str]:
        """Basis-Python der aktuellen Installation (pyvenv.cfg der aktiven Version, sonst
        `install.json`, sonst das laufende) und seine Version (`3.11`)."""
        current_dir = layout.version_dir(st.current, root) if st.current else None
        python = venv_mod.python_of_env(current_dir) if current_dir is not None else None
        if python is None and st.python and Path(st.python).is_file():
            python = Path(st.python)
        if python is None:
            python = venv_mod.base_python()
        pyver = venv_mod.python_version_of_env(current_dir) if current_dir is not None else None
        return python, pyver or f"{sys.version_info[0]}.{sys.version_info[1]}"

    def _prepare(self, version: str, explicit: bool = False) -> Path:
        lock_file: Path | None = None
        try:
            root, st = self._require_installed()
            self._check_newer(version, st, explicit)
            if version in st.failed:
                raise UpdateError("update.apply_failed", _t("Version {version} ist früher gescheitert und wird nicht erneut installiert", version=version))
            if self._prepared(version):
                self._write(state="ready", error=None)
                return layout.version_dir(version, root)
            self._write(state="downloading", error=None)
            channel = str(setting(self._cfg(), "update.channel"))
            if self._cache is None or self._cache[0] != version:
                # genau diese Version holen; die Signatur wird dabei immer geprüft
                manifest, source = self._fetch(version)
                if manifest is None or manifest.version != version:
                    raise UpdateError("update.download_failed", _t("Version {version} ist in der Quelle nicht (mehr) verfügbar", version=version))
                self._cache = (version, manifest, source)
            _v, manifest, source = self._cache
            if channel != "beta" and manifest.channel != "stable" and not explicit:
                raise UpdateError("update.download_failed", _t("Version {version} gehört zum Kanal {channel}, eingestellt ist {channel2}", version=version, channel=manifest.channel, channel2=channel))
            if manifest.kind != KIND_PYTHON:
                raise UpdateError("update.source_invalid", _t("Version {version} gibt es nur als portablen Build, nicht über Python", version=version))
            python, pyver = self._base_python(root, st)
            if pyver not in manifest.python:
                raise UpdateError("update.apply_failed",
                                  _t("Version {version} unterstützt Python {items}, installiert ist Python {pyver}", version=version, items=", ".join(manifest.python), pyver=pyver),
                                  hint=_t("Python aktualisieren und Tapesmith neu installieren (py -m tapesmith install)."))
            downloads = root / "downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            lock_file = downloads / f"lock-{version}.txt"
            lock_file.write_text(lock_text(manifest), encoding="utf-8")
            options = source.pip_options() if hasattr(source, "pip_options") else {}
            spec = venv_mod.PipSpec(lock_file=lock_file, **options)
            try:
                venv_mod.provision(root, version, python=python, spec=spec, run=self.run)
            except venv_mod.ProvisionError as exc:
                log.error("Bereitstellung von %s gescheitert (%s): %s %s", version, exc.step, exc, exc.output)
                if exc.step == "selftest":
                    self._mark_failed(root, version)
                    raise UpdateError("update.apply_failed", _t("Selbsttest der Version {version} fehlgeschlagen", version=version)) from exc
                if exc.step == "pip" and "DO NOT MATCH THE HASHES" in exc.output.upper():
                    raise UpdateError("update.checksum_mismatch",
                                      _t("Ein Paket für {version} passt nicht zur Prüfsumme im signierten Manifest", version=version),
                                      hint=_t("Update-Quelle prüfen; veränderte Pakete werden nie installiert.")) from exc
                if exc.step == "pip" and "NO MATCHING DISTRIBUTION FOUND FOR TAPESMITH==" in exc.output.upper():
                    # PyPI verteilt ein neues Release erst nach einigen Minuten über alle Spiegel
                    raise UpdateError("update.download_failed",
                                      _t("Version {version} ist auf PyPI noch nicht abrufbar", version=version),
                                      hint=_t("Das Release ist wohl gerade erst erschienen; in ein paar Minuten erneut versuchen.")) from exc
                if exc.step == "pip":
                    raise UpdateError("update.download_failed",
                                      _t("Pakete für {version} nicht installierbar: {exc}", version=version, exc=exc),
                                      hint=_t("Netzwerk prüfen, später erneut versuchen.")) from exc
                raise UpdateError("update.apply_failed", _t("Bereitstellung von {version} fehlgeschlagen: {exc}", version=version, exc=exc)) from exc
            try:
                installer.register_version(version, root)
            except OSError:
                shutil.rmtree(layout.version_dir(version, root), ignore_errors=True)
                raise
            target = layout.version_dir(version, root)
        except (UpdateError, OSError) as exc:
            if isinstance(exc, UpdateError):
                self._fail(exc)
                raise
            err = UpdateError("update.apply_failed",
                              _t("Bereitstellung von {version} fehlgeschlagen ({name})", version=version, name=type(exc).__name__),
                              hint=_t("Speicherplatz und Virenscanner prüfen, dann erneut versuchen."))
            log.error("Bereitstellung von %s fehlgeschlagen: %s", version, exc)
            self._fail(err)
            raise err from exc
        finally:
            if lock_file is not None:
                lock_file.unlink(missing_ok=True)
        self._write(state="ready", error=None)
        return target

    def _mark_failed(self, root: Path, version: str) -> None:
        st = layout.read_state(root)
        if st is None or version in st.failed:
            return
        layout.write_state(layout.InstallState(current=st.current, previous=st.previous, versions=list(st.versions),
                                               failed=[*st.failed, version], installed_at=st.installed_at,
                                               channel=st.channel), root)

    # ---------- Installieren, Rückstellung ----------

    def _apply_argv(self, root: Path, st: layout.InstallState) -> list[str]:
        """Updater aus dem echten Ordner der aktiven Version (nie über `current`): das Umstellen
        der Junction berührt ihn so nicht."""
        pythonw = layout.venv_python(layout.version_dir(st.current, root), gui=True)
        return [str(pythonw), "-m", APPLY_MODULE]

    def start_install(self, version: str, reopen_route: str | None = None, *, explicit: bool = False) -> list[str]:
        """Startet `versions\\<aktuelle>\\Scripts\\pythonw.exe -m tapesmith.update.apply --version V`
        losgelöst. Beim ausdrücklichen Zurückgehen auf eine ältere Version vorher eine Sicherung
        der Benutzerdaten; scheitert sie, wird nicht umgestellt."""
        try:
            root, st = self._require_installed()
            downgrade = self._check_newer(version, st, explicit)
            if version in st.failed:
                raise UpdateError("update.apply_failed", _t("Version {version} ist früher gescheitert und wird nicht erneut installiert", version=version))
            if not self._prepared(version):
                raise UpdateError("update.apply_failed", _t("Version {version} ist nicht bereitgestellt", version=version))
            if downgrade:
                try:
                    saved = self.backup(self._cfg())
                except Exception as exc:  # noqa: BLE001
                    log.error("Sicherung vor dem Zurückgehen auf %s fehlgeschlagen: %s", version, exc)
                    raise UpdateError("update.apply_failed",
                                      _t("Sicherung vor dem Zurückgehen auf {version} fehlgeschlagen, nichts umgestellt", version=version),
                                      hint=_t("Speicherort der Sicherungen prüfen und erneut versuchen.")) from exc
                log.info("Zurückgehen auf %s, Sicherung: %s", version, saved)
        except UpdateError as exc:
            self._fail(exc)
            raise
        argv = self._apply_argv(root, st) + ["--version", version, "--root", str(root)]
        if reopen_route:
            argv += ["--reopen-route", reopen_route]
        self._write(state="installing", error=None)
        self.spawn(argv)
        return argv

    def start_rollback(self, reopen_route: str | None = None) -> list[str]:
        try:
            root, st = self._require_installed()
            if not st.previous or st.previous in st.failed or not layout.version_dir(st.previous, root).is_dir():
                raise UpdateError("update.apply_failed", _t("Keine vorige Version zum Zurückstellen vorhanden"))
        except UpdateError as exc:
            self._fail(exc)
            raise
        argv = self._apply_argv(root, st) + ["--rollback", "--root", str(root)]
        if reopen_route:
            argv += ["--reopen-route", reopen_route]
        self._write(state="installing", error=None)
        self.spawn(argv)
        return argv

    # ---------- Leerlauf ----------

    def idle_ok(self, service) -> bool:
        """Dienst frei, seit `update.idle_min` Minuten im Leerlauf und kein Lebenszeichen einer
        Oberfläche in den letzten 120 s."""
        if service is None:
            return False
        try:
            if service.busy():
                return False
            since = service.idle_since()
        except Exception:  # noqa: BLE001
            return False
        if since is None:
            return False
        now = self.clock()
        idle_min = float(setting(self._cfg(), "update.idle_min"))
        if now - since < idle_min * 60:
            return False
        beat = self.heartbeat()
        return not (beat is not None and now - beat < IDLE_HEARTBEAT_S)
