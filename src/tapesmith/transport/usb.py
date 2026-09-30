"""USB-Erkennung und -Transport für den P12 (experimentell).

Ob der P12 überhaupt über USB druckt, ist unbelegt (unbekannt, ob das USB-Kabel nur lädt oder auch
eine Datenschnittstelle anbietet). Deshalb ist dieser Transport nur nutzbar, wenn er im
Geräteprofil ausdrücklich als `"usb"` unter `experimental` eingetragen ist (siehe
`transport/resolve.py`). Erkennung/Diagnose liest nur die Registry (nie schreibend), der Transport
selbst spricht (falls vorhanden) die Windows-`usbprint`-Geräteschnittstelle an.
"""

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

from tapesmith.doctor import Check
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import N_, _t

USB_VID = 0x4C4A
USB_PID = 0x4155
GUID_DEVINTERFACE_USBPRINT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
EXPERIMENTAL_NOTE = N_("USB-Transport ist experimentell: ob der P12 über USB druckt, ist unbelegt")

_VIDPID = f"VID_{USB_VID:04X}&PID_{USB_PID:04X}"


@dataclass(frozen=True)
class UsbDevice:
    instance: str
    service: str | None
    friendly_name: str | None
    class_name: str | None
    present: bool | None = None


def _read_usb_registry() -> list[dict]:
    """Liest nur lesend HKLM\\...\\Enum\\USB\\VID_xxxx&PID_yyyy* (Muster wie btports._read_registry).
    Auf Rechnern, an denen nie ein USB-Gerät hing (etwa virtuelle Maschinen), fehlt der Schlüssel
    Enum\\USB ganz: dann ist kein Gerät bekannt."""
    import winreg

    rows: list[dict] = []
    root = r"SYSTEM\CurrentControlSet\Enum\USB"
    try:
        usb_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
    except FileNotFoundError:
        return rows
    with usb_key:
        for i in range(winreg.QueryInfoKey(usb_key)[0]):
            vidpid = winreg.EnumKey(usb_key, i)
            if not vidpid.upper().startswith(_VIDPID):
                continue
            with winreg.OpenKey(usb_key, vidpid) as vidpid_key:
                for j in range(winreg.QueryInfoKey(vidpid_key)[0]):
                    instance = winreg.EnumKey(vidpid_key, j)
                    try:
                        with winreg.OpenKey(vidpid_key, instance) as inst_key:
                            def _get(name: str):
                                try:
                                    value, _ = winreg.QueryValueEx(inst_key, name)
                                    return value
                                except OSError:
                                    return None

                            rows.append({
                                "instance": f"USB\\{vidpid}\\{instance}",
                                "service": _get("Service"),
                                "friendly_name": _get("FriendlyName") or _get("DeviceDesc"),
                                "class": _get("Class"),
                            })
                    except OSError:
                        continue
    return rows


def find_usb_devices(reader: Callable[[], list[dict]] | None = None) -> list[UsbDevice]:
    rows = (reader or _read_usb_registry)()
    return [UsbDevice(
        instance=row["instance"],
        service=row.get("service"),
        friendly_name=row.get("friendly_name"),
        class_name=row.get("class"),
        present=row.get("present"),
    ) for row in rows]


def diagnose_usb(devices: Sequence[UsbDevice]) -> list[str]:
    if not devices:
        return [_t("Kein P12 per USB bekannt, per USB-Kabel anstecken und einschalten")]
    lines = []
    for d in devices:
        service = (d.service or "").casefold()
        klass = (d.class_name or "").casefold()
        if service == "usbprint":
            lines.append(_t("{instance}: Druckerschnittstelle (usbprint), USB-Transport möglich (experimentell)", instance=d.instance))
        elif service == "usbser" or klass == "ports":
            lines.append(_t("{instance}: virtueller COM-Port (CDC), als COMn nutzbar", instance=d.instance))
        elif service == "hidusb" or klass == "hidclass":
            lines.append(_t("{instance}: HID-Gerät, kein Druckweg implementiert", instance=d.instance))
        else:
            lines.append(_t("{instance}: Dienst {value}, unbekannt", instance=d.instance, value=d.service or '-'))
    return lines


def usb_check(reader: Callable[[], list[dict]] | None = None) -> Check:
    """USB ist experimentell und nie Voraussetzung zum Drucken: deshalb immer `ok`, auch wenn die
    Geräteliste nicht lesbar ist (dann steht der Grund im Detail)."""
    try:
        devices = find_usb_devices(reader)
    except OSError as exc:
        return Check(_t("USB (experimentell)"), True, _t("USB-Geräteliste nicht lesbar: {exc}", exc=exc))
    return Check(_t("USB (experimentell)"), True, "; ".join(diagnose_usb(devices)))


