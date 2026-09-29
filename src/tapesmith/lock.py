"""Prozessübergreifende Drucksperre (Windows Named Mutex), bis der Druckdienst p12d existiert."""

import ctypes
import os
from tapesmith.i18n import _t

WAIT_OBJECT_0 = 0x0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102
WAIT_FAILED = 0xFFFFFFFF


class PrinterBusy(RuntimeError):
    pass


class PrintLock:
    def __init__(self, name: str | None = None, timeout_s: float = 0.0):
        # TAPESMITH_LOCK_NAME trennt parallel laufende Test-Suites voneinander
        self.name = name or os.environ.get("TAPESMITH_LOCK_NAME", "Local\\Tapesmith.Print")
        self.timeout_s = timeout_s
        self._handle = None
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateMutexW.restype = ctypes.c_void_p
        self._k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self._k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._k32.WaitForSingleObject.restype = ctypes.c_uint32
        self._k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self._k32.CloseHandle.argtypes = [ctypes.c_void_p]

    def __enter__(self):
        handle = self._k32.CreateMutexW(None, False, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), _t("CreateMutexW fehlgeschlagen"))
        result = self._k32.WaitForSingleObject(handle, int(self.timeout_s * 1000))
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            pass
        elif result == WAIT_TIMEOUT:
            self._k32.CloseHandle(handle)
            raise PrinterBusy(_t("Drucker ist belegt, ein anderes P12-Programm druckt gerade"))
        else:
            self._k32.CloseHandle(handle)
            raise OSError(ctypes.get_last_error(), _t("WaitForSingleObject fehlgeschlagen (0x{result:08x})", result=result))
        self._handle = handle
        return self

    def __exit__(self, *exc):
        self._k32.ReleaseMutex(self._handle)
        self._k32.CloseHandle(self._handle)
        self._handle = None
        return False
