"""Job-Metadaten, Abbruch-Token und die Ausnahme für unvollständige Drucke."""

import dataclasses
import threading
from dataclasses import dataclass, field

from tapesmith.render.compose import LabelSpec
from tapesmith.transport.base import TransportError
from tapesmith.i18n import _t

SOURCES = ("cli", "gui", "hotkey", "api", "mcp", "mqtt", "hotfolder")
KINDS = ("text", "template", "image", "qr", "calibrate", "reprint", "test")

_SPEC_FIELDS = {f.name for f in dataclasses.fields(LabelSpec)}


@dataclass(frozen=True)
class JobMeta:
    source: str = "cli"
    kind: str = "image"
    title: str = ""
    template: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    sensitive: bool = False
    spec: dict | None = None

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(_t("Unbekannte Quelle '{source}' (erlaubt: {items})", source=self.source, items=', '.join(SOURCES)))
        if self.kind not in KINDS:
            raise ValueError(_t("Unbekannte Art '{kind}' (erlaubt: {items})", kind=self.kind, items=', '.join(KINDS)))

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "template": self.template,
            "values": dict(self.values),
            "sensitive": self.sensitive,
            "spec": self.spec,
        }


def spec_to_dict(spec: LabelSpec) -> dict:
    data = dataclasses.asdict(spec)
    data["lines"] = list(data["lines"])
    return data


def spec_from_dict(data: dict) -> LabelSpec:
    unknown = set(data) - _SPEC_FIELDS
    if unknown:
        raise ValueError(_t("Unbekannte LabelSpec-Schlüssel: {sorted}", sorted=sorted(unknown)))
    values = dict(data)
    if "lines" in values:
        values["lines"] = tuple(values["lines"])
    return LabelSpec(**values)


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class IncompletePrint(TransportError):
    def __init__(self, message: str, rows_sent: int, rows_total: int):
        super().__init__(message)
        self.rows_sent = rows_sent
        self.rows_total = rows_total
