"""BLE-Transport für den P12 ohne Windows-Kopplung (experimentell).

Der P12 spricht über GATT: Service `0xFF00`, Schreiben ohne Antwort auf `0xFF02`, Statusantworten
per Notify auf `0xFF03`. Ob BLE am P12 zuverlässig funktioniert, ist bisher nur eine Vermutung
(nicht am Gerät verifiziert), deshalb ist dieser Transport ausdrücklich als experimentell markiert.

BLE und die vorhandene Bluetooth-SPP-Verbindung (`serial_port.SerialTransport`) laufen **nie**
gleichzeitig: pro Sitzung existiert genau ein Transport, und der gemeinsame `lock.PrintLock`
verhindert wie bisher, dass zwei Programme gleichzeitig auf den Drucker zugreifen. BLE braucht
dafür keinen eigenen Mechanismus.

`bleak` wird nur bei tatsächlicher Nutzung (lazy) importiert, damit das Modul auch ohne die
Bibliothek geladen werden kann; fehlt sie, meldet `BleakBackend` das als `TransportError`.
"""

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import N_, _t

BLE_SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb"
BLE_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"
BLE_NOTIFY = "0000ff03-0000-1000-8000-00805f9b34fb"
DEFAULT_NAMES = ("P12", "P12 PRO", "P12PRO")
CHUNK_BYTES = 128
CHUNK_PAUSE_S = 0.02
EXPERIMENTAL_NOTE = N_("BLE-Transport ist experimentell (am P12 noch nicht belegt)")

_BLEAK_IMPORT_ERROR = N_("bleak fehlt, BLE-Transport nicht verfügbar (siehe requirements)")


@dataclass(frozen=True)
class BleDevice:
    name: str | None
    address: str
    rssi: int | None = None


def normalize_address(address: str) -> str:
    """"001122334455" / "00-11-22-33-44-55" / "00:11:22:33:44:55" -> "00:11:22:33:44:55"."""
    normalized = "".join(ch for ch in address if ch.isalnum()).upper()
    if len(normalized) != 12 or not all(ch in "0123456789ABCDEF" for ch in normalized):
        raise ValueError(_t("Ungültige BLE-Adresse: {address!r}", address=address))
    return ":".join(normalized[i:i + 2] for i in range(0, 12, 2))


def matches(device: BleDevice, names: Sequence[str], address: str | None) -> bool:
    """`address` gesetzt: nur Adressvergleich. Sonst: Name (casefold) exakt oder als Präfix."""
    if address is not None:
        return device.address.casefold() == address.casefold()
    if device.name is None:
        return False
    name = device.name.casefold()
    return any(name == n.casefold() or name.startswith(n.casefold()) for n in names)


class BleBackend(Protocol):
    """Kapselt bleak (asyncio) hinter einer synchronen Schnittstelle; in Tests ein Fake."""

    def scan(self, timeout_s: float) -> list[BleDevice]: ...

    def connect(self, address: str, timeout_s: float) -> None: ...

    def start_notify(self, char_uuid: str, callback: Callable[[bytes], None]) -> None: ...

    def write(self, char_uuid: str, data: bytes, response: bool) -> None: ...

    def disconnect(self) -> None: ...


