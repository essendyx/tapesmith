"""Wandelt eine Transportangabe ('auto', 'COM4', 'com:COM4', 'file:pfad', 'ble[:adresse]',
'usb[:pfad]') in einen Transport."""

import re
from collections.abc import Sequence
from pathlib import Path

from tapesmith.transport.base import FileTransport, HexLogTransport, Transport, TransportError
from tapesmith.transport.ble import DEFAULT_NAMES, BleTransport, normalize_address
from tapesmith.transport.btports import find_outgoing_port
from tapesmith.transport.serial_port import SerialTransport
from tapesmith.transport.usb import UsbPrintTransport
from tapesmith.i18n import _t


def open_transport(spec: str, mac: str | None, hexlog: Path | None = None, reader=None,
                   open_timeout: float = 8.0, *,
                   experimental: frozenset[str] | set[str] | tuple[str, ...] = frozenset(),
                   ble_names: Sequence[str] = DEFAULT_NAMES, ble_scan_timeout_s: float = 8.0,
                   ble_backend_factory=None, usb_opener=None) -> Transport:
    if spec == "auto":
        port = find_outgoing_port(mac, reader)
        if port is None and mac is None:
            raise TransportError(
                _t("Kein eindeutiger Bluetooth-COM-Port: ist der Drucker in Windows gekoppelt? Dann `tapesmith setup` ausführen (oder `tapesmith config set mac <MAC>`)"))
        if port is None:
            raise TransportError(
                _t("Kein ausgehender Bluetooth-COM-Port für {mac}: Drucker in Windows gekoppelt?", mac=mac))
        transport: Transport = SerialTransport(port, open_timeout=open_timeout)
    elif spec.lower().startswith("file:"):
        transport = FileTransport(Path(spec[5:]))
    elif re.fullmatch(r"(?i)(com:)?COM\d+", spec):
        transport = SerialTransport(spec.split(":")[-1].upper(), open_timeout=open_timeout)
    elif spec == "ble" or spec.lower().startswith("ble:"):
        address = normalize_address(spec[4:]) if spec.lower().startswith("ble:") else None
        transport = BleTransport(address, names=ble_names, scan_timeout_s=ble_scan_timeout_s,
                                 open_timeout=open_timeout, backend_factory=ble_backend_factory)
    elif spec == "usb" or spec.lower().startswith("usb:"):
        if "usb" not in experimental:
            raise ValueError(
                _t("USB-Transport ist experimentell: in calibration.json \"experimental\": [\"usb\"] eintragen (siehe tapesmith usb)"))
        path = spec[4:] if spec.lower().startswith("usb:") else None
        kwargs = {"open_timeout": open_timeout}
        if usb_opener is not None:
            kwargs["opener"] = usb_opener
        transport = UsbPrintTransport(path, **kwargs)
    else:
        raise ValueError(
            _t("Unbekannter Transport '{spec}' (erlaubt: auto, COMn, file:pfad, ble[:adresse], usb[:pfad])", spec=spec))
    return HexLogTransport(transport, hexlog) if hexlog else transport
