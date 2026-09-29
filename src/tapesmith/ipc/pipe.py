"""Named Pipe zwischen Clients und Druckdienst p12d (ctypes, kein pywin32).

Die Pipe `\\\\.\\pipe\\tapesmith-<home_key>` ist lokal (PIPE_REJECT_REMOTE_CLIENTS), die erste Instanz
wird mit FILE_FLAG_FIRST_PIPE_INSTANCE erzeugt (kein Pipe-Squatting) und die DACL erlaubt nur dem
aktuellen Benutzer den Zugriff. Alle Ein-/Ausgaben laufen overlapped, damit `close()`/`stop()`
blockierende Aufrufe sofort beenden.
"""

from __future__ import annotations

import ctypes
import functools
import hashlib
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Protocol, runtime_checkable

from tapesmith import paths
from tapesmith.ipc.protocol import (
    PROTOCOL_VERSION,
    IpcError,
    ProtocolError,
    check_message,
    decode_line,
    encode_line,
    error_message,
    hello,
    welcome,
)
from tapesmith.ipc import protocol as _protocol
from tapesmith.i18n import _t

__all__ = [
    "IpcError", "ProtocolError", "DaemonUnavailable", "ChannelClosed", "PipeInUse",
    "home_key", "pipe_name", "daemon_mutex_name", "Channel", "PipeChannel", "PipeServer", "connect",
    "memory_channel_pair", "current_user_sid", "pipe_dacl_sids", "client_handshake", "server_handshake",
]

log = logging.getLogger(__name__)


class DaemonUnavailable(IpcError):
    """Druckdienst nicht erreichbar."""


class ChannelClosed(IpcError):
    """Gegenstelle hat die Verbindung geschlossen (oder der Kanal wurde geschlossen)."""


class PipeInUse(IpcError):
    """Pipe existiert schon: ein anderer Druckdienst läuft."""


# ---------- Namen ----------

def home_key(home: Path | None = None) -> str:
    base = Path(home or paths.app_dir()).resolve()
    text = os.path.normcase(str(base)) + "|" + os.environ.get("USERNAME", "")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def pipe_name(home: Path | None = None) -> str:
    return os.environ.get("TAPESMITH_PIPE_NAME") or r"\\.\pipe\tapesmith-" + home_key(home)


def daemon_mutex_name(home: Path | None = None) -> str:
    return os.environ.get("TAPESMITH_DAEMON_MUTEX") or "Local\\Tapesmith.Daemon." + home_key(home)


# ---------- Win32 ----------

PIPE_ACCESS_DUPLEX = 0x3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0
PIPE_READMODE_BYTE = 0
PIPE_WAIT = 0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
READ_CONTROL = 0x00020000
OPEN_EXISTING = 3
ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_NO_DATA = 232
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_PIPE_CONNECTED = 535
ERROR_OPERATION_ABORTED = 995
ERROR_IO_PENDING = 997
ERROR_INSUFFICIENT_BUFFER = 122
SDDL_REVISION_1 = 1
SE_KERNEL_OBJECT = 6
DACL_SECURITY_INFORMATION = 4
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF
BUFFER_SIZE = 65536
READ_CHUNK = 65536

_CLOSED_ERRORS = (ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_NOT_CONNECTED, ERROR_OPERATION_ABORTED)
_INVALID_HANDLE = ctypes.c_void_p(-1).value

HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
BOOL = wintypes.BOOL


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", DWORD), ("OffsetHigh", DWORD), ("hEvent", HANDLE)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", BOOL)]


