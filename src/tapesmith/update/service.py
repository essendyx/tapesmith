"""`UpdateService`: Prüfen, Bereitstellen, Installation starten, Rückstellung und Leerlauf-Regel
für Web-API, CLI und Addon.

Nicht installiert (portabel oder Entwicklung): `status()` meldet `installed: false`, `check()`
zeigt trotzdem die verfügbare Version, `prepare`/`start_install`/`start_rollback` werfen
`update.not_installed`. Versionen aus `install.json` `failed` werden nie angeboten."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tapesmith import launch
from tapesmith.config import setting
from tapesmith.install import layout
from tapesmith.update import stage
from tapesmith.update import state as state_mod
from tapesmith.update.download import verify_package
from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import Manifest, parse_manifest
from tapesmith.update.signing import load_trusted_keys, verify
from tapesmith.update.sources import parse_source
from tapesmith.i18n import N_, _t

log = logging.getLogger("tapesmith.update")

IDLE_HEARTBEAT_S = 120.0
_PREPARE_LOCK = threading.Lock()
NOT_INSTALLED_MESSAGE = (N_("Portable Version oder Entwicklung: Updates nur in der installierten App. Installieren mit Installieren.cmd aus dem Zip."))


def _app_version() -> str:
    from tapesmith import __version__

    return __version__


def _default_heartbeat() -> float | None:
    from tapesmith.webapi.drafts import last_heartbeat

    return last_heartbeat()


class UpdateService:
    def __init__(self, cfg_loader: Callable[[], dict], *, source_factory=parse_source,
                 keys_loader=load_trusted_keys, root: Path | None = None,
                 spawn: Callable = launch.spawn_detached, run: Callable = subprocess.run,
                 now: Callable[[], datetime] = datetime.now, transport=None,
                 executable: str | None = None, clock: Callable[[], float] = time.monotonic,
                 heartbeat: Callable[[], float | None] = _default_heartbeat,
                 app_version: Callable[[], str] = _app_version):
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
        self._cache: tuple[str, Manifest, object] | None = None

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
            consent_needed=bool(installed and not enabled and not setting(cfg, "update.asked")))

    def _offerable(self, version: str, current: str, st: layout.InstallState | None) -> bool:
        try:
            newer = layout.parse_version(version) > layout.parse_version(current)
        except ValueError:
            return False
        return newer and (st is None or version not in st.failed)

    # ---------- Prüfen ----------

    def _fetch(self) -> tuple[Manifest | None, object]:
        """Manifest laden und Signatur prüfen. (None, Quelle): kein Release in der Quelle."""
        cfg = self._cfg()
        source = self.source_factory(str(setting(cfg, "update.source")), transport=self.transport,
                                     channel=str(setting(cfg, "update.channel")))
        fetched = source.fetch_manifest()
        if fetched is None:
            return None, source
        data, signature = fetched
        verify(data, signature, self.keys_loader())
        manifest = parse_manifest(data)
        return manifest, source

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
        if manifest is not None and (channel == "beta" or manifest.channel == "stable") \
                and self._offerable(manifest.version, self._current(), st):
            available = {"version": manifest.version, "notes": manifest.notes, "published": manifest.published,
                         "size": manifest.size}
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
        return version in st.versions and (layout.version_dir(version, root) / layout.APP_EXE).is_file()

    def _check_newer(self, version: str, st: layout.InstallState) -> None:
        """Nur neuere Versionen (kein Downgrade bzw. Replay einer älteren, gültig signierten Version)."""
        current = st.current or self.app_version()
        try:
            newer = layout.parse_version(version) > layout.parse_version(current)
        except ValueError:
            newer = False
        if not newer:
            raise UpdateError("update.apply_failed", _t("Version {version} ist nicht neuer als die installierte Version {current}", version=version, current=current), hint=_t("Zurück auf eine ältere Version nur über die Rückstellung."))

    def prepare(self, version: str) -> Path:
        """Laden, Prüfsumme, Entpacken, Selbsttest, Umbenennen. Zustand `downloading` → `ready`.

        Prozessweit nur eine Bereitstellung zugleich (`_PREPARE_LOCK`): API-Knopf und Addon haben je
        einen eigenen Dienst und teilen sich sonst den Staging-Ordner."""
        with _PREPARE_LOCK:
            return self._prepare(version)

    def _prepare(self, version: str) -> Path:
        staging: Path | None = None
        try:
            root, st = self._require_installed()
            self._check_newer(version, st)
            if version in st.failed:
                raise UpdateError("update.apply_failed", _t("Version {version} ist früher gescheitert und wird nicht erneut installiert", version=version))
            if self._prepared(version):
                self._write(state="ready", error=None)
                return layout.version_dir(version, root)
            self._write(state="downloading", error=None)
            channel = str(setting(self._cfg(), "update.channel"))
            if self._cache is None or self._cache[0] != version:
                manifest, source = self._fetch()
                if manifest is None or manifest.version != version:
                    raise UpdateError("update.download_failed", _t("Version {version} ist in der Quelle nicht (mehr) verfügbar", version=version))
                self._cache = (version, manifest, source)
            _v, manifest, source = self._cache
            if channel != "beta" and manifest.channel != "stable":
                raise UpdateError("update.download_failed", _t("Version {version} gehört zum Kanal {channel}, eingestellt ist {channel2}", version=version, channel=manifest.channel, channel2=channel))
            downloads = root / "downloads"
            package = source.download(manifest.file, downloads / manifest.file)
            try:
                verify_package(package, manifest)
                staging = stage.staging_dir(version, root)
                stage.extract(package, version, root)
            finally:
                package.unlink(missing_ok=True)
            if not stage.smoke(staging, run=self.run):
                shutil.rmtree(staging, ignore_errors=True)
                self._mark_failed(root, version)
                raise UpdateError("update.apply_failed", _t("Selbsttest der Version {version} fehlgeschlagen", version=version))
            target = stage.finalize(staging, version, root)
        except (UpdateError, OSError) as exc:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, UpdateError):
                self._fail(exc)
                raise
            err = UpdateError("update.apply_failed",
                              _t("Bereitstellung von {version} fehlgeschlagen ({name})", version=version, name=type(exc).__name__),
                              hint=_t("Speicherplatz und Virenscanner prüfen, dann erneut versuchen."))
            log.error("Bereitstellung von %s fehlgeschlagen: %s", version, exc)
            self._fail(err)
            raise err from exc
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

    def _apply_exe(self, root: Path, st: layout.InstallState) -> str:
        return str(layout.version_dir(st.current, root) / layout.APP_EXE)

    def start_install(self, version: str, reopen_route: str | None = None) -> list[str]:
        """Startet `versions\\<aktuelle>\\Tapesmith.exe --update-apply --version V …` losgelöst."""
        try:
            root, st = self._require_installed()
            self._check_newer(version, st)
            if not self._prepared(version):
                raise UpdateError("update.apply_failed", _t("Version {version} ist nicht bereitgestellt", version=version))
        except UpdateError as exc:
            self._fail(exc)
            raise
        argv = [self._apply_exe(root, st), "--update-apply", "--version", version, "--root", str(root)]
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
        argv = [self._apply_exe(root, st), "--update-apply", "--rollback", "--root", str(root)]
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