class BleakBackend:
    """Produktions-Backend: eigene asyncio-Eventloop in einem Daemon-Thread, Aufrufe per
    `asyncio.run_coroutine_threadsafe(...).result(timeout)`. `bleak` wird lazy importiert."""

    def __init__(self) -> None:
        self._loop = None
        self._thread: threading.Thread | None = None
        self._client = None

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        import asyncio

        ready = threading.Event()
        box: dict = {}

        def runner() -> None:
            loop = asyncio.new_event_loop()
            box["loop"] = loop
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(target=runner, daemon=True, name="p12-ble-loop")
        thread.start()
        ready.wait()
        self._loop = box["loop"]
        self._thread = thread

    def _run(self, coro, timeout: float):
        import asyncio

        self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    def scan(self, timeout_s: float) -> list[BleDevice]:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise TransportError(_t(_BLEAK_IMPORT_ERROR)) from exc

        async def _scan() -> list[BleDevice]:
            found = await BleakScanner.discover(timeout=timeout_s, return_adv=True)
            return [BleDevice(dev.name, addr, adv.rssi) for addr, (dev, adv) in found.items()]

        return self._run(_scan(), timeout_s + 5)

    def connect(self, address: str, timeout_s: float) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise TransportError(_t(_BLEAK_IMPORT_ERROR)) from exc

        async def _connect() -> None:
            client = BleakClient(address)
            await client.connect(timeout=timeout_s)
            self._client = client

        self._run(_connect(), timeout_s + 5)

    def start_notify(self, char_uuid: str, callback: Callable[[bytes], None]) -> None:
        async def _start() -> None:
            await self._client.start_notify(char_uuid, lambda _char, data: callback(bytes(data)))

        self._run(_start(), 10)

    def write(self, char_uuid: str, data: bytes, response: bool) -> None:
        async def _write() -> None:
            await self._client.write_gatt_char(char_uuid, data, response=response)

        self._run(_write(), 10)

    def disconnect(self) -> None:
        if self._client is None:
            return

        async def _disconnect() -> None:
            await self._client.disconnect()

        self._run(_disconnect(), 10)


def scan_devices(timeout_s: float = 8.0, *, backend: "BleBackend | None" = None) -> list[BleDevice]:
    backend = backend or BleakBackend()
    return backend.scan(timeout_s)


class BleTransport:
    supports_responses = True

    def __init__(self, address: str | None = None, *, names: Sequence[str] = DEFAULT_NAMES,
                 scan_timeout_s: float = 8.0, open_timeout: float = 10.0,
                 backend_factory: Callable[[], "BleBackend"] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.address = address
        self.names = tuple(names)
        self.scan_timeout_s = scan_timeout_s
        self.open_timeout = open_timeout
        self._backend_factory = backend_factory or BleakBackend
        self._sleep = sleep
        self.name = f"ble:{address}" if address else "ble"
        self._backend: "BleBackend | None" = None
        self._opened = False
        self._cond = threading.Condition()
        self._buffer = bytearray()

    def _on_notify(self, data: bytes) -> None:
        with self._cond:
            self._buffer.extend(data)
            self._cond.notify_all()

    def open(self) -> None:
        backend = self._backend_factory()
        address = self.address
        if address is None:
            devices = backend.scan(self.scan_timeout_s)
            found = next((d for d in devices if matches(d, self.names, None)), None)
            if found is None:
                raise ConnectTimeout(
                    _t("Kein P12 per BLE gefunden. Drucker an? Handy-App und Windows-Kopplung (COM) trennen"))
            address = found.address
        try:
            backend.connect(address, self.open_timeout)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(f"BLE {address}: {exc}") from exc
        backend.start_notify(BLE_NOTIFY, self._on_notify)
        self._backend = backend
        self.address = address
        self.name = f"ble:{address}"
        self._opened = True

    def write(self, data: bytes) -> None:
        if not self._opened or self._backend is None:
            raise TransportError(_t("{name} nicht geöffnet", name=self.name))
        chunks = [data[i:i + CHUNK_BYTES] for i in range(0, len(data), CHUNK_BYTES)] or [b""]
        try:
            for i, chunk in enumerate(chunks):
                self._backend.write(BLE_WRITE, chunk, False)
                if i < len(chunks) - 1:
                    self._sleep(CHUNK_PAUSE_S)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(_t("BLE {address}: Schreiben fehlgeschlagen: {exc}", address=self.address, exc=exc)) from exc

    def read(self, timeout: float) -> bytes:
        with self._cond:
            if not self._buffer:
                self._cond.wait(timeout)
            if not self._buffer:
                return b""
        time.sleep(0.05)  # kurz auf Nachzügler warten (Muster wie serial_port.SerialTransport)
        with self._cond:
            data, self._buffer = bytes(self._buffer), bytearray()
        return data

    def close(self) -> None:
        if self._backend is not None:
            backend, self._backend = self._backend, None
            backend.disconnect()
        self._opened = False
