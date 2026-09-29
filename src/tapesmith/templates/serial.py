"""Seriennummern bereinigen und aus /dev/disk/by-id-Namen gewinnen."""

import re
from dataclasses import dataclass
from tapesmith.i18n import _t

_SN_PREFIX = re.compile(r"^\s*(?:S/N|SN)\s*:?\s*", re.IGNORECASE)
_NO_SERIAL = ("wwn-", "eui.", "nvme-eui.", "scsi-3")
_PREFIXES = ("ata-", "scsi-SATA_", "usb-", "nvme-")


@dataclass(frozen=True)
class DiskId:
    model: str | None
    serial: str


class SerialNotDerivable(ValueError):
    pass


def clean_serial(raw: str) -> str:
    return re.sub(r"\s+", "", _SN_PREFIX.sub("", raw))


def parse_by_id(name: str) -> DiskId:
    base = name.strip().rsplit("/", 1)[-1]
    base = re.sub(r"-part\d+$", "", base)
    if base.startswith(_NO_SERIAL):
        raise SerialNotDerivable(
            _t("'{base}' enthält nur WWN/EUI, keine Seriennummer. Per 'lsblk -o NAME,SERIAL' auflösen", base=base))
    for prefix in _PREFIXES:
        if base.startswith(prefix):
            rest = base[len(prefix):]
            if prefix == "nvme-":
                rest = re.sub(r"_\d+$", "", rest)
            if prefix == "usb-":
                rest = re.sub(r"-\d+:\d+$", "", rest)
            model, _, serial = rest.rpartition("_")
            if not model or not serial:
                raise SerialNotDerivable(_t("Unbekanntes by-id-Format: {base}", base=base))
            return DiskId(model.replace("_", " "), serial)
    raise SerialNotDerivable(_t("Unbekanntes by-id-Format: {base}", base=base))


def normalize_serial_input(raw: str) -> DiskId:
    text = raw.strip()
    if "/dev/disk/by-id/" in text or re.match(r"^(ata|nvme|scsi|usb|wwn)-|^eui\.", text):
        return parse_by_id(text)
    return DiskId(None, clean_serial(text))


def shorten(serial: str, digits: int = 6) -> str:
    return serial[-digits:] if digits > 0 else serial