def _bind(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


class _Win32:
    def __init__(self) -> None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        P = ctypes.POINTER
        self.CreateNamedPipeW = _bind(k32, "CreateNamedPipeW", HANDLE, wintypes.LPCWSTR, DWORD, DWORD, DWORD,
                                      DWORD, DWORD, DWORD, P(SECURITY_ATTRIBUTES))
        self.ConnectNamedPipe = _bind(k32, "ConnectNamedPipe", BOOL, HANDLE, P(OVERLAPPED))
        self.DisconnectNamedPipe = _bind(k32, "DisconnectNamedPipe", BOOL, HANDLE)
        self.CreateFileW = _bind(k32, "CreateFileW", HANDLE, wintypes.LPCWSTR, DWORD, DWORD,
                                 ctypes.c_void_p, DWORD, DWORD, HANDLE)
        self.WaitNamedPipeW = _bind(k32, "WaitNamedPipeW", BOOL, wintypes.LPCWSTR, DWORD)
        self.ReadFile = _bind(k32, "ReadFile", BOOL, HANDLE, ctypes.c_void_p, DWORD, P(DWORD), P(OVERLAPPED))
        self.WriteFile = _bind(k32, "WriteFile", BOOL, HANDLE, ctypes.c_void_p, DWORD, P(DWORD), P(OVERLAPPED))
        self.GetOverlappedResult = _bind(k32, "GetOverlappedResult", BOOL, HANDLE, P(OVERLAPPED), P(DWORD), BOOL)
        self.CancelIoEx = _bind(k32, "CancelIoEx", BOOL, HANDLE, P(OVERLAPPED))
        self.CreateEventW = _bind(k32, "CreateEventW", HANDLE, ctypes.c_void_p, BOOL, BOOL, wintypes.LPCWSTR)
        self.SetEvent = _bind(k32, "SetEvent", BOOL, HANDLE)
        self.WaitForMultipleObjects = _bind(k32, "WaitForMultipleObjects", DWORD, DWORD, P(HANDLE), BOOL, DWORD)
        self.WaitForSingleObject = _bind(k32, "WaitForSingleObject", DWORD, HANDLE, DWORD)
        self.CloseHandle = _bind(k32, "CloseHandle", BOOL, HANDLE)
        self.LocalFree = _bind(k32, "LocalFree", ctypes.c_void_p, ctypes.c_void_p)
        self.GetCurrentProcess = _bind(k32, "GetCurrentProcess", HANDLE)
        self.OpenProcessToken = _bind(adv, "OpenProcessToken", BOOL, HANDLE, DWORD, P(HANDLE))
        self.GetTokenInformation = _bind(adv, "GetTokenInformation", BOOL, HANDLE, ctypes.c_int,
                                         ctypes.c_void_p, DWORD, P(DWORD))
        self.ConvertSidToStringSidW = _bind(adv, "ConvertSidToStringSidW", BOOL, ctypes.c_void_p,
                                            P(ctypes.c_void_p))
        self.ConvertStringSecurityDescriptorToSecurityDescriptorW = _bind(
            adv, "ConvertStringSecurityDescriptorToSecurityDescriptorW", BOOL, wintypes.LPCWSTR, DWORD,
            P(ctypes.c_void_p), P(wintypes.ULONG))
        self.GetSecurityInfo = _bind(adv, "GetSecurityInfo", DWORD, HANDLE, ctypes.c_int, DWORD,
                                     P(ctypes.c_void_p), P(ctypes.c_void_p), P(ctypes.c_void_p),
                                     P(ctypes.c_void_p), P(ctypes.c_void_p))
        self.GetAce = _bind(adv, "GetAce", BOOL, ctypes.c_void_p, DWORD, P(ctypes.c_void_p))


@functools.lru_cache(maxsize=1)
def _w() -> _Win32:
    return _Win32()


def _err() -> int:
    return ctypes.get_last_error()


def _event() -> int:
    handle = _w().CreateEventW(None, True, False, None)
    if not handle:
        raise IpcError(_t("CreateEventW fehlgeschlagen ({err})", err=_err()))
    return handle


def _wait_two(first: int, second: int, timeout_ms: int) -> int:
    handles = (HANDLE * 2)(first, second)
    return _w().WaitForMultipleObjects(2, handles, False, timeout_ms)


def _sid_to_string(psid) -> str:
    out = ctypes.c_void_p()
    if not _w().ConvertSidToStringSidW(psid, ctypes.byref(out)):
        raise IpcError(_t("ConvertSidToStringSidW fehlgeschlagen ({err})", err=_err()))
    try:
        return ctypes.wstring_at(out.value)
    finally:
        _w().LocalFree(out.value)


@functools.lru_cache(maxsize=1)
def current_user_sid() -> str:
    w = _w()
    token = HANDLE()
    if not w.OpenProcessToken(w.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise IpcError(_t("OpenProcessToken fehlgeschlagen ({err})", err=_err()))
    try:
        size = DWORD()
        w.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not w.GetTokenInformation(token, TOKEN_USER_CLASS, buf, size, ctypes.byref(size)):
            raise IpcError(_t("GetTokenInformation fehlgeschlagen ({err})", err=_err()))
        psid = ctypes.c_void_p.from_buffer(buf).value   # TOKEN_USER.User.Sid
        return _sid_to_string(psid)
    finally:
        w.CloseHandle(token)


def _dacl_sids_of_handle(handle: int) -> list[str]:
    w = _w()
    pdacl = ctypes.c_void_p()
    psd = ctypes.c_void_p()
    rc = w.GetSecurityInfo(handle, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                           ctypes.byref(pdacl), None, ctypes.byref(psd))
    if rc != 0:
        raise IpcError(_t("GetSecurityInfo fehlgeschlagen ({rc})", rc=rc))
    try:
        if not pdacl.value:
            return []   # NULL-DACL: jeder hat Zugriff
        count = ctypes.c_uint16.from_address(pdacl.value + 4).value   # ACL.AceCount
        sids: list[str] = []
        for index in range(count):
            pace = ctypes.c_void_p()
            if not w.GetAce(pdacl, index, ctypes.byref(pace)):
                raise IpcError(_t("GetAce fehlgeschlagen ({err})", err=_err()))
            sids.append(_sid_to_string(pace.value + 8))   # ACE_HEADER (4) + Mask (4) -> SidStart
        return sids
    finally:
        w.LocalFree(psd.value)


_SERVERS: dict[str, "PipeServer"] = {}
_SERVERS_LOCK = threading.Lock()


def pipe_dacl_sids(name: str) -> list[str]:
    """SIDs aller ACEs der DACL einer offenen Pipe (für Tests und Selbsttest).

    Läuft der Server im selben Prozess, wird das Handle der wartenden Instanz gelesen. Sonst öffnet
    die Funktion kurz ein Client-Handle mit READ_CONTROL; das zählt beim Server als Verbindung
    (Handler läuft an und sieht sofort ChannelClosed).
    """
    with _SERVERS_LOCK:
        server = _SERVERS.get(name.lower())
    if server is not None:
        sids = server._dacl_sids()
        if sids is not None:
            return sids
    w = _w()
    handle = w.CreateFileW(name, READ_CONTROL, 0, None, OPEN_EXISTING, 0, None)
    if handle in (None, _INVALID_HANDLE):
        raise DaemonUnavailable(_t("Pipe {name} nicht geöffnet ({err})", name=name, err=_err()))
    try:
        return _dacl_sids_of_handle(handle)
    finally:
        w.CloseHandle(handle)


def _create_instance(name: str, first: bool, max_instances: int) -> int:
    w = _w()
    psd = ctypes.c_void_p()
    sddl = f"D:P(A;;GA;;;{current_user_sid()})"
    if not w.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SDDL_REVISION_1, ctypes.byref(psd), None):
        raise IpcError(_t("Sicherheitsbeschreibung fehlgeschlagen ({err})", err=_err()))
    try:
        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd.value, False)
        mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0)
        handle = w.CreateNamedPipeW(name, mode,
                                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                    max_instances, BUFFER_SIZE, BUFFER_SIZE, 0, ctypes.byref(sa))
        err = _err()
    finally:
        w.LocalFree(psd.value)
    if handle in (None, _INVALID_HANDLE):
        if first and err in (ERROR_ACCESS_DENIED, ERROR_PIPE_BUSY):
            raise PipeInUse(_t("Pipe {name} existiert bereits. Läuft schon ein Druckdienst?", name=name))
        raise IpcError(_t("CreateNamedPipeW fehlgeschlagen ({err})", err=err))
    return handle


