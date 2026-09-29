"""Verbindungsassistent-Kern: Port über die MAC finden, Drucker ansprechen,
Konfiguration speichern, optional ein Testlabel drucken."""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field

from tapesmith.config import normalize_mac
from tapesmith.errors import EXIT_ERROR, EXIT_OK, EXIT_UNREACHABLE, explain
from tapesmith.protocol.status import decode
from tapesmith.transport.btports import list_bt_ports
from tapesmith.i18n import _t


@dataclass
class SetupStep:
    name: str
    ok: bool
    detail: str
    hint: str = ""


@dataclass
class SetupResult:
    ok: bool
    port: str | None
    mac: str | None
    serial: str | None
    firmware: str | None
    saved: bool
    printed: bool
    steps: list[SetupStep] = field(default_factory=list)
    exit_code: int = EXIT_OK

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "port": self.port,
            "mac": self.mac,
            "serial": self.serial,
            "firmware": self.firmware,
            "saved": self.saved,
            "printed": self.printed,
            "steps": [dataclasses.asdict(step) for step in self.steps],
            "exit_code": self.exit_code,
        }


def _decode(buf: bytes, codes):
    """Ruft protocol.status.decode auf, mit Codes, falls die installierte Version sie schon kennt."""
    try:
        return decode(buf, codes)
    except TypeError:
        return decode(buf)


def _failed(steps: list[SetupStep], mac: str | None, exit_code: int, port: str | None = None) -> SetupResult:
    return SetupResult(
        ok=False, port=port, mac=mac, serial=None, firmware=None,
        saved=False, printed=False, steps=steps, exit_code=exit_code,
    )


def run_setup(
    *,
    mac: str | None,
    port: str | None,
    ports_reader=None,
    probe: Callable[[str], list[tuple[bytes, bytes]]],
    save: Callable[[dict], object],
    test_print: Callable[[str], None] | None = None,
    codes=None,
) -> SetupResult:
    steps: list[SetupStep] = []
    resolved_mac = normalize_mac(mac) if mac else None
    resolved_port = port

    if resolved_port:
        steps.append(SetupStep("Port", True, f"{resolved_port} (vorgegeben)"))
    else:
        outgoing = [p for p in list_bt_ports(ports_reader) if p.outgoing]
        candidates = [p for p in outgoing if p.mac == resolved_mac] if resolved_mac else outgoing
        if len(candidates) == 1:
            chosen = candidates[0]
            resolved_port = chosen.port
            if not resolved_mac:
                resolved_mac = chosen.mac
            steps.append(SetupStep("Port", True, f"{resolved_port} (MAC {chosen.mac})"))
        elif len(candidates) > 1:
            detail = ", ".join(f"{p.port} ({p.mac})" for p in candidates)
            steps.append(SetupStep("Port", False, detail, _t("mit --mac oder --port wählen")))
            return _failed(steps, resolved_mac, EXIT_ERROR)
        else:
            steps.append(SetupStep(
                "Port", False, _t("kein ausgehender Bluetooth-COM-Port gefunden"),
                _t("Drucker einschalten und in Windows unter Bluetooth koppeln")))
            return _failed(steps, resolved_mac, EXIT_UNREACHABLE)

    try:
        handshake = probe(resolved_port)
    except Exception as exc:
        advice = explain(exc)
        steps.append(SetupStep(_t("Drucker ansprechen"), False, advice.title, advice.hint))
        return _failed(steps, resolved_mac, EXIT_UNREACHABLE, resolved_port)

    answers = b"".join(response for _request, response in handshake)
    if not answers:
        steps.append(SetupStep(
            _t("Drucker ansprechen"), False, _t("Port offen, aber keine Antwort"),
            _t("Drucker aus/eingeschlafen? Einschalten und erneut versuchen")))
        return _failed(steps, resolved_mac, EXIT_UNREACHABLE, resolved_port)

    messages = _decode(answers, codes)
    serial = next((m.value for m in messages if m.kind == "serial"), None)
    firmware = next((m.value for m in messages if m.kind == "firmware"), None)
    steps.append(SetupStep(_t("Drucker ansprechen"), True, _t("Seriennummer {serial}, Firmware {firmware}", serial=serial, firmware=firmware)))

    if resolved_mac:
        save({"mac": resolved_mac, "transport": "auto"})
    else:
        save({"transport": resolved_port})
    steps.append(SetupStep(_t("Konfiguration gespeichert"), True, ""))

    printed = False
    ok = True
    exit_code = EXIT_OK
    if test_print is not None:
        try:
            test_print(resolved_port)
            printed = True
            steps.append(SetupStep(_t("Testlabel"), True, "gedruckt"))
        except Exception as exc:
            advice = explain(exc)
            steps.append(SetupStep(_t("Testlabel"), False, advice.title, advice.hint))
            ok = False
            exit_code = EXIT_UNREACHABLE

    return SetupResult(
        ok=ok, port=resolved_port, mac=resolved_mac, serial=serial, firmware=firmware,
        saved=True, printed=printed, steps=steps, exit_code=exit_code,
    )
