"""Transporte: Speicher (Tests), Datei (Trockenlauf) und Hex-Log-Hülle."""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from tapesmith.protocol.status import StatusCodes, decode
from tapesmith.i18n import _t


class TransportError(RuntimeError):
    pass


class ConnectTimeout(TransportError):
    pass


class Transport(Protocol):
    name: str

    def open(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...
    def close(self) -> None: ...


class MemoryTransport:
    name = "memory"
    supports_responses = True

    def __init__(self, responses: dict[bytes, bytes] | None = None):
        self.responses = dict(responses or {})
        self.written: list[bytes] = []
        self.opened = False
        self.closed = False
        self._pending = b""

    def open(self) -> None:
        self.opened = True

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))
        self._pending = self.responses.get(bytes(data), b"")

    def read(self, timeout: float) -> bytes:
        data, self._pending = self._pending, b""
        return data

    def close(self) -> None:
        self.closed = True


class FileTransport:
    supports_responses = False

    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = f"file:{self.path}"
        self._fh = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "wb")

    def write(self, data: bytes) -> None:
        self._fh.write(data)

    def read(self, timeout: float) -> bytes:
        return b""

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class HexLogTransport:
    def __init__(self, inner: Transport, log_path: Path, codes: StatusCodes | None = None):
        self.inner = inner
        self.name = inner.name
        self.log_path = Path(log_path)
        self.codes = codes

    @property
    def supports_responses(self) -> bool:
        return getattr(self.inner, "supports_responses", True)

    def _log(self, line: str) -> None:
        stamp = datetime.now().isoformat(timespec="milliseconds")
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")

    def open(self) -> None:
        try:
            self.inner.open()
        except Exception as exc:
            self._log(_t("OPEN-FEHLER {name}: {exc}", name=self.inner.name, exc=exc))
            raise
        try:
            self._log(f"OPEN {self.inner.name}")
        except Exception:
            self.inner.close()
            raise

    def write(self, data: bytes) -> None:
        self._log(f"TX {data.hex(' ')}")
        self.inner.write(data)

    def read(self, timeout: float) -> bytes:
        data = self.inner.read(timeout)
        if data:
            texts = ", ".join(m.text for m in decode(data, self.codes))
            self._log(f"RX {data.hex(' ')}  # {texts}")
        else:
            self._log(f"RX (timeout {timeout} s)")
        return data

    def close(self) -> None:
        self.inner.close()
        self._log("CLOSE")