# ---------- Kanäle ----------

@runtime_checkable
class Channel(Protocol):
    def send(self, msg: dict) -> None: ...
    def recv(self, timeout: float | None = None) -> dict | None: ...
    def close(self) -> None: ...

    @property
    def closed(self) -> bool: ...


def _timeout_ms(deadline: float | None) -> int:
    if deadline is None:
        return INFINITE
    return max(0, int((deadline - time.monotonic()) * 1000 + 0.999))


class _LineBuffer:
    """Sammelt Bytes und liefert vollständige Zeilen (ohne `\\n`)."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._scan = 0

    def feed(self, data: bytes) -> None:
        self._data += data

    def pop(self) -> bytes | None:
        while True:
            idx = self._data.find(b"\n", self._scan)
            if idx < 0:
                self._scan = len(self._data)
                if len(self._data) > _protocol.MAX_LINE_BYTES:
                    raise ProtocolError(_t("Nachricht zu groß (über {max_line_bytes} Bytes)", max_line_bytes=_protocol.MAX_LINE_BYTES))
                return None
            line = bytes(self._data[:idx])
            del self._data[:idx + 1]
            self._scan = 0
            if line.strip():
                return line


class PipeChannel:
    """Kanal über ein overlapped geöffnetes Pipe-HANDLE (Server- oder Client-Seite)."""

    def __init__(self, handle: int, name: str = ""):
        self.name = name
        self._h = handle
        self._send_lock = threading.Lock()
        self._recv_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._eof = False
        self._lines = _LineBuffer()
        self._events: list[int] = []
        try:
            self._close_ev = self._new_event()
            self._read_ev = self._new_event()
            self._write_ev = self._new_event()
        except BaseException:
            for ev in self._events:
                _w().CloseHandle(ev)
            _w().CloseHandle(handle)
            raise
        self._read_ov = OVERLAPPED()
        self._read_ov.hEvent = self._read_ev
        self._read_buf = ctypes.create_string_buffer(READ_CHUNK)
        self._read_pending = False

    def _new_event(self) -> int:
        ev = _event()
        self._events.append(ev)
        return ev

    def __enter__(self) -> PipeChannel:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    # --- Senden ---

    def send(self, msg: dict) -> None:
        data = encode_line(msg)
        if self._closed:
            raise ChannelClosed(_t("Kanal ist geschlossen"))
        with self._send_lock:
            if self._closed:
                raise ChannelClosed(_t("Kanal ist geschlossen"))
            buf = ctypes.create_string_buffer(data, len(data))
            base = ctypes.addressof(buf)
            offset = 0
            while offset < len(data):
                offset += self._write(base + offset, len(data) - offset)

    def _write(self, address: int, size: int) -> int:
        w = _w()
        ov = OVERLAPPED()
        ov.hEvent = self._write_ev
        done = DWORD()
        if not w.WriteFile(self._h, address, size, None, ctypes.byref(ov)):
            err = _err()
            if err != ERROR_IO_PENDING:
                if err in _CLOSED_ERRORS:
                    raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
                raise IpcError(_t("WriteFile fehlgeschlagen ({err})", err=err))
        if _wait_two(self._write_ev, self._close_ev, INFINITE) != WAIT_OBJECT_0:
            w.CancelIoEx(self._h, ctypes.byref(ov))
            w.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(done), True)
            raise ChannelClosed(_t("Kanal wurde geschlossen"))
        if not w.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(done), False):
            err = _err()
            if err in _CLOSED_ERRORS:
                raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
            raise IpcError(_t("WriteFile fehlgeschlagen ({err})", err=err))
        return done.value

    # --- Empfangen ---

    def recv(self, timeout: float | None = None) -> dict | None:
        if self._closed:
            raise ChannelClosed(_t("Kanal ist geschlossen"))
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._recv_lock:
            while True:
                if self._closed:
                    raise ChannelClosed(_t("Kanal ist geschlossen"))
                line = self._lines.pop()
                if line is not None:
                    return decode_line(line)
                if self._eof:
                    raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
                if not self._read_pending:
                    self._start_read()
                result = _wait_two(self._read_ev, self._close_ev, _timeout_ms(deadline))
                if result == WAIT_OBJECT_0:
                    self._finish_read()
                elif result == WAIT_OBJECT_0 + 1:
                    raise ChannelClosed(_t("Kanal wurde geschlossen"))
                elif result == WAIT_TIMEOUT:
                    return None
                else:
                    raise IpcError(_t("Warten auf die Pipe fehlgeschlagen ({err})", err=_err()))

    def _start_read(self) -> None:
        if not _w().ReadFile(self._h, self._read_buf, READ_CHUNK, None, ctypes.byref(self._read_ov)):
            err = _err()
            if err != ERROR_IO_PENDING:
                if err in _CLOSED_ERRORS:
                    self._eof = True
                    raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
                raise IpcError(_t("ReadFile fehlgeschlagen ({err})", err=err))
        self._read_pending = True

    def _finish_read(self) -> None:
        got = DWORD()
        ok = _w().GetOverlappedResult(self._h, ctypes.byref(self._read_ov), ctypes.byref(got), False)
        self._read_pending = False
        if not ok:
            err = _err()
            if err in _CLOSED_ERRORS:
                self._eof = True
                raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
            raise IpcError(_t("ReadFile fehlgeschlagen ({err})", err=err))
        if got.value:
            self._lines.feed(ctypes.string_at(self._read_buf, got.value))

    # --- Schließen ---

    def close(self) -> None:
        w = _w()
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            w.SetEvent(self._close_ev)
            w.CancelIoEx(self._h, None)
        with self._recv_lock:
            if self._read_pending:
                got = DWORD()
                w.GetOverlappedResult(self._h, ctypes.byref(self._read_ov), ctypes.byref(got), True)
                self._read_pending = False
        with self._send_lock:
            w.CloseHandle(self._h)
            for ev in self._events:
                w.CloseHandle(ev)
            self._events = []


# ---------- Server ----------

class PipeServer:
    """Nimmt Verbindungen an; je Verbindung ein Daemon-Thread mit `handler(channel)`."""

    def __init__(self, name: str, handler: Callable[[Channel], None], *, max_instances: int = 16):
        self._name = name
        self._handler = handler
        self._max = max_instances
        self._lock = threading.Lock()
        self._listen: int | None = None
        self._channels: set[PipeChannel] = set()
        self._threads: set[threading.Thread] = set()
        self._accept: threading.Thread | None = None
        self._stop_ev: int | None = None
        self._connect_ev: int | None = None
        self._started = False
        self._stopping = False

    @property
    def name(self) -> str:
        return self._name

    def active_channels(self) -> int:
        with self._lock:
            return sum(1 for ch in self._channels if not ch.closed)

    def start(self) -> None:
        if self._started:
            raise IpcError(_t("Pipe-Server läuft bereits"))
        listen = _create_instance(self._name, True, self._max)
        try:
            self._stop_ev = _event()
            self._connect_ev = _event()
        except BaseException:
            _w().CloseHandle(listen)
            for ev in (self._stop_ev, self._connect_ev):
                if ev:
                    _w().CloseHandle(ev)
            raise
        self._listen = listen
        self._started = True
        with _SERVERS_LOCK:
            _SERVERS[self._name.lower()] = self
        self._accept = threading.Thread(target=self._accept_loop, name="tapesmith-pipe-accept", daemon=True)
        self._accept.start()

    def _dacl_sids(self) -> list[str] | None:
        with self._lock:
            if self._listen is None:
                return None
            return _dacl_sids_of_handle(self._listen)

    def _accept_loop(self) -> None:
        w = _w()
        try:
            while not self._stopping:
                with self._lock:
                    handle = self._listen
                if handle is None:
                    try:
                        handle = _create_instance(self._name, False, self._max)
                    except IpcError:
                        if w.WaitForSingleObject(self._stop_ev, 50) == WAIT_OBJECT_0:
                            break
                        continue
                    with self._lock:
                        self._listen = handle
                connected = self._wait_connect(handle)
                if connected is None:
                    break
                if not connected:
                    if not w.DisconnectNamedPipe(handle):
                        with self._lock:
                            self._listen = None
                        w.CloseHandle(handle)
                    continue
                try:
                    channel = PipeChannel(handle, self._name)
                except IpcError:
                    log.exception("Pipe-Kanal konnte nicht angelegt werden")
                    with self._lock:
                        self._listen = None
                    continue
                try:
                    successor = _create_instance(self._name, False, self._max)
                except IpcError:
                    successor = None
                with self._lock:
                    self._listen = successor
                    if self._stopping:
                        stale = channel
                        thread = None
                    else:
                        stale = None
                        self._channels.add(channel)
                        thread = threading.Thread(target=self._serve, args=(channel,),
                                                  name="tapesmith-pipe-conn", daemon=True)
                        self._threads.add(thread)
                if stale is not None:
                    stale.close()
                    break
                thread.start()
        finally:
            with self._lock:
                handle, self._listen = self._listen, None
            if handle is not None:
                w.CloseHandle(handle)

    def _wait_connect(self, handle: int) -> bool | None:
        """True = Client verbunden, False = Fehlversuch, None = Stopp."""
        w = _w()
        ov = OVERLAPPED()
        ov.hEvent = self._connect_ev
        done = DWORD()
        if w.ConnectNamedPipe(handle, ctypes.byref(ov)):
            return True
        err = _err()
        if err == ERROR_PIPE_CONNECTED:
            return True
        if err != ERROR_IO_PENDING:
            return False
        if _wait_two(self._connect_ev, self._stop_ev, INFINITE) == WAIT_OBJECT_0:
            return bool(w.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), False))
        w.CancelIoEx(handle, ctypes.byref(ov))
        w.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), True)
        return None

    def _serve(self, channel: PipeChannel) -> None:
        try:
            self._handler(channel)
        except ChannelClosed:
            pass
        except Exception:
            log.exception("Fehler im Pipe-Handler")
        finally:
            channel.close()
            with self._lock:
                self._channels.discard(channel)
                self._threads.discard(threading.current_thread())

    def stop(self, timeout_s: float = 2.0) -> None:
        with self._lock:
            if not self._started or self._stopping:
                return
            self._stopping = True
            channels = list(self._channels)
        deadline = time.monotonic() + timeout_s
        _w().SetEvent(self._stop_ev)
        for channel in channels:
            channel.close()
        if self._accept is not None:
            self._accept.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        with _SERVERS_LOCK:
            if _SERVERS.get(self._name.lower()) is self:
                del _SERVERS[self._name.lower()]
        if self._accept is None or not self._accept.is_alive():
            for ev in (self._stop_ev, self._connect_ev):
                _w().CloseHandle(ev)
            self._stop_ev = self._connect_ev = None
        else:
            log.warning("Pipe-Server %s: Annahme-Thread endet nicht rechtzeitig", self._name)


# ---------- Client ----------

def connect(name: str, timeout_s: float = 2.0) -> PipeChannel:
    w = _w()
    deadline = time.monotonic() + timeout_s
    last = 0
    while True:
        handle = w.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING,
                               FILE_FLAG_OVERLAPPED, None)
        if handle not in (None, _INVALID_HANDLE):
            return PipeChannel(handle, name)
        last = _err()
        remaining = deadline - time.monotonic()
        if last not in (ERROR_FILE_NOT_FOUND, ERROR_PIPE_BUSY) or remaining <= 0:
            break
        if last == ERROR_PIPE_BUSY:
            w.WaitNamedPipeW(name, max(1, min(int(remaining * 1000), 500)))
        else:
            time.sleep(min(0.05, remaining))
    if last == ERROR_ACCESS_DENIED:
        raise DaemonUnavailable(_t("Druckdienst nicht erreichbar (Zugriff verweigert, anderer Benutzer?)"))
    raise DaemonUnavailable(_t("Druckdienst nicht erreichbar ({name}, Fehler {last})", name=name, last=last))


# ---------- Kanäle im Speicher (Tests) ----------

_EOF = object()
_WAKE = object()


class _MemoryChannel:
    def __init__(self) -> None:
        self._inbox: queue.Queue = queue.Queue()
        self._peer: _MemoryChannel | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._eof = False

    @property
    def closed(self) -> bool:
        return self._closed

    def send(self, msg: dict) -> None:
        data = encode_line(msg)
        with self._lock:
            if self._closed:
                raise ChannelClosed(_t("Kanal ist geschlossen"))
            peer = self._peer
            if peer is None or peer._closed:
                raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
            peer._inbox.put(data)

    def recv(self, timeout: float | None = None) -> dict | None:
        if self._closed:
            raise ChannelClosed(_t("Kanal ist geschlossen"))
        if self._eof:
            raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
        try:
            item = self._inbox.get(timeout=None if timeout is None else max(0.0, timeout))
        except queue.Empty:
            return None
        if self._closed or item is _WAKE:
            raise ChannelClosed(_t("Kanal wurde geschlossen"))
        if item is _EOF:
            self._eof = True
            raise ChannelClosed(_t("Gegenstelle hat die Verbindung geschlossen"))
        return decode_line(item.rstrip(b"\n"))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._inbox.put(_WAKE)
        if self._peer is not None:
            self._peer._inbox.put(_EOF)


def memory_channel_pair() -> tuple[Channel, Channel]:
    a, b = _MemoryChannel(), _MemoryChannel()
    a._peer, b._peer = b, a
    return a, b


# ---------- Handshake ----------

def client_handshake(ch: Channel, client: str, *, home: str | None = None, timeout_s: float = 2.0) -> dict:
    key = home if home is not None else home_key()
    ch.send(hello(client, key))
    try:
        msg = ch.recv(timeout=timeout_s)
    except ChannelClosed as exc:
        raise DaemonUnavailable(_t("Druckdienst hat die Verbindung beim Handshake geschlossen")) from exc
    if msg is None:
        raise DaemonUnavailable(_t("Druckdienst antwortet nicht (Handshake)"))
    check_message(msg)
    if msg["type"] == "error":
        raise ProtocolError(msg["message"])
    if msg["type"] != "welcome":
        raise ProtocolError(_t("Handshake: 'welcome' erwartet, '{type}' erhalten", type=msg['type']))
    if msg["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError(_t("Protokoll {protocol} des Dienstes nicht unterstützt (Client spricht {protocol_version})", protocol=msg['protocol'], protocol_version=PROTOCOL_VERSION))
    if msg["home"] != key:
        raise ProtocolError(_t("Druckdienst gehört zu einem anderen App-Verzeichnis"))
    return msg


def server_handshake(ch: Channel, *, home: str | None = None, timeout_s: float = 5.0) -> dict:
    key = home if home is not None else home_key()
    msg = ch.recv(timeout=timeout_s)
    if msg is None:
        raise ProtocolError(_t("Handshake: kein 'hello' erhalten"))
    try:
        check_message(msg)
        if msg["type"] != "hello":
            raise ProtocolError(_t("Handshake: 'hello' erwartet, '{type}' erhalten", type=msg['type']))
    except ProtocolError as exc:
        _send_quietly(ch, error_message("protocol", str(exc)))
        raise
    if msg["protocol"] != PROTOCOL_VERSION:
        text = _t("Protokoll {protocol} nicht unterstützt (Dienst spricht {protocol_version})", protocol=msg['protocol'], protocol_version=PROTOCOL_VERSION)
        _send_quietly(ch, error_message("protocol", text))
        raise ProtocolError(text)
    if msg["home"] != key:
        text = _t("Falsches App-Verzeichnis: dieser Druckdienst gehört zu einem anderen TAPESMITH_HOME")
        _send_quietly(ch, error_message("home", text))
        raise ProtocolError(text)
    ch.send(welcome(key))
    return msg


def _send_quietly(ch: Channel, msg: dict) -> None:
    try:
        ch.send(msg)
    except IpcError:
        pass
