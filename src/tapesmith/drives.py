"""Datenträger-Assistent: Wechseldatenträger erkennen (Bezeichnung, Kapazität,
Dateisystem) und ein Kurzetikett vorschlagen. Win32-API per ctypes (kein WMI, keine
Zusatzabhängigkeit), keine Adminrechte nötig. Kein Qt hier."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol
from tapesmith.i18n import _t

DRIVE_UNKNOWN = 0
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

BUS_USB = 7
BUS_SD = 0x0C
BUS_MMC = 0x0D

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
SEM_FAILCRITICALERRORS = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3

STANDARD_GB = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000, 2000, 4000, 8000)


@dataclass(frozen=True)
class DriveInfo:
    root: str               # "E:\\"
    label: str              # Datenträgerbezeichnung ("" wenn keine)
    size_bytes: int
    free_bytes: int
    filesystem: str         # "exFAT", "FAT32", "NTFS", "" (unbekannt)
    bus: str                # "usb" | "sd" | "unbekannt"
    removable: bool         # GetDriveType == DRIVE_REMOVABLE


class DrivesBackend(Protocol):
    def roots(self) -> list[str]: ...                       # GetLogicalDrives -> ["C:\\", "E:\\", …]

    def drive_type(self, root: str) -> int: ...              # GetDriveTypeW (2 = removable, 3 = fixed)

    def volume(self, root: str) -> tuple[str, str]: ...      # GetVolumeInformationW; nicht bereit -> OSError

    def space(self, root: str) -> tuple[int, int]: ...        # GetDiskFreeSpaceExW -> (total, free)

    def bus(self, root: str) -> str: ...                      # IOCTL_STORAGE_QUERY_PROPERTY


def _roots_from_mask(mask: int) -> list[str]:
    return [f"{chr(ord('A') + i)}:\\" for i in range(26) if mask & (1 << i)]


def _configure_kernel32() -> "ctypes.WinDLL":
    k = ctypes.windll.kernel32
    k.GetLogicalDrives.argtypes = []
    k.GetLogicalDrives.restype = wintypes.DWORD
    k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    k.GetDriveTypeW.restype = wintypes.UINT
    k.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
    ]
    k.GetVolumeInformationW.restype = wintypes.BOOL
    k.GetDiskFreeSpaceExW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
    ]
    k.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    k.SetErrorMode.argtypes = [wintypes.UINT]
    k.SetErrorMode.restype = wintypes.UINT
    k.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.DWORD, wintypes.HANDLE,
    ]
    k.CreateFileW.restype = wintypes.HANDLE
    k.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    k.DeviceIoControl.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


class WinDrivesBackend:
    """ctypes-Umsetzung des `DrivesBackend`-Protokolls. `volume` wirft `OSError`, wenn das
    Laufwerk nicht bereit ist (Kartenleser ohne Karte usw.); jede andere Einzelabfrage fängt
    `OSError` selbst ab und liefert neutrale Werte, statt `list_drives` abzubrechen."""

    def __init__(self) -> None:
        self._k = _configure_kernel32()

    def roots(self) -> list[str]:
        try:
            mask = self._k.GetLogicalDrives()
        except OSError:
            return []
        return _roots_from_mask(mask)

    def drive_type(self, root: str) -> int:
        try:
            return int(self._k.GetDriveTypeW(root))
        except OSError:
            return DRIVE_UNKNOWN

    def volume(self, root: str) -> tuple[str, str]:
        vol_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_component = wintypes.DWORD()
        flags = wintypes.DWORD()
        prev_mode = self._k.SetErrorMode(SEM_FAILCRITICALERRORS)
        try:
            ok = self._k.GetVolumeInformationW(
                root, vol_buf, len(vol_buf), ctypes.byref(serial), ctypes.byref(max_component),
                ctypes.byref(flags), fs_buf, len(fs_buf))
        finally:
            self._k.SetErrorMode(prev_mode)
        if not ok:
            raise OSError(ctypes.get_last_error(), _t("Laufwerk {root} nicht bereit", root=root))
        return vol_buf.value, fs_buf.value

    def space(self, root: str) -> tuple[int, int]:
        free_avail = ctypes.c_ulonglong()
        total = ctypes.c_ulonglong()
        total_free = ctypes.c_ulonglong()
        try:
            ok = self._k.GetDiskFreeSpaceExW(
                root, ctypes.byref(free_avail), ctypes.byref(total), ctypes.byref(total_free))
        except OSError:
            return 0, 0
        if not ok:
            return 0, 0
        return total.value, total_free.value

    def bus(self, root: str) -> str:
        path = f"\\\\.\\{root[:2]}"
        try:
            handle = self._k.CreateFileW(
                path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
            if not handle or handle == -1:
                return "unbekannt"
            try:
                query = (ctypes.c_uint32 * 3)(0, 0, 0)  # PropertyId=0, QueryType=0
                out_buf = ctypes.create_string_buffer(1024)
                returned = wintypes.DWORD()
                ok = self._k.DeviceIoControl(
                    handle, IOCTL_STORAGE_QUERY_PROPERTY, query, ctypes.sizeof(query),
                    out_buf, ctypes.sizeof(out_buf), ctypes.byref(returned), None)
                if not ok:
                    return "unbekannt"
                bus_type = ctypes.c_uint32.from_buffer_copy(out_buf.raw, 28).value
            finally:
                self._k.CloseHandle(handle)
        except OSError:
            return "unbekannt"
        if bus_type == BUS_USB:
            return "usb"
        if bus_type in (BUS_SD, BUS_MMC):
            return "sd"
        return "unbekannt"


def list_drives(backend: DrivesBackend | None = None, *, include_fixed_usb: bool = True) -> list[DriveInfo]:
    """Wechseldatenträger + (optional) feste Laufwerke mit Bus `usb`/`sd`; nicht bereite
    Laufwerke werden übersprungen; nie das Systemlaufwerk."""
    backend = backend if backend is not None else WinDrivesBackend()
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\").upper() + "\\"

    result: list[DriveInfo] = []
    for root in backend.roots():
        if root.upper() == system_drive:
            continue
        dtype = backend.drive_type(root)
        if dtype == DRIVE_REMOVABLE:
            removable = True
        elif dtype == DRIVE_FIXED:
            removable = False
        else:
            continue
        try:
            label, filesystem = backend.volume(root)
        except OSError:
            continue
        bus = backend.bus(root)
        if not removable and not (include_fixed_usb and bus in ("usb", "sd")):
            continue
        size_bytes, free_bytes = backend.space(root)
        result.append(DriveInfo(root=root, label=label, size_bytes=size_bytes, free_bytes=free_bytes,
                                filesystem=filesystem, bus=bus, removable=removable))
    return result


def marketing_size(size_bytes: int) -> str:
    gb = size_bytes / 1e9
    if gb < 1:
        return f"{round(size_bytes / 1e6)} MB"
    threshold = gb * 0.97
    for s in STANDARD_GB:
        if s >= threshold:
            return f"{s // 1000} TB" if s >= 1000 else f"{s} GB"
    return f"{round(gb / 1000)} TB"


def suggest_label(info: DriveInfo) -> tuple[str, str]:
    label = info.label.strip()
    if label:
        if label.isupper():
            label = " ".join(word.capitalize() for word in label.split())
    elif info.bus == "sd":
        label = _t("SD-Karte")
    elif info.removable:
        label = _t("USB-Stick")
    else:
        label = _t("USB-Platte")

    size_txt = marketing_size(info.size_bytes)
    line2 = f"{size_txt} · {info.filesystem}" if info.filesystem else size_txt
    return label, line2