# ---------- SetupAPI: usbprint-Geräteschnittstellen (nur lesend, real nur am Gerät geprüft) ----------

_DIGCF_PRESENT = 0x2
_DIGCF_DEVICEINTERFACE = 0x10
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_str(guid: str) -> _GUID:
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(guid, ctypes.byref(g))
    return g


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(wintypes.ULONG)),
    ]


def _real_usbprint_paths() -> list[str]:
    """SetupDiGetClassDevsW + SetupDiEnumDeviceInterfaces + SetupDiGetDeviceInterfaceDetailW
    über die Geräteschnittstelle GUID_DEVINTERFACE_USBPRINT. Ungetestet am echten Gerät
    (Hardware-Prüfung 4); Tests injizieren immer einen `enumerator`."""
    setupapi = ctypes.windll.setupapi
    guid = _guid_from_str(GUID_DEVINTERFACE_USBPRINT)
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                      _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE)
    if not h or h == _INVALID_HANDLE_VALUE:
        return []
    paths: list[str] = []
    try:
        index = 0
        while True:
            did = _SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(_SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(guid), index, ctypes.byref(did)):
                break
            required = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(did), None, 0,
                                                      ctypes.byref(required), None)
            if required.value:
                buf = ctypes.create_string_buffer(required.value)
                cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(cb_size)), 4)
                if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(did), buf, required, None, None):
                    paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
            index += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return paths


def list_usbprint_paths(enumerator: Callable[[], list[str]] | None = None) -> list[str]:
    paths = (enumerator or _real_usbprint_paths)()
    return [p for p in paths if "vid_4c4a&pid_4155" in p.casefold()]


class UsbHandle(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes: ...

    def close(self) -> None: ...


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_FILE_FLAG_OVERLAPPED = 0x40000000


class _RealUsbHandle:
    """Default-Opener über CreateFileW/WriteFile/ReadFile. Ungetestet am echten Gerät
    (Hardware-Prüfung 4); Tests injizieren immer einen `opener`."""

    def __init__(self, path: str) -> None:
        handle = ctypes.windll.kernel32.CreateFileW(
            path, _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None, _OPEN_EXISTING, _FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            raise TransportError(_t("USB {path}: Öffnen fehlgeschlagen (Fehler {get_last_error})", path=path, get_last_error=ctypes.get_last_error()))
        self._handle = handle

    def write(self, data: bytes) -> None:
        written = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.WriteFile(self._handle, data, len(data), ctypes.byref(written), None)
        if not ok:
            raise TransportError(_t("Schreiben fehlgeschlagen (Fehler {get_last_error})", get_last_error=ctypes.get_last_error()))

    def read(self, timeout: float) -> bytes:
        buf = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.ReadFile(self._handle, buf, len(buf), ctypes.byref(got), None)
        if not ok:
            return b""
        return buf.raw[:got.value]

    def close(self) -> None:
        ctypes.windll.kernel32.CloseHandle(self._handle)


def _open_usbprint_handle(path: str) -> UsbHandle:
    return _RealUsbHandle(path)


class UsbPrintTransport:
    supports_responses = True

    def __init__(self, path: str | None = None, *, open_timeout: float = 5.0,
                 opener: Callable[[str], UsbHandle] | None = None,
                 enumerator: Callable[[], list[str]] | None = None) -> None:
        self.path = path
        self.open_timeout = open_timeout
        self._opener = opener or _open_usbprint_handle
        self._enumerator = enumerator
        self._handle: UsbHandle | None = None
        self.name = f"usb:{path}" if path else "usb"

    def open(self) -> None:
        path = self.path
        if path is None:
            paths = list_usbprint_paths(self._enumerator)
            if not paths:
                raise ConnectTimeout(
                    _t("Kein P12 per USB (usbprint) gefunden. `p12 usb` zeigt, was Windows anbietet"))
            path = paths[0]
        try:
            handle = self._opener(path)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(f"USB {path}: {exc}") from exc
        self._handle = handle
        self.path = path
        self.name = f"usb:{path}"

    def write(self, data: bytes) -> None:
        if self._handle is None:
            raise TransportError(_t("{name} nicht geöffnet", name=self.name))
        try:
            self._handle.write(data)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(_t("USB {path}: Schreiben fehlgeschlagen: {exc}", path=self.path, exc=exc)) from exc

    def read(self, timeout: float) -> bytes:
        if self._handle is None:
            raise TransportError(_t("{name} nicht geöffnet", name=self.name))
        try:
            return self._handle.read(timeout)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(_t("USB {path}: Lesen fehlgeschlagen: {exc}", path=self.path, exc=exc)) from exc

    def close(self) -> None:
        if self._handle is not None:
            handle, self._handle = self._handle, None
            handle.close()
