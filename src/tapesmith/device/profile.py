"""Geräteprofile: alle Druckermaße, Protokollkonstanten und Statuscodes an einer Stelle."""

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tapesmith import fileutil
from tapesmith.protocol.status import DEFAULT_CODES, StatusCodes
from tapesmith.i18n import _t

CALIBRATION_KEYS = (
    "content_dots", "content_offset", "feed_seconds", "pacing_margin_seconds",
    "response_timeout_s", "length_factor", "leader_mm", "trailer_mm",
    "block_rows", "experimental",
)

EXPERIMENTAL_FLAGS = ("usb",)


def _parse_status_codes(raw: dict, hint) -> tuple[tuple[str, int, str], ...]:
    triples: list[tuple[str, int, str]] = []
    for kind, mapping in raw.items():
        for hex_key, meaning in mapping.items():
            try:
                byte = int(hex_key, 16)
            except ValueError as exc:
                raise ValueError(
                    _t("Ungültiger Hex-Schlüssel status_codes.{kind}.{hex_key!r} (Datei: {hint})", kind=kind, hex_key=hex_key, hint=hint)) from exc
            triples.append((kind, byte, meaning))
    return tuple(triples)


@dataclass(frozen=True)
class DeviceProfile:
    model: str
    head_dots: int
    content_dots: int
    content_offset: int
    dots_per_mm: int
    speed_mm_s: float
    feed_seconds: float
    pacing_margin_seconds: float
    response_timeout_s: float
    length_factor: float
    leader_mm: float
    trailer_mm: float
    init_packets: tuple[bytes, ...]
    feed_command: bytes
    verified: tuple[str, ...]
    status_codes: tuple[tuple[str, int, str], ...] = ()
    block_rows: int = 0                   # Blockmodus: 0 = aus (ein Rasterkopf wie bisher), sonst 1..255 Zeilen je Block
    experimental: tuple[str, ...] = ()    # z. B. ("usb",)

    @property
    def bytes_per_line(self) -> int:
        return self.head_dots // 8

    def status_map(self) -> StatusCodes:
        if not self.status_codes:
            return {kind: dict(codes) for kind, codes in DEFAULT_CODES.items()}
        out: StatusCodes = {}
        for kind, byte, meaning in self.status_codes:
            out.setdefault(kind, {})[byte] = meaning
        return out


def load_profile(model: str = "p12", calibration_path: Path | None = None) -> DeviceProfile:
    text = resources.files("tapesmith.device.profiles").joinpath(f"{model}.json").read_text(encoding="utf-8")
    raw = json.loads(text)
    if calibration_path is not None and calibration_path.exists():
        raw.update(json.loads(calibration_path.read_text(encoding="utf-8")))
    hint = calibration_path if calibration_path is not None else f"{model}.json"
    block_rows = int(raw.get("block_rows", 0))
    if not 0 <= block_rows <= 255:
        raise ValueError(_t("block_rows muss 0 (aus) oder 1..255 sein, ist {block_rows} (Datei: {hint})", block_rows=block_rows, hint=hint))
    experimental = tuple(raw.get("experimental", []))
    unknown_flags = [flag for flag in experimental if flag not in EXPERIMENTAL_FLAGS]
    if unknown_flags:
        raise ValueError(
            _t("Unbekannte experimental-Schalter {unknown_flags} (erlaubt: {list}, Datei: {hint})", unknown_flags=unknown_flags, list=list(EXPERIMENTAL_FLAGS), hint=hint))
    try:
        profile = DeviceProfile(
            model=raw["model"],
            head_dots=int(raw["head_dots"]),
            content_dots=int(raw["content_dots"]),
            content_offset=int(raw["content_offset"]),
            dots_per_mm=int(raw["dots_per_mm"]),
            speed_mm_s=float(raw["speed_mm_s"]),
            feed_seconds=float(raw["feed_seconds"]),
            pacing_margin_seconds=float(raw["pacing_margin_seconds"]),
            response_timeout_s=float(raw["response_timeout_s"]),
            length_factor=float(raw["length_factor"]),
            leader_mm=float(raw["leader_mm"]),
            trailer_mm=float(raw["trailer_mm"]),
            init_packets=tuple(bytes.fromhex(p) for p in raw["init_packets"]),
            feed_command=bytes.fromhex(raw["feed_command"]),
            verified=tuple(raw.get("verified", [])),
            status_codes=_parse_status_codes(raw.get("status_codes", {}), hint),
            block_rows=block_rows,
            experimental=experimental,
        )
    except KeyError as exc:
        raise ValueError(_t("Profil unvollständig, Schlüssel fehlt: {exc} (Datei: {hint})", exc=exc, hint=hint)) from exc
    if profile.head_dots % 8:
        raise ValueError(_t("head_dots={head_dots} ist kein Vielfaches von 8", head_dots=profile.head_dots))
    if profile.content_offset < 0 or profile.content_offset + profile.content_dots > profile.head_dots:
        raise ValueError(
            _t("Inhalt (Offset {content_offset} + {content_dots} Punkte) passt nicht auf den Kopf ({head_dots} Punkte)", content_offset=profile.content_offset, content_dots=profile.content_dots, head_dots=profile.head_dots))
    return profile


def remove_calibration(path: Path, *keys: str) -> None:
    """Kalibrierwerte entfernen: danach gilt wieder der Wert aus dem Geräteprofil."""
    unknown = set(keys) - set(CALIBRATION_KEYS)
    if unknown:
        raise KeyError(_t("Keine Kalibrierwerte: {sorted}", sorted=sorted(unknown)))
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in keys:
        data.pop(key, None)
    fileutil.atomic_write_text(path, json.dumps(data, indent=2))


def save_calibration(path: Path, **values) -> None:
    unknown = set(values) - set(CALIBRATION_KEYS)
    if unknown:
        raise KeyError(_t("Keine Kalibrierwerte: {sorted}", sorted=sorted(unknown)))
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(values)
    fileutil.atomic_write_text(path, json.dumps(data, indent=2))
