"""Atomar schreiben (temp + os.replace) und prozessübergreifende Dateisperre (Windows-Byte-Lock)."""

import msvcrt
import os
import tempfile
import threading
import time
from pathlib import Path
from tapesmith.i18n import _t

_REPLACE_RETRIES = 10
_REPLACE_RETRY_DELAY_S = 0.05


class FileLockTimeout(TimeoutError):
    pass


# Threads desselben Prozesses warten blockierend auf einen Lock pro Datei, statt den Byte-Lock
# unfair zu pollen (sonst kann ein Thread auf einem langsamen Rechner bis zum Timeout verhungern)
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _atomic_write(path: Path, write) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False)
    tmp_path = Path(tmp.name)
    try:
        write(tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_RETRY_DELAY_S)
    except BaseException:
        if not tmp.closed:
            tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    _atomic_write(path, lambda tmp: tmp.write(data))


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_write(path, lambda tmp: tmp.write(text.encode(encoding)))


class FileLock:
    def __init__(self, path: Path, timeout_s: float = 5.0, poll_s: float = 0.05):
        self.path = Path(path)
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._fh = None
        self._thread_lock = _thread_lock(self.path)

    def __enter__(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout_s
        if not self._thread_lock.acquire(timeout=self.timeout_s):
            raise FileLockTimeout(
                _t("Datei gesperrt: {path}, ein anderes P12-Programm schreibt gerade", path=self.path))
        try:
            self._lock_file(deadline)
        except BaseException:
            self._thread_lock.release()
            raise
        return self

    def _lock_file(self, deadline: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise FileLockTimeout(
                        _t("Datei gesperrt: {path}, ein anderes P12-Programm schreibt gerade", path=self.path))
                time.sleep(self.poll_s)
        self._fh = fh

    def __exit__(self, *exc) -> bool:
        self._fh.seek(0)
        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        self._fh.close()
        self._fh = None
        self._thread_lock.release()
        return False
