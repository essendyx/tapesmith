"""Laufende Tapesmith-Prozesse finden und beenden: Installer/Updater dürfen
nicht in ein Verzeichnis schreiben, das eine laufende EXE gerade offen hält.

`list_processes` nutzt nur `ctypes` (kein pywin32): `psapi.EnumProcesses`,
`kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`, `QueryFullProcessImageNameW`.
Prozesse ohne Zugriffsrecht werden übersprungen, nicht als Fehler behandelt."""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from tapesmith.i18n import _t

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
_INITIAL_ARRAY_SIZE = 1024


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    exe: str


def _normpath(path: object) -> str:
    text = os.path.normpath(str(path))
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return text.rstrip("\\").upper()


def list_processes() -> list[ProcessInfo]:
    """Alle für diesen Benutzer sichtbaren Prozesse mit ausführbarem Pfad. Prozesse ohne
    Zugriffsrecht (`OpenProcess`/`QueryFullProcessImageNameW` schlägt fehl) werden übersprungen."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    size = _INITIAL_ARRAY_SIZE
    while True:
        pids = (wintypes.DWORD * size)()
        needed = wintypes.DWORD()
        ok = psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed))
        if not ok:
            raise OSError(ctypes.get_last_error(), _t("EnumProcesses fehlgeschlagen"))
        count = needed.value // ctypes.sizeof(wintypes.DWORD)
        if count < size:
            break
        size *= 2

    result: list[ProcessInfo] = []
    for pid in pids[:count]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            buf_len = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
                result.append(ProcessInfo(pid=int(pid), exe=buf.value))
        finally:
            kernel32.CloseHandle(handle)
    return result


def processes_under(root: Path, *, lister: Callable[[], list[ProcessInfo]] = list_processes,
                    exclude_pids: Iterable[int] = ()) -> list[ProcessInfo]:
    """Prozesse aus `lister()`, deren Pfad unter `root` oder dem aufgelösten Ziel von
    `root\\current` liegt (normalisiert: Groß/Klein egal, `\\?\\`-Präfix entfernt)."""
    from tapesmith.install import junction, layout

    root = Path(root)
    roots = {_normpath(root)}
    target = junction.read_junction(layout.current_link(root))
    if target is not None:
        roots.add(_normpath(target))
    exclude = set(exclude_pids)

    result = []
    for proc in lister():
        if proc.pid in exclude:
            continue
        exe_norm = _normpath(proc.exe)
        if any(exe_norm == base or exe_norm.startswith(base + "\\") for base in roots):
            result.append(proc)
    return result


def stop_daemon(cfg: dict, *, timeout_s: float = 15.0, connect=None) -> bool:
    """Beendet den Druckdienst über IPC `shutdown` (nicht erzwungen). `True`: kein Dienst
    erreichbar oder er hat sich innerhalb `timeout_s` beendet. `False`: er ist belegt
    (`stopping: False`) oder beendet sich nicht rechtzeitig."""
    from tapesmith.config import setting
    from tapesmith.ipc.client import DaemonClient
    from tapesmith.ipc.pipe import DaemonUnavailable

    connector = connect or DaemonClient.connect
    connect_timeout = float(setting(cfg, "daemon.connect_timeout_s"))
    try:
        client = connector(client="cli", timeout_s=connect_timeout)
    except DaemonUnavailable:
        return True

    try:
        result = client.call("shutdown", {"force": False})
    finally:
        client.close()
    if not result.get("stopping", False):
        return False

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            probe = connector(client="cli", timeout_s=0.3)
        except DaemonUnavailable:
            return True
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return False


def _default_kill(pid: int, timeout_s: float) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return True  # kein Zugriff bzw. existiert schon nicht mehr
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
        waited = kernel32.WaitForSingleObject(handle, int(max(timeout_s, 0.0) * 1000))
        return waited == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def terminate(pids: Iterable[int], *, timeout_s: float = 5.0,
             killer: Callable[[int, float], bool] | None = None) -> list[int]:
    """Beendet `pids` (`OpenProcess(PROCESS_TERMINATE)` + `TerminateProcess`, dann
    `WaitForSingleObject`). Gibt die übrig gebliebenen PIDs zurück."""
    kill = killer or _default_kill
    remaining = []
    for pid in pids:
        try:
            ok = kill(pid, timeout_s)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            remaining.append(pid)
    return remaining
