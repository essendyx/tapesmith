"""Bluetooth-SPP über den ausgehenden Windows-COM-Port."""

import threading
import time

import serial

from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import _t


class SerialTransport:
    def __init__(self, port: str, open_timeout: float = 8.0):
        self.port = port
        self.name = port
        self.open_timeout = open_timeout
        self._ser = None
        self._lock = threading.Lock()
        self._timed_out = False

    def open(self) -> None:
        result: dict = {}

        def worker():
            try:
                ser = serial.Serial(self.port, timeout=0.5, write_timeout=10)
                with self._lock:
                    if self._timed_out:
                        ser.close()
                        return
                    result["ser"] = ser
            except Exception as exc:  # pyserial wirft SerialException/OSError
                result["err"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(self.open_timeout)
        if thread.is_alive():
            with self._lock:
                self._timed_out = True
            raise ConnectTimeout(
                _t("{port}: keine Verbindung nach {open_timeout:.0f} s. Drucker an und in Reichweite?", port=self.port, open_timeout=self.open_timeout))
        if "err" in result:
            raise TransportError(f"{self.port}: {result['err']}")
        self._ser = result.get("ser")

    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise TransportError(_t("{port}: nicht geöffnet", port=self.port))
        try:
            self._ser.write(data)
            self._ser.flush()
        except (serial.SerialException, OSError) as exc:
            raise TransportError(_t("{port}: Schreiben fehlgeschlagen: {exc}", port=self.port, exc=exc)) from exc

    def read(self, timeout: float) -> bytes:
        if self._ser is None:
            raise TransportError(_t("{port}: nicht geöffnet", port=self.port))
        try:
            self._ser.timeout = timeout
            first = self._ser.read(1)
            if not first:
                return b""
            time.sleep(0.05)
            return first + self._ser.read(self._ser.in_waiting)
        except (serial.SerialException, OSError) as exc:
            raise TransportError(_t("{port}: Lesen fehlgeschlagen: {exc}", port=self.port, exc=exc)) from exc

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None
