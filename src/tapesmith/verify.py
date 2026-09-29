"""Geführte Testreihe am echten Drucker: klärt unbelegte Protokollwerte und kalibriert die Geometrie."""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tapesmith.calibrate import EDGE_STEP_DOTS, edge_test_head, ruler_content
from tapesmith.device.profile import DeviceProfile, load_profile, save_calibration
from tapesmith.protocol.raster import place_on_head
from tapesmith.protocol.status import decode
from tapesmith.transport.base import TransportError
from tapesmith.i18n import _t

RULER_MM = 100
MIN_EDGE_SPAN_DOTS = 44  # mindestens halbe Kopfbreite, sonst ist die Ablesung unplausibel
OPEN_RETRY_DELAY_S = 1.5


@dataclass
class VerifyReport:
    firmware: str | None = None
    results: dict = field(default_factory=dict)
    complete: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


class _RetryingSession:
    """Öffnet eine Sitzung; nach TransportError ein Wiederholversuch nach Wartezeit."""

    def __init__(self, verifier: "Verifier", profile: DeviceProfile):
        self._verifier = verifier
        self._profile = profile
        self._session = None

    def __enter__(self):
        try:
            self._session = self._verifier.open_session(self._profile)
            return self._session.__enter__()
        except TransportError:
            self._verifier.sleep(OPEN_RETRY_DELAY_S)
            self._session = self._verifier.open_session(self._profile)
            return self._session.__enter__()

    def __exit__(self, *exc):
        return self._session.__exit__(*exc)


class Verifier:
    def __init__(self, open_session, profile: DeviceProfile, calibration_file: Path, ask=input, say=print,
                 sleep=time.sleep):
        self.open_session = open_session
        self.profile = profile
        self.calibration_file = Path(calibration_file)
        self.ask = ask
        self.say = say
        self.sleep = sleep
        self.report = VerifyReport()

    def _number(self, question: str, lo: float, hi: float, cast=float):
        while True:
            answer = self.ask(question).strip().replace(",", ".")
            try:
                value = cast(answer)
            except ValueError:
                self.say(_t("Bitte eine Zahl zwischen {lo} und {hi} eingeben.", lo=lo, hi=hi))
                continue
            if lo <= value <= hi:
                return value
            self.say(_t("Bitte eine Zahl zwischen {lo} und {hi} eingeben.", lo=lo, hi=hi))

    def _yes(self, question: str) -> bool:
        return self.ask(question).strip().lower() in ("j", "ja", "y", "yes")

    def _query(self, session, command_hex: str) -> dict:
        raw = session.query(command_hex)
        return {"raw": raw.hex(), "decoded": [m.text for m in decode(raw, self.profile.status_map())]}

    def _connect(self, profile: DeviceProfile) -> _RetryingSession:
        return _RetryingSession(self, profile)

    def run(self) -> VerifyReport:
        report = self.report
        r = report.results

        self.say(_t("Schritt 1/4: Handshake und Statusabfragen"))
        with self._connect(self.profile) as s:
            handshake = s.handshake()
            r["handshake"] = {p.hex(): resp.hex() for p, resp in handshake}
            r["responds"] = any(resp for _, resp in handshake)
            fw = [m.value for _, resp in handshake for m in decode(resp, self.profile.status_map())
                  if m.kind == "firmware"]
            report.firmware = fw[0] if fw else None
            r["battery"] = self._query(s, "1f1108")
            self.ask(_t("Deckel ÖFFNEN, dann Enter drücken"))
            r["lid_open"] = self._query(s, "1f1112")
            r["paper_lid_open"] = self._query(s, "1f1111")
            self.ask(_t("Deckel SCHLIESSEN, dann Enter drücken"))
            r["lid_closed"] = self._query(s, "1f1112")
            r["paper_lid_closed"] = self._query(s, "1f1111")
            self.say(_t("15 Sekunden lang: Deckel einmal öffnen und wieder schließen …"))
            r["spontaneous"] = s.listen(15.0).hex()

        self.say(_t("Schritt 2/4: Kantentest wird gedruckt (ca. 12 cm)"))
        with self._connect(self.profile) as s:
            s.print_image(edge_test_head(self.profile))
        top = self.profile.head_dots - EDGE_STEP_DOTS
        while True:
            first = self._number(_t("Kleinste Zahl, deren Balken VOLLSTÄNDIG sichtbar ist: "), 0, top, int)
            last = self._number(_t("Größte Zahl, deren Balken VOLLSTÄNDIG sichtbar ist: "), first, top, int)
            if last - first >= MIN_EDGE_SPAN_DOTS:
                break
            self.say(_t("Abstand zu klein (mind. {min_edge_span_dots} Punkte), bitte beide Werte erneut ablesen.", min_edge_span_dots=MIN_EDGE_SPAN_DOTS))
        # Balken "last" belegt die Kopfzeilen last..last+3 -> Inhalt reicht von first bis last+3
        offset, dots = first, min(last + EDGE_STEP_DOTS - first, self.profile.head_dots - first)
        r["edge"] = {"first_row": first, "last_row": last, "content_offset": offset, "content_dots": dots}
        r["edge_complete"] = self._yes(_t("War das Label vollständig (nicht abgebrochen)? [j/n] "))
        save_calibration(self.calibration_file, content_offset=offset, content_dots=dots)

        self.say(_t("Schritt 3/4: Lineal 0 bis 100 mm wird gedruckt"))
        calibrated = load_profile(calibration_path=self.calibration_file)
        with self._connect(calibrated) as s:
            s.print_image(place_on_head(ruler_content(calibrated, RULER_MM), calibrated))
        measured = self._number(_t("Gemessener Abstand 0 bis 100 in mm: "), 50, 150)
        leader = self._number(_t("Leeres Band VOR dem 0-Strich in mm: "), 0, 50)
        trailer = self._number(_t("Leeres Band NACH dem 100-Strich in mm: "), 0, 50)
        factor = calibrated.length_factor * RULER_MM / measured  # Lineal lief schon mit diesem Faktor
        r["ruler"] = {"measured_mm": measured, "leader_mm": leader, "trailer_mm": trailer, "length_factor": factor}
        r["ruler_complete"] = self._yes(_t("War das Label vollständig (nicht abgebrochen)? [j/n] "))
        save_calibration(self.calibration_file, length_factor=factor, leader_mm=leader, trailer_mm=trailer)

        self.say(_t("Schritt 4/4: fertig, Ergebnisse gespeichert"))
        report.complete = True
        return report
