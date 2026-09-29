"""Selbstdiagnose: Was fehlt, damit gedruckt werden kann, mit konkretem Hinweis."""

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from tapesmith import paths
from tapesmith.device.profile import load_profile
from tapesmith.lock import PrinterBusy, PrintLock
from tapesmith.protocol.status import decode
from tapesmith.render import zxing
from tapesmith.i18n import _t


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def run_checks(mac: str, port_finder, connect=None, lock_factory=PrintLock,
              extra_checks: Sequence[Callable[[], Check]] = ()) -> list[Check]:
    checks: list[Check] = []
    profile = None
    try:
        profile = load_profile(calibration_path=paths.calibration_path())
        checks.append(Check(_t("Geräteprofil"), True,
                            _t("{model}, Inhalt {content_dots} Punkte ab Offset {content_offset}", model=profile.model, content_dots=profile.content_dots, content_offset=profile.content_offset)))
    except Exception as exc:
        checks.append(Check(_t("Geräteprofil"), False, str(exc), _t("calibration.json prüfen: {calibration_path}", calibration_path=paths.calibration_path())))

    port = port_finder(mac)
    mac_text = f"MAC {mac}" if mac else _t("ohne gespeicherte MAC")
    if port:
        checks.append(Check(_t("Bluetooth-Port"), True, _t("{port} (ausgehend, {mac_text})", port=port, mac_text=mac_text)))
    else:
        checks.append(Check(_t("Bluetooth-Port"), False, _t("kein ausgehender COM-Port ({mac_text})", mac_text=mac_text),
                            _t("Drucker einschalten, in Windows unter Bluetooth-Geräte koppeln und p12 setup ausführen")))

    try:
        with lock_factory():
            pass
        checks.append(Check(_t("Drucksperre"), True, _t("frei")))
    except PrinterBusy as exc:
        checks.append(Check(_t("Drucksperre"), False, str(exc), _t("Anderes P12-Programm beenden")))

    if connect is not None:
        if not port:
            checks.append(Check(_t("Drucker antwortet"), False, _t("übersprungen (kein Port)")))
        else:
            try:
                handshake = connect(port)
                answers = b"".join(resp for _, resp in handshake)
                if answers:
                    codes = profile.status_map() if profile is not None else None
                    texts = ", ".join(m.text for m in decode(answers, codes))
                    checks.append(Check(_t("Drucker antwortet"), True, texts))
                else:
                    checks.append(Check(_t("Drucker antwortet"), False, _t("Port offen, aber keine Antwort"),
                                        _t("Drucker aus/eingeschlafen? Einschalten und erneut versuchen")))
            except Exception as exc:
                checks.append(Check(_t("Drucker antwortet"), False, str(exc),
                                    _t("Drucker einschalten; Handy-App trennen (nur ein Gerät gleichzeitig)")))

    for check_fn in extra_checks:
        try:
            checks.append(check_fn())
        except Exception as exc:
            name = getattr(check_fn, "__name__", check_fn.__class__.__name__)
            checks.append(Check(name, False, str(exc)))
    return checks


def decoder_check() -> Check:
    """Barcode-Decoder (zxing-cpp, optional): ohne ihn wird gedruckt, nur Rücklesen und SN-Scan fehlen.
    Deshalb nie ein Fehler, nur der Status mit Grund."""
    return Check(_t("Barcode-Decoder"), True, zxing.status_text())


def format_checks(checks: list[Check], as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2)
    lines = []
    for c in checks:
        lines.append(f"{'[OK]    ' if c.ok else '[FEHLER]'} {c.name}: {c.detail}")
        if c.hint and not c.ok:
            lines.append(f"         -> {c.hint}")
    return "\n".join(lines)
